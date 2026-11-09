<#
Untimed, one detached launch (pc\launch.ps1), not under yield_run: a suspended export keeps its memory (Gemma 4 E4B: 32 GB
of commit), and other lanes' timing gates read free RAM. The NPU-form IR of the models whose published OpenVINO IR does not
give text on the NPU (Qwen3 0.6B / 1.7B and Gemma 4 E4B: not in that form; Qwen3-4B: its int4-ov is int4_sym g128 r1.0 + AWQ,
and the NPU answers it with degenerate tokens, while the same IR on the CPU writes the answer; gemma-4-E2B-it-int4-cw-ov is
used as published). Steps: the export venv .venv-ovexport (pc\req\ovexport.txt), the original checkpoints of
shelf\export_manifest.json (pc\fetch.py, sha-checked, resumable, into hf\), then one optimum-cli export per model into
models\z2-npu\<model>-int4-sym-<g128|cw>-ov with the settings the OpenVINO GenAI NPU docs say an LLM must be exported with
(--weight-format int4 --sym --ratio 1.0, --group-size 128 or -1).
Each step starts only when no timing lock is held (any lane's, this one's too; a lock its lane marks "not a timing", short
checks on the RTX every few minutes, does not count: they would stop a 10-minute export for ever) and, a big model, when
the commit charge in use is low enough and 14 GB of RAM is free; within 5 s of a timing lock it is stopped, its files
dropped, and taken again when the gate opens. It is also stopped when the commit in use passes 80 GB (queue, the RAM
collision of 11-07 23:10, at 83 GB; the commit limit moves with the system-managed page file: 60 to 84 GB seen).
Writes active\Z2-export.txt while it runs, logs\export_npu_<g128|cw>[_<models>].json (per model: command, exit code,
running seconds of the attempt that ended it, attempts, the export tree's peak working set and private bytes (sampled every
30 s), lowest available RAM, highest commit in use, the IR's rt_info and every file's size and sha256 from pc\ir_info.py) and
logs\export_npu_<g128|cw>[_<models>].done ("OK ..." or "FAIL ...") at the end; <models> only with -Only, so an earlier full
run's record stays.

  powershell -NoProfile -ExecutionPolicy Bypass -File pc\export_npu.ps1 [-Group 128|-1] [-Only Qwen3-0.6B,gemma-4-E4B-it]
#>
param([int]$Group = 128, [string]$Only = "")
. "$PSScriptRoot\zlib.ps1"
$ErrorActionPreference = "Continue"
$logs = Join-Path $Root "logs"
New-Item -ItemType Directory -Force $logs | Out-Null
$tag = if ($Group -lt 0) { "cw" } else { "g$Group" }
$want = @($Only -split "," | Where-Object { $_ })
$stem = "export_npu_$tag" + $(if ($want.Count) { "_" + ($want -join "+") } else { "" })
$log = Join-Path $logs "$stem.log"
$done = Join-Path $logs "$stem.done"
$sum = Join-Path $logs "$stem.json"
if (Test-Path $done) { Remove-Item $done -Force }
$active = Join-Path $Pcup "active\Z2-export.txt"
Write-Utf8 $active "Z2 NPU-form export ($tag) into $Root (no timing, stops within 5 s of any lock) since $(Get-Date -Format o)"
Say $log "export_npu start (group $Group, only '$Only')"

function Get-CommitUsedGB { $os = Get-CimInstance Win32_OperatingSystem; [math]::Round(($os.TotalVirtualMemorySize - $os.FreeVirtualMemory) / 1MB, 1) }
function Test-AnyLock { return [bool]((Test-OtherTiming) -or (Test-OursBusy)) }
function Stop-ExportTree([int]$Top) { foreach ($q in (Get-TreePids $Top)) { Stop-Process -Id $q -Force -ErrorAction SilentlyContinue } }
function Wait-ExportGate([string]$What, [double]$MaxUsed, [double]$RamGate, [int]$MaxHours = 12) {
    $until = (Get-Date).AddHours($MaxHours); $said = $false
    while ((Get-Date) -lt $until) {
        $lock = Test-AnyLock; $used = Get-CommitUsedGB; $ram = Get-AvailGB
        if (-not $lock -and $used -le $MaxUsed -and ($RamGate -le 0 -or $ram -ge $RamGate)) { return $true }
        if (-not $said) { Say $log "$What waits: lock $lock, commit in use $used GB (at most $MaxUsed), free RAM $ram GB (at least $RamGate)"; $said = $true }
        Start-Sleep -Seconds 30
    }
    Say $log "$What`: the gate stayed shut for $MaxHours h"
    return $false
}

