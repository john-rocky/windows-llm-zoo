<#
Runs the units of one plan (pc\plans\<sitting>.json, written on the Mac by tools/make_plan.py) on this PC.
Windows PowerShell 5.1. Start it detached (pc\launch.ps1), never from an SSH session that may close.

  powershell -NoProfile -ExecutionPolicy Bypass -File chain.ps1 -Plan <plan.json> -Mode first|timed [-HoldAtEndMin 40]

-Mode first: one run per unit, no lock, active\Z2-<sitting>.txt says what runs; a unit that fails still writes its JSON. Not under
  yield_run: a suspended engine keeps its GPU memory and Foundry's daemon sits outside the suspended tree, so another
  lane's gate would wait on them. Instead, while another lane holds busy.txt nothing starts, and a run in flight is
  killed (the daemon stopped), its files removed, and the run taken again once the lock is free; except a python engine
  on the NPU or the CPU, which is suspended there and resumed (it holds no GPU memory, and a slow one outlasts the gaps).
-Mode timed: the plan's runs per unit (3), under the Z2 lock that the Mac took and gated before starting this
  (tools/sitting.sh). Before each run, the bench job's quiet gate (zlib Wait-RunQuiet); 30 s between runs. Before a run,
  while another lane waits and the lock has been held 30 min or the run would end past 30 min of the hold, the lock is
  released for 16.5 min, taken again once the other lane's lock has been gone 60 s, settled 60 s and gated again; the
  lock's text says until when the run is expected to run.
  At the end the lock stays ours for -HoldAtEndMin minutes so the Mac can run the closing anchor rows; the chain then
  releases it if it is still ours.
Every run writes <runs>\<sitting>\<model>\<cell>\run<k>.meta.json (the chain's view: gate, load before and after, peak
working set, GPU memory per adapter) next to the runner's run<k>.json; a run already on disk is skipped (resume).
#>
param(
    [Parameter(Mandatory = $true)][string]$Plan,
    [Parameter(Mandatory = $true)][ValidateSet("first", "timed")][string]$Mode,
    [int]$HoldAtEndMin = 40,
    [int]$BetweenRunsSeconds = 30
)
. "$PSScriptRoot\zlib.ps1"
$p = Get-Content $Plan -Raw -Encoding UTF8 | ConvertFrom-Json
$sit = $p.sitting
$out = Join-Path $Root "runs\$sit"
New-Item -ItemType Directory -Force $out | Out-Null
$log = Join-Path $out "chain.log"
$done = Join-Path $out "chain.done"
if (Test-Path $done) { Remove-Item $done -Force }   # a done file of an earlier start is not this run's (seen on this PC)
$prompt = Join-Path $Root "pc\short-chat.txt"
$active = Join-Path $Pcup "active\Z2-$sit.txt"   # one note per chain: a walk may run beside it
# After a duty gap, how long the lock must stay free once another lane gave it back before Z2 takes it again (s): the
# plan's retake_free_sec (a rerun plan takes its sitting's), else 60 (the shared PC's form of 2026-11-09). A sitting
# whose window hands the lock from one lane to another that comes after the first one's return line sets more.
$RetakeFreeSec = 60
try {
    if ($p.retake_free_sec) { $RetakeFreeSec = [int]$p.retake_free_sec }
    elseif ($p.rerun_of) {
        $basePlan = Join-Path (Split-Path -Parent $Plan) "$($p.rerun_of).json"
        if (Test-Path $basePlan) {
            $basePj = Get-Content $basePlan -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($basePj.retake_free_sec) { $RetakeFreeSec = [int]$basePj.retake_free_sec }
        }
    }
} catch { $RetakeFreeSec = 60 }
$cuda12 = Join-Path $Root "cuda12\dll"
Say $log "chain start: plan $Plan mode $Mode, $(@($p.units).Count) units, pid $PID"
if ($RetakeFreeSec -ne 60) { Say $log "after a duty gap the lock is taken back once it has been free $RetakeFreeSec s after another lane's return (the plan's retake_free_sec)" }
Write-JsonFile (Join-Path $out "env.$(Get-Date -Format yyyyMMddTHHmmss).json") (Get-HostEnv)

