<#
Foundry Local for Z2 on this PC (Windows PowerShell 5.1). Steps (-Steps, a comma list, default all four):
  status    the CLI version, `status -o json`, `config show -o json`, the catalog (`model list --variants -o json`) and
            which of the variants below were cached before Z2 (logs\foundry_cached_before.json: at the lane close Z2
            removes only the entries it added)
  download  the catalog variants of Gemma 4 E2B and Qwen3 0.6B / 1.7B / 4B on CUDA, WebGPU and CPU, each by the explicit
            variant id the catalog gives now for that name. While another lane holds busy.txt a download is stopped (CLI
            killed, daemon stopped: the daemon is not in yield_run's process tree) and started again afterwards.
            Stops when C: would fall under 100 GB free.
  register  the two E4B packages of mlboydaisuke/gemma-4-E4B-it-Foundry-Local as local models z2-... (the commands of
            the john-rocky/gemma-4-e4b-on-foundry-local README: --task vision-language-chat, CUDA on gpu, CPU on cpu)
  paths     the folder of each package on disk (the one holding genai_config.json), its files with size and sha256
            -> logs\foundry_paths.json
Ends with logs\foundry_setup.done ("OK ..." or "FAIL ..."). Never runs `foundry report` (it opens a browser) or `foundry cache remove`.

  powershell -NoProfile -ExecutionPolicy Bypass -File pc\foundry_setup.ps1 [-Steps status,download,register,paths]
#>
param([string]$Steps = "status,download,register,paths")
. "$PSScriptRoot\zlib.ps1"
$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$logs = Join-Path $Root "logs"
New-Item -ItemType Directory -Force $logs | Out-Null
$log = Join-Path $logs "foundry_setup.log"
$done = Join-Path $logs "foundry_setup.done"   # "OK <time>" or "FAIL <what> <time>" at the end (pc\wait_done.ps1)
if (Test-Path $done) { Remove-Item $done -Force }
$env:Path = "$(Join-Path $Root 'cuda12\dll');$env:Path"   # the daemon exits at start without CUDA 12 on PATH (E1)
$Names = @("gemma-4-e2b-it-cuda-gpu", "gemma-4-e2b-it-generic-gpu", "gemma-4-e2b-it-generic-cpu",
    "qwen3-0.6b-cuda-gpu", "qwen3-0.6b-generic-gpu", "qwen3-0.6b-generic-cpu",
    "qwen3-1.7b-cuda-gpu", "qwen3-1.7b-generic-gpu", "qwen3-1.7b-generic-cpu",
    "qwen3-4b-cuda-gpu", "qwen3-4b-generic-gpu", "qwen3-4b-generic-cpu")
$E4b = Join-Path $Root "models\mlboydaisuke__gemma-4-E4B-it-Foundry-Local"
$Local = @(
    @{ id = "z2-gemma-4-e4b-it-cuda-int4-8k:1"; folder = "$E4b\cuda-int4-8k"; device = "gpu"; ep = "CUDAExecutionProvider" },
    @{ id = "z2-gemma-4-e4b-it-cpu-int4:1"; folder = "$E4b\cpu-int4"; device = "cpu"; ep = "CPUExecutionProvider" })
$fail = @()

function F([string[]]$Parts) {
    Append-Utf8 $log "`r`n--- foundry $($Parts -join ' ')  [$(Get-Date -Format o)]`r`n"
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $o = & foundry @Parts 2>&1 | ForEach-Object { "$_" }
    $code = $LASTEXITCODE
    Append-Utf8 $log (($o -join "`r`n") + "`r`n[exit=$code, $([math]::Round($sw.Elapsed.TotalSeconds, 1)) s]`r`n")
    return $code
}
# A JSON answer: stdout to logs\<name>.json as bytes (cmd redirect), stderr apart; the parsed object or $null
function FJ([string]$Name, [string]$ArgLine) {
    $o = Join-Path $logs "$Name.json"; $e = Join-Path $logs "$Name.stderr.txt"
    & cmd.exe /d /c "foundry $ArgLine -o json 1>$o 2>$e"
    Say $log "foundry $ArgLine -o json -> $Name.json (exit $LASTEXITCODE)"
    try { return (Get-Content $o -Raw -Encoding UTF8 | ConvertFrom-Json) } catch { Say $log "  not JSON: $(Get-Content $o -Raw -ErrorAction SilentlyContinue)"; return $null }
}
function Get-FreeGB { [math]::Round((Get-PSDrive C).Free / 1GB, 1) }
function Get-Catalog {
    $c = FJ "foundry_variants" "model list --variants"
    if ($c -and $c.variants) { return @($c.variants) }
    return @()
}
# the newest version of each name (variantId = <name>:<version>)
function Select-Ids($Variants) {
    $ids = [ordered]@{}
    foreach ($n in $Names) {
        $v = @($Variants | Where-Object { $_.variantName -eq $n } | Sort-Object { [int](($_.variantId -split ":")[-1]) } -Descending)
        $ids[$n] = if ($v.Count) { $v[0] } else { $null }
    }
    return $ids
}

$active = Join-Path $Pcup "active\Z2-foundry.txt"
Write-Utf8 $active "Z2 Foundry Local: $Steps (catalog downloads, no timing; stops a download while another lane holds busy.txt) since $(Get-Date -Format o)"
Say $log "foundry_setup start: steps $Steps, free C: $(Get-FreeGB) GB"
# One Foundry Local service per Windows user, shared by the lanes: stop it at the end only when none ran at the start
$daemonAtStart = @(Get-Process foundrylocald -ErrorAction SilentlyContinue | ForEach-Object { $_.Id })
if ($daemonAtStart.Count) { Say $log "a Foundry daemon was running at the start (pid $($daemonAtStart -join ',')): it is left running at the end" }
$steps_ = $Steps.Split(",") | ForEach-Object { $_.Trim() }
while (Test-OtherBusy) { Start-Sleep -Seconds 30 }   # nothing of this touches the PC while another lane times
$null = F @("--version")
$null = F @("server", "start")

if ($steps_ -contains "status") {
    $null = FJ "foundry_status" "status"
    $null = FJ "foundry_config" "config show"
    $ids = Select-Ids (Get-Catalog)
    $before = [ordered]@{}
    foreach ($n in $ids.Keys) { $v = $ids[$n]; $before[$n] = if ($v) { [ordered]@{ variantId = $v.variantId; cached = $v.cached; fileSizeMb = $v.fileSizeMb; license = $v.license; executionProvider = $v.executionProvider; type = $v.type } } else { $null } }
    $bf = Join-Path $logs "foundry_cached_before.json"
    if (-not (Test-Path $bf)) { Write-JsonFile $bf $before; Say $log "cached before Z2: $(($before.Keys | Where-Object { $before[$_] -and $before[$_].cached }) -join ', ')" }
    else { Say $log "foundry_cached_before.json kept from the first start" }
    foreach ($n in $Names) { if (-not $ids[$n]) { Say $log "not in the catalog now: $n"; $fail += "catalog:$n" } }
}

if ($steps_ -contains "download") {
    $ids = Select-Ids (Get-Catalog)
    foreach ($n in $Names) {
        $v = $ids[$n]
        if (-not $v) { continue }
        if ($v.cached) { Say $log "$($v.variantId) cached"; continue }
        if ((Get-FreeGB) - $v.fileSizeMb / 1024 -lt 100) { Say $log "ERROR: C: would fall under 100 GB free with $($v.variantId) ($(Get-FreeGB) GB free)"; $fail += "disk"; break }
        $ok = $false
        for ($t = 1; $t -le 6 -and -not $ok; $t++) {
            while (Test-OtherBusy) { Start-Sleep -Seconds 30 }
            $dl = Join-Path $logs "download_$($v.variantId -replace ':', '_').txt"
            $sw = [Diagnostics.Stopwatch]::StartNew()
            $p = Start-Process -FilePath "cmd.exe" -ArgumentList "/d /c foundry model download $($v.variantId) 1>>$dl 2>&1" -PassThru -WindowStyle Hidden
            $null = $p.Handle
            $yielded = $false
            while (-not $p.HasExited) {
                if (Test-OtherBusy) { $yielded = $true; & taskkill.exe /PID $p.Id /T /F 2>&1 | Out-Null; break }
                Start-Sleep -Seconds 5
            }
            if ($yielded) {
                Say $log "download $($v.variantId) try $t stopped after $([int]$sw.Elapsed.TotalSeconds) s: another lane took busy.txt ($((Read-Busy).Text))"
                if (-not $daemonAtStart.Count) { $null = F @("server", "stop") }
                while (Test-OtherBusy) { Start-Sleep -Seconds 30 }
                $null = F @("server", "start")
                continue
            }
            $p.WaitForExit()
            Say $log "download $($v.variantId) try $t exit $($p.ExitCode) in $([int]$sw.Elapsed.TotalSeconds) s"
            $ok = ($p.ExitCode -eq 0)
        }
        if (-not $ok) { $fail += "download:$($v.variantId)" }
    }
}

if ($steps_ -contains "register") {
    foreach ($m in $Local) {
        if (-not (Test-Path "$($m.folder)\genai_config.json")) { Say $log "ERROR: $($m.folder) has no genai_config.json (pc\fetch.py first)"; $fail += "register:$($m.id)"; continue }
        $null = F @("model", "unregister", $m.id)
        $c = F @("model", "register", $m.folder, $m.id, "--task", "vision-language-chat", "--display-name", ($m.id -replace ':.*$', ''), "--device", $m.device, "--execution-provider", $m.ep)
        if ($c -ne 0) { $fail += "register:$($m.id)" }
    }
    $null = F @("model", "list", "--search", "e4b", "--variants")
    $null = F @("cache", "ls", "--search", "e4b", "--variants")
}

if ($steps_ -contains "paths") {
    $null = FJ "foundry_cache_ls" "cache ls --variants"
    $ids = Select-Ids (Get-Catalog)
    $cacheRoot = Join-Path $env:USERPROFILE ".foundry\cache\models"
    $configs = @(Get-ChildItem $cacheRoot -Recurse -Filter genai_config.json -ErrorAction SilentlyContinue)
    $paths = [ordered]@{}
    $add = {
        param($Key, $Dir, $Extra)
        # every file of the package, sub-folders included (the multimodal packages keep decoder\, embedding\, ... apart)
        $files = @(Get-ChildItem $Dir -File -Recurse | Sort-Object FullName | ForEach-Object { while (Test-OtherBusy) { Start-Sleep -Seconds 30 }; [ordered]@{ name = $_.FullName.Substring($Dir.TrimEnd('\').Length + 1); size = $_.Length; sha256 = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower() } })
        $row = [ordered]@{ folder = $Dir; files = $files }
        foreach ($k in $Extra.Keys) { $row[$k] = $Extra[$k] }
        $paths[$Key] = $row
    }
    foreach ($n in $Names) {
        $v = $ids[$n]
        if (-not $v) { continue }
        $ver = ($v.variantId -split ":")[-1]
        $hit = @($configs | Where-Object { $_.DirectoryName -match "\\$([regex]::Escape($n))-$ver(\\|$)" })
        if ($hit.Count -ne 1) { Say $log "paths: $($v.variantId): $($hit.Count) folders with genai_config.json under $cacheRoot"; $fail += "path:$($v.variantId)"; continue }
        & $add $v.variantId $hit[0].DirectoryName ([ordered]@{ source = "foundry-catalog"; executionProvider = $v.executionProvider; license = $v.license })
    }
    foreach ($m in $Local) { if (Test-Path "$($m.folder)\genai_config.json") { & $add $m.id $m.folder ([ordered]@{ source = "hub:mlboydaisuke/gemma-4-E4B-it-Foundry-Local"; executionProvider = $m.ep }) } }
    Write-JsonFile (Join-Path $logs "foundry_paths.json") $paths
    Say $log "paths: $($paths.Count) packages -> foundry_paths.json"
}
if (-not $daemonAtStart.Count) { $null = F @("server", "stop") }
if (Test-Path $active) { Remove-Item $active -Force }
Write-Utf8 $done "$(if ($fail.Count) { "FAIL $($fail -join ',')" } else { 'OK' }) $(Get-Date -Format o)"
if ($fail.Count) { Say $log "ERROR: $($fail -join ', ')"; exit 1 }
Say $log "foundry_setup done (free C: $(Get-FreeGB) GB)"