# 1. the export venv
$uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
if (-not $uv) { $uv = "$env:LOCALAPPDATA\Microsoft\WinGet\Links\uv.exe" }
$venv = Join-Path $Root ".venv-ovexport"
$py = Join-Path $venv "Scripts\python.exe"
$env:UV_LINK_MODE = "copy"
[void](Wait-ExportGate "venv" 1000 0)
if (-not (Test-Path $py)) { & $uv venv $venv --python 3.12 2>&1 | ForEach-Object { Say $log "  $_" } }
& $uv pip install --python $py -r (Join-Path $Root "pc\req\ovexport.txt") 2>&1 | ForEach-Object { Say $log "  $_" }
$s = $LASTEXITCODE
Say $log "venv ovexport: uv pip install exit $s"
$o = & $py -c "import importlib.metadata as m, sys; print(sys.version.split()[0]); [print(d.metadata['Name'], d.version) for d in sorted(m.distributions(), key=lambda d: d.metadata['Name'].lower())]" 2>&1
Write-Utf8 (Join-Path $logs "setup_versions_ovexport.txt") (($o -join "`r`n") + "`r`n")

# 2. the original checkpoints, pinned and sha-checked (fetch.py needs only the standard library)
$flog = Join-Path $logs "fetch_export.log"
$f = 1
for ($try = 1; $try -le 30; $try++) {
    if (-not (Wait-ExportGate "fetch" 1000 0)) { break }
    $fa = "-u $(Join-Path $PSScriptRoot 'fetch.py') --manifest $(Join-Path $Root 'shelf\export_manifest.json') --dest $(Join-Path $Root 'hf')"
    $fp = Start-Process -FilePath $py -ArgumentList $fa -RedirectStandardOutput $flog -RedirectStandardError "$flog.err" -PassThru -WindowStyle Hidden
    $null = $fp.Handle
    $yielded = $false
    while (-not $fp.WaitForExit(5000)) {
        if (Test-AnyLock) { Stop-ExportTree $fp.Id; $yielded = $true; break }
    }
    if (-not $yielded) { $f = $fp.ExitCode; break }
    Say $log "fetch stopped: a lock was taken; taken again when it is free (resumes its files)"
}
Say $log "fetch exit $f"

# 3. one export per model
$env:HF_HUB_OFFLINE = "1"; $env:HF_HUB_DISABLE_TELEMETRY = "1"; $env:PYTHONUTF8 = "1"; $env:PYTHONIOENCODING = "utf-8"
$cli = Join-Path $venv "Scripts\optimum-cli.exe"
# repo, running-minutes limit, task (optimum-cli cannot infer a task from a local folder), most commit in use at the start
# (GB), free RAM at the start (GB; 0 = under the queue's 8 GB line: 3.4 GB and 5.1 GB private when run; Qwen3-4B 9.8 GB)
$models = [ordered]@{ "Qwen3-0.6B" = @("Qwen/Qwen3-0.6B", 30, "text-generation-with-past", 70, 0);
                      "Qwen3-1.7B" = @("Qwen/Qwen3-1.7B", 45, "text-generation-with-past", 70, 0);
                      "Qwen3-4B" = @("Qwen/Qwen3-4B", 60, "text-generation-with-past", 60, 14);
                      "gemma-4-E4B-it" = @("google/gemma-4-E4B-it", 180, "image-text-to-text", 30, 14) }