# adapter LUID -> kind, from the engine types of the GPU Engine counters (L8: OFA / JPEG = NVIDIA, GSC /
# VideoProcessing = Intel GPU, Neural only = NPU); read once
function Get-LuidKinds {
    $m = @{}
    try {
        $names = (New-Object Diagnostics.PerformanceCounterCategory("GPU Engine")).GetInstanceNames()
        foreach ($n in $names) {
            if ($n -match "luid_(0x[0-9A-Fa-f]+_0x[0-9A-Fa-f]+)_phys_\d+_eng_\d+_engtype_(.*)$") {
                $l = $Matches[1]; $t = $Matches[2]
                if (-not $m.ContainsKey($l)) { $m[$l] = New-Object System.Collections.Generic.HashSet[string] }
                [void]$m[$l].Add($t)
            }
        }
    } catch { }
    $kinds = @{}
    foreach ($l in $m.Keys) {
        $t = @($m[$l])
        $k = if ($t -match "OFA|JPEG") { "nvidia" } elseif ($t -match "GSC|VideoProcessing") { "intel-gpu" } elseif (($t -join ",") -match "^(Neural|Compute)") { "npu?" } else { "?" }
        $kinds[$l] = [ordered]@{ kind = $k; engtypes = ($t | Sort-Object) -join "," }
    }
    return $kinds
}
$luids = Get-LuidKinds
Write-JsonFile (Join-Path $out "luids.json") $luids
Say $log "adapters: $(($luids.Keys | ForEach-Object { "$_=$($luids[$_].kind)" }) -join ', ')"

function F([string]$FLog, [string[]]$Parts) {
    $ErrorActionPreference = "Continue"   # the CLI's stderr lines under Stop would end the chain (5.1, 2>&1)
    Append-Utf8 $FLog "`r`n--- foundry $($Parts -join ' ')  [$(Get-Date -Format o)]`r`n"
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $o = & foundry @Parts 2>&1 | ForEach-Object { "$_" }
    $code = $LASTEXITCODE
    Append-Utf8 $FLog (($o -join "`r`n") + "`r`n[exit=$code, $([math]::Round($sw.Elapsed.TotalSeconds, 2)) s]`r`n")
    return [pscustomobject]@{ code = $code; s = [math]::Round($sw.Elapsed.TotalSeconds, 3); text = ($o -join "`n") }
}

# One engine process under a 0.5 s poll: its peak working set, its GPU memory per adapter every 2 s, the NVIDIA line
# every 5 s; killed with its tree after the unit's timeout. $Watch = another process to read (Foundry's daemon).
# What a first-pass cell gives way to: every other lane's lock on a GPU; on the NPU or the CPU only a timing lock (a lock
# marked "not a timing" comes every few minutes: a slow cell would never end, and it needs the RTX, not a quiet CPU)
$script:CellOffGpu = $false
function Test-CellYield { if ($script:CellOffGpu) { return (Test-OtherTiming) }; return (Test-OtherBusy) }

# taskkill's stderr (a child that is already gone) under Stop would end the chain (5.1, 2>&1): Continue in here
function Stop-EngineTree([int]$EnginePid) {
    $ErrorActionPreference = "Continue"
    & "$env:SystemRoot\System32\taskkill.exe" /PID $EnginePid /T /F 2>&1 | Out-Null
}

function Invoke-Engine([string]$Exe, [string[]]$ArgList, [string]$Base, [int]$TimeoutMin, $Watch, [bool]$YieldCheck = $false, [bool]$SuspendOnYield = $false) {
    $quoted = @($ArgList | ForEach-Object { if ($_ -match '[\s"]') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ } })
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $proc = Start-Process -FilePath $Exe -ArgumentList ($quoted -join " ") -RedirectStandardOutput "$Base.stdout.txt" `
        -RedirectStandardError "$Base.stderr.txt" -PassThru -WindowStyle Hidden
    $null = $proc.Handle
    $peak = [int64]0; $wpeak = [int64]0; $gpu = @{}; $wgpu = @{}; $nvSamples = @(); $next2 = 2.0; $next5 = 5.0; $timedOut = $false
    $yielded = $false; $susp = 0.0; $suspN = 0
    $engPid = $null; $engProc = $null
    try {
    while (-not $proc.HasExited) {
        # the venv's python.exe is a launcher that runs the interpreter as its child: watch the pid the runner prints
        if (-not $engPid) {
            try {
                $sfs = [IO.File]::Open("$Base.stdout.txt", [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete)
                $srd = New-Object IO.StreamReader($sfs); $stxt = $srd.ReadToEnd(); $srd.Close()
                if ($stxt -match 'ENGINE_PID (\d+)') {
                    $engPid = [int]$Matches[1]
                    $engProc = Get-Process -Id $engPid -ErrorAction SilentlyContinue
                    if ($engProc) { $null = $engProc.Handle }
                }
            } catch { }
        }
        $tgt = if ($engProc) { $engProc } else { $proc }
        try { $tgt.Refresh(); if ($tgt.PeakWorkingSet64 -gt $peak) { $peak = $tgt.PeakWorkingSet64 } } catch { }
        if ($Watch) { try { $Watch.Refresh(); if ($Watch.PeakWorkingSet64 -gt $wpeak) { $wpeak = $Watch.PeakWorkingSet64 } } catch { } }
        $t = $sw.Elapsed.TotalSeconds
        if ($t -ge $next2) {
            $gpu = Merge-GpuPeak $gpu (Get-ProcGpuMiB $(if ($engPid) { $engPid } else { $proc.Id }))
            if ($Watch) { $wgpu = Merge-GpuPeak $wgpu (Get-ProcGpuMiB $Watch.Id) }
            $next2 += 2.0
        }
        if ($t -ge $next5) { $nvSamples += "$([int]$t)s $(Get-NvidiaLine)"; $next5 += 5.0 }
        if ($YieldCheck -and (Test-CellYield)) {
            if ($SuspendOnYield) {
                $hs = Suspend-Tree $proc.Id; $s0 = Get-Date
                # a Foundry CPU cell: the daemon does the work and sits outside the runner's tree
                if ($Watch) { $hw = Suspend-Tree $Watch.Id; foreach ($k in @($hw.Keys)) { $hs[$k] = $hw[$k] } }
                Say $log "$Base suspended ($($hs.Count) processes) while another lane holds busy.txt ($((Read-Busy).Text))"
                do {
                    while (Test-CellYield) { Start-Sleep -Seconds 15 }
                    if ($script:CellRamWant -gt 0) { [void](Wait-FreeRam $script:CellRamWant $log "$Base resume") }
                } while (Test-CellYield)
                $rn = Resume-Tree $hs; $susp += ((Get-Date) - $s0).TotalSeconds; $suspN++
                Say $log "$Base resumed ($rn processes) after $([int]((Get-Date) - $s0).TotalSeconds) s"
                continue
            }
            $yielded = $true
            Stop-EngineTree $proc.Id
            break
        }
        if (($t - $susp) -ge $TimeoutMin * 60) {
            $timedOut = $true
            Stop-EngineTree $proc.Id
            break
        }
        Start-Sleep -Milliseconds 500
    }
    } finally {
        # a chain error inside the poll must not leave the engine running on a device
        if (-not $proc.HasExited) { Stop-EngineTree $proc.Id }
    }
    $proc.WaitForExit()
    return [ordered]@{ exitCode = $(if ($timedOut -or $yielded) { $null } else { $proc.ExitCode }); timedOut = $timedOut; yielded = $yielded; suspendedSeconds = [math]::Round($susp, 1); suspensions = $suspN; enginePid = $engPid
        elapsedSeconds = [math]::Round($sw.Elapsed.TotalSeconds, 3); peakWorkingSetBytes = $peak; gpuMiBPeak = $gpu
        watchPeakWorkingSetBytes = $wpeak; watchGpuMiBPeak = $wgpu; nvidiaSamples = $nvSamples }
}

# A foundrylocald this chain did not start belongs to another lane (one Foundry Local service per Windows user): a
# Foundry run waits for it to go, and after $MaxMin minutes is written as not run instead of stopping it.
$script:OurDaemons = @()
function Wait-ForeignDaemon([string]$Log, [int]$MaxMin = 30) {
    $until = (Get-Date).AddMinutes($MaxMin); $said = $false
    while ($true) {
        $f = @(Get-Process foundrylocald -ErrorAction SilentlyContinue | Where-Object { $script:OurDaemons -notcontains $_.Id } | ForEach-Object { $_.Id })
        if (-not $f.Count) { return "none" }
        if ((Get-Date) -gt $until) { return "a Foundry daemon Z2 did not start (pid $($f -join ',')) still ran after $MaxMin min" }
        if (-not $said) { Say $Log "a Foundry daemon Z2 did not start is running (pid $($f -join ',')): waiting up to $MaxMin min"; $said = $true }
        Start-Sleep -Seconds 30
    }
}
function Stop-Daemon([string]$FLog) {
    $null = F $FLog @("server", "stop")
    for ($i = 0; $i -lt 30; $i++) { if (-not (Get-Process foundrylocald -ErrorAction SilentlyContinue)) { return "stopped" }; Start-Sleep -Seconds 1 }
    Get-Process foundrylocald -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Seconds 2
    return "killed"
}

# One run of a unit; returns the chain's meta (engine.yielded = killed because another lane took busy.txt, first mode)
function Run-Once($u, [int]$k, [string]$base) {
    $yc = ($Mode -eq "first")
    $gate = $null
    if ($Mode -eq "timed") {
        $gate = Wait-RunQuiet $log -Engines:([bool]$u.engines_gate) -RamNeedGB $(if ($u.ram_need_gb) { [double]$u.ram_need_gb } else { 8 })
        # no run starts without the RAM it needs: the sitting stops here (the holders are in the log; tools/sitting.sh
        # skips the rerun after a FAIL and closes with the tail anchors)
        if ($gate.quietGate -eq "ram-short") { throw "per-run gate: available RAM $($gate.availGB) GB under the $($gate.ramNeedGB) GB of $($u.cell) for 10 min in a row (holders in the log)" }
    }
    $before = [ordered]@{ load = (Measure-Load 1); nvidia = (Get-NvidiaLine); availGB = (Get-AvailGB) }
    $py = Join-Path $Root ".venv-$($u.venv)\Scripts\python.exe"
    $meta = [ordered]@{ cell = $u.cell; run = $k; mode = $Mode; sitting = $sit; start = (Get-Date -Format o); osBuild = (Get-OsBuild); gate = $gate; before = $before }
    if ($u.kind -eq "python") {
        $a = @("-u", (Join-Path $Root "pc\$($u.script)")) + @(@($u.args) | ForEach-Object { "$_".Replace("{HOME}", $HomeDir).Replace("{ROOT}", $Root) }) + @("--prompt-file", $prompt, "--out", "$base.json")
        $meta.command = "$py $($a -join ' ')"
        Say $log "$($u.cell) run $k start"
        # a first-pass NPU or CPU engine is suspended under another lane's lock (a slow CPU cell takes longer than the gaps
        # between locks, killed and taken again it would never end); a GPU engine would keep its GPU memory: stopped
        $meta.engine = Invoke-Engine $py $a $base ([int]$u.timeout_min) $null $yc ($yc -and $u.cell -match "_npu_|_cpu_")
    } elseif ($u.kind -eq "foundry") {
        $fl = "$base.foundry.txt"
        $meta.foreignDaemon = Wait-ForeignDaemon $log
        if ($meta.foreignDaemon -ne "none") {
            Write-JsonFile "$base.json" ([ordered]@{ status = "ERROR"; error = "not run: $($meta.foreignDaemon)" })
            $meta.engine = [ordered]@{ exitCode = $null; timedOut = $false; yielded = $false }
            $meta.end = Get-Date -Format o
            return $meta
        }
        $meta.daemonStop0 = Stop-Daemon $fl
        if ($env:Path -notlike "*$cuda12*") { $env:Path = "$cuda12;$env:Path" }   # Foundry's CUDA EP reads CUDA 12 from PATH
        # a Foundry fix's plan can name environment variables for this daemon and commands to run before the load
        $daemonEnv = @()
        if ($u.daemon_env) {
            foreach ($p in $u.daemon_env.PSObject.Properties) { Set-Item "env:$($p.Name)" "$($p.Value)"; $daemonEnv += $p.Name }
            $meta.daemonEnv = $u.daemon_env
        }
        $meta.serverStart = F $fl @("server", "start")
        foreach ($n in $daemonEnv) { Remove-Item "env:$n" -ErrorAction SilentlyContinue }
        $d = Get-Process foundrylocald -ErrorAction SilentlyContinue | Select-Object -First 1
        $meta.daemonPid = if ($d) { $d.Id } else { $null }
        if ($d) { $script:OurDaemons += $d.Id }
        if ($u.pre_foundry) {
            $meta.preFoundry = @(foreach ($parts in @($u.pre_foundry)) {
                $pa = @(@($parts) | ForEach-Object { "$_".Replace("{HOME}", $HomeDir).Replace("{ROOT}", $Root) })
                [ordered]@{ command = ($pa -join " "); result = (F $fl $pa) }
            })
        }
        $meta.modelLoad = F $fl @("model", "load", $u.model_id)
        if ($d) { try { $d.Refresh(); $meta.daemonPeakAfterLoadBytes = $d.PeakWorkingSet64 } catch { } }
        $meta.gpuAfterLoad = if ($d) { Get-ProcGpuMiB $d.Id } else { $null }
        if ($yc -and (Test-CellYield)) {
            $meta.engine = [ordered]@{ exitCode = $null; timedOut = $false; yielded = $true }
        } else {
            $a = @("-u", (Join-Path $Root "pc\run_foundry.py"), "--model", $u.model_id, "--path", $u.path, "--prompt-file", $prompt, "--out", "$base.json")
            $meta.command = "$py $($a -join ' ')"
            Say $log "$($u.cell) run $k start (daemon $($meta.daemonPid), load exit $($meta.modelLoad.code) in $($meta.modelLoad.s) s)"
            $meta.engine = Invoke-Engine $py $a $base ([int]$u.timeout_min) $d $yc ($yc -and $u.cell -match "_cpu_")
        }
        if ($d) { try { $d.Refresh(); $meta.daemonPeakWorkingSetBytes = $d.PeakWorkingSet64 } catch { } }
        $meta.modelUnload = F $fl @("model", "unload", $u.model_id)
        $meta.daemonStop = Stop-Daemon $fl
    }
    $meta.after = [ordered]@{ load = (Measure-Load 1); nvidia = (Get-NvidiaLine) }
    $meta.end = Get-Date -Format o
    return $meta
}

function Run-Unit($u, [int]$k) {
    $dir = Join-Path $out $u.cell
    New-Item -ItemType Directory -Force $dir | Out-Null
    $base = Join-Path $dir "run$k"
    if (Test-Path "$base.meta.json") { Say $log "$($u.cell) run $k on disk, skipped"; return }
    $script:CellOffGpu = [bool]($u.cell -match "_npu_|_cpu_")
    # the queue's RAM rule for a cell over 8 GB (a timed cell has it in Wait-RunQuiet); first mode only, nothing else waits there
    $script:CellRamWant = if ($Mode -eq "first" -and [double]$u.ram_need_gb -gt 8) { [math]::Max(12, [double]$u.ram_need_gb + 2) } else { 0 }
    for ($try = 1; $try -le 20; $try++) {
        if ($Mode -eq "first") {
            do {
                if (Test-CellYield) {
                    Say $log "another lane holds busy.txt ($((Read-Busy).Text)): waiting before $($u.cell) run $k"
                    while (Test-CellYield) { Start-Sleep -Seconds 30 }
                }
                if ($script:CellRamWant -gt 0) { [void](Wait-FreeRam $script:CellRamWant $log "$($u.cell) run $k") }
            } while (Test-CellYield)
        }
        $meta = Run-Once $u $k $base
        if (-not $meta.engine.yielded) { break }
        Say $log "$($u.cell) run $k stopped: another lane took busy.txt; its files removed, taken again when the lock is free"
        Remove-Item "$base.json", "$base.stdout.txt", "$base.stderr.txt", "$base.foundry.txt" -ErrorAction SilentlyContinue
    }
    $meta.tries = $try
    Write-JsonFile "$base.meta.json" $meta
    $res = if (Test-Path "$base.json") { (Get-Content "$base.json" -Raw -Encoding UTF8 | ConvertFrom-Json).status } else { "no runner JSON" }
    Say $log "$($u.cell) run $k end: exit $($meta.engine.exitCode), $res, $($meta.engine.elapsedSeconds) s"
    Note-RunSec $u.cell $meta.engine.elapsedSeconds
    $script:runsSinceTake++
}

# Timed mode, before every run (a slow CPU cell's three runs take 1.5 h: a check per unit would hold the lock that long),
# while another lane waits: the lock held 30 min, or the run would end past 30 min of the hold -> release for 16.5 min,
# not 15 (a lane that takes the lock after 15 free minutes, as another lane's lock script did, would race this chain's
# retake every time; 2026-11-08), take it back once the other lane's lock has been gone 60 s, settle 60 s, gate again.
# A run right after a take starts whatever its expected length (one longer than 30 min would never start otherwise).
# held since Z2 took the lock (the marker's creation time; Touch-Busy rewrites its text, not its creation time): the
# anchors and bench rows sitting.sh times before this chain starts count too (walk-timed, 11-08: about 50 min at first)
$script:held = if ($Mode -eq "timed" -and (Test-OursBusy)) { (Get-Item $Busy).CreationTime } else { Get-Date }
# runs since the lock was taken; a chain that starts under a lock held a minute or more counts as past a take
$script:runsSinceTake = if (((Get-Date) - $script:held).TotalMinutes -ge 1) { 1 } else { 0 }
# What one run of a cell is expected to take, in seconds (0 = not known): the longest elapsed of that cell's runs this
# chain has seen (its own; for a <sitting>-rerun plan those of <sitting> too) plus 60 s for the start and the gate.
# The lock's text carries the expected end ("run until about HH:mm", else the run's time limit) for the lanes that wait.
$script:runSec = @{}
function Note-RunSec([string]$Cell, $Sec) {
    try {
        $s = [double]$Sec
        if ($s -gt 0 -and (-not $script:runSec.ContainsKey($Cell) -or $s -gt $script:runSec[$Cell])) { $script:runSec[$Cell] = $s }
    } catch { }
}
function Get-RunEstSec([string]$Cell) {
    if ($script:runSec.ContainsKey($Cell)) { return [double]$script:runSec[$Cell] + 60 }
    return 0
}
if ($sit -match '^(.+)-rerun$') {
    $seedDir = Join-Path $Root "runs\$($Matches[1])"
    foreach ($su in @($p.units)) {
        foreach ($mf in @(Get-ChildItem (Join-Path $seedDir "$($su.cell)\run*.meta.json") -ErrorAction SilentlyContinue)) {
            try { Note-RunSec $su.cell (Get-Content $mf.FullName -Raw -Encoding UTF8 | ConvertFrom-Json).engine.elapsedSeconds } catch { }
        }
    }
}
function Invoke-Duty([string]$What, [string]$Cell, [double]$LimitMin = 0) {
    $est = 0
    try { $est = [double](Get-RunEstSec $Cell) } catch { $est = 0 }
    $heldMin = ((Get-Date) - $script:held).TotalMinutes
    $others = @(Get-OthersWaiting)
    $why = ""
    if ($others.Count -gt 0) {
        if ($heldMin -ge 30) { $why = "held $([int]$heldMin) min" }
        elseif ($est -gt 0 -and $script:runsSinceTake -gt 0 -and ($heldMin + $est / 60) -gt 30) {
            $why = "held $([int]$heldMin) min and the next run would end past 30 min (about $([int][math]::Ceiling($est / 60)) min)"
        }
    }
    if ($why) {
        Say $log "duty: $why, others waiting ($($others -join ', ')): release for 16.5 min"
        Release-Busy $log
        Open-Window 990 $log
        Wait-Window 990 $RetakeFreeSec
        Close-Window   # the window's time is over: no stale "open until" while the lock is taken back (11-09)
        while ($true) {
            $t = Take-Busy "sitting $sit (after a duty gap)" $log $RetakeFreeSec
            Close-Window
            if ($t -eq "TIMEOUT") { throw "could not take the lock back" }
            Start-Sleep -Seconds 60
            if ((Pass-LaneGate $log) -eq "PASS") { break }
            Release-Busy $log; Open-Window 600 $log; Wait-Window 600 $RetakeFreeSec; Close-Window
        }
        $script:held = Get-Date
        $script:runsSinceTake = 0
    }
    $until = ""
    if ($est -gt 0) { $until = ", run until about $((Get-Date).AddSeconds($est).ToString('HH:mm'))" }
    elseif ($LimitMin -gt 0) { $until = ", run until $((Get-Date).AddMinutes($LimitMin + 1).ToString('HH:mm')) at the latest (its time limit)" }
    Touch-Busy "sitting $sit $What$until"
}

$status = "OK"
try {
    if ($Mode -eq "timed" -and -not (Test-OursBusy)) { throw "mode timed needs the Z2 lock (tools/sitting.sh takes it and gates first)" }
    if ($Mode -eq "first") { Write-Utf8 $active "Z2 first pass of $sit ($(@($p.units).Count) units, no timing) since $(Get-Date -Format o)" }
    foreach ($u in @($p.units)) {
        $runs = if ($Mode -eq "first") { 1 } else { [int]$u.runs }
        for ($k = 1; $k -le $runs; $k++) {
            if ($Mode -eq "timed") { Invoke-Duty "unit $($u.cell) run $k" $u.cell ([double]$u.timeout_min) }
            Run-Unit $u $k
            if ($Mode -eq "timed" -and $k -lt $runs) { Start-Sleep -Seconds $BetweenRunsSeconds }
        }
    }
} catch {
    $status = "FAIL $($_.Exception.Message)"
    Say $log "chain error: $($_ | Out-String)"
} finally {
    if ($Mode -eq "first" -and (Test-Path $active)) { Remove-Item $active -Force }
    if ($Mode -eq "timed") { Close-Window }
    Write-Utf8 $done "$status $(Get-Date -Format o)"
    Say $log "chain done: $status"
}
if ($Mode -eq "timed" -and $HoldAtEndMin -gt 0) {
    $until = (Get-Date).AddMinutes($HoldAtEndMin)
    while ((Get-Date) -lt $until -and (Test-OursBusy)) { Start-Sleep -Seconds 15 }
    if (Test-OursBusy) { Say $log "the Mac did not release the lock in $HoldAtEndMin min: releasing"; Release-Busy $log }
}