$res = @(); $bad = @()
if ($s -ne 0 -or $f -ne 0) { $bad += "setup" }
foreach ($m in $models.Keys) {
    if ($want.Count -and -not ($want -contains $m)) { continue }
    if ($bad -contains "setup") { break }
    $repo = $models[$m][0]; $tmin = [int]$models[$m][1]; $task = $models[$m][2]; $maxUsed = [double]$models[$m][3]; $ramGate = [double]$models[$m][4]
    $src = Join-Path $Root ("hf\" + $repo.Replace("/", "__"))
    $out = Join-Path $Root "models\z2-npu\$m-int4-sym-$tag-ov"
    $argl = @("export", "openvino", "--model", $src, "--task", $task, "--weight-format", "int4", "--sym", "--ratio", "1.0", "--group-size", "$Group", $out)
    $so = Join-Path $logs "export_${m}_$tag.out.txt"; $se = Join-Path $logs "export_${m}_$tag.err.txt"
    $code = "gate"; $attempt = 0; $run = 0.0; $peak = 0; $peakPriv = 0; $minAvail = 9999; $maxCommit = 0; $avail0 = $null
    while ($attempt -lt 30) {
        $attempt++
        if (-not (Wait-ExportGate $m $maxUsed $ramGate)) { $code = "gate"; break }
        if (Test-Path $out) { Remove-Item $out -Recurse -Force }
        $avail0 = Get-AvailGB
        Say $log "$m start (attempt $attempt): optimum-cli $($argl -join ' ') (available RAM $avail0 GB, running-time limit $tmin min)"
        # the form pc\chain.ps1 starts its engines with (one argument string, hidden window); no path here has a space
        $p = Start-Process -FilePath $cli -ArgumentList ($argl -join " ") -RedirectStandardOutput $so -RedirectStandardError $se -PassThru -WindowStyle Hidden
        $null = $p.Handle   # keeps ExitCode readable after the exit (Start-Process -PassThru)
        $run = 0.0; $last = Get-Date; $stopped = ""; $tick = 0
        while (-not $p.WaitForExit(5000)) {
            $now = Get-Date; $run += ($now - $last).TotalSeconds; $last = $now
            if (Test-AnyLock) { Stop-ExportTree $p.Id; $stopped = "lock"; break }
            $tick++
            if ($tick % 6 -eq 0) {
                $ws = 0; $pv = 0   # the tree's peak working sets (each process's own peak so far) and private bytes now
                foreach ($q in (Get-TreePids $p.Id)) {
                    $g = Get-Process -Id $q -ErrorAction SilentlyContinue
                    if ($g) { $ws += $g.PeakWorkingSet64; $pv += $g.PrivateMemorySize64 }
                }
                if ($ws -gt $peak) { $peak = $ws }
                if ($pv -gt $peakPriv) { $peakPriv = $pv }
                $a = Get-AvailGB; if ($a -lt $minAvail) { $minAvail = $a }
                $cu = Get-CommitUsedGB; if ($cu -gt $maxCommit) { $maxCommit = $cu }
                if ($cu -gt 80) { Say $log "$m stopped: $cu GB of commit in use"; Stop-ExportTree $p.Id; $stopped = "commit"; break }
            }
            if ($run -gt $tmin * 60) { Say $log "$m over $tmin running minutes: stopping its tree"; Stop-ExportTree $p.Id; $stopped = "timeout"; break }
        }
        if ($stopped -eq "lock") { Say $log "$m stopped after $([math]::Round($run)) s: a lock was taken; taken again when the gate opens"; $code = "lock"; continue }
        $code = if ($stopped) { $stopped } else { $p.ExitCode }
        break
    }
    $xml = @(Get-ChildItem $out -Filter *.xml -ErrorAction SilentlyContinue)
    $info = Join-Path $logs "export_${m}_$tag.ir.json"
    if ($code -eq 0 -and $xml.Count) {
        & $py -u (Join-Path $PSScriptRoot "ir_info.py") $out --out $info 2>&1 | ForEach-Object { Say $log "  ir_info: $_" }
    } else { $bad += $m }
    Say $log "$m end: exit $code, attempt $attempt, $([math]::Round($run)) s running, peak working set $([math]::Round($peak / 1MB)) MB, private $([math]::Round($peakPriv / 1MB)) MB, lowest available RAM $minAvail GB, highest commit in use $maxCommit GB, $($xml.Count) xml"
    $res += [ordered]@{ model = $m; repo = $repo; source = $src; out = $out; group = $Group; command = "optimum-cli $($argl -join ' ')"
                        "exit" = "$code"; attempts = $attempt; running_s = [math]::Round($run, 1); peak_ws_mb = [math]::Round($peak / 1MB)
                        peak_private_mb = [math]::Round($peakPriv / 1MB)
                        avail_gb_start = $avail0; avail_gb_min = $minAvail; commit_used_gb_max = $maxCommit; stdout = $so; stderr = $se
                        ir_info = $(if (Test-Path $info) { $info } else { $null }); "end" = (Get-Date -Format o) }
    Write-JsonFile $sum @{ group = $Group; venv_exit = $s; fetch_exit = $f; models = $res }
}
Write-JsonFile $sum @{ group = $Group; venv_exit = $s; fetch_exit = $f; models = $res }
if (Test-Path $active) { Remove-Item $active -Force }
Write-Utf8 $done "$(if (-not $bad.Count) { 'OK' } else { "FAIL $($bad -join ',')" }) $(Get-Date -Format o)"
Say $log "export_npu done"
