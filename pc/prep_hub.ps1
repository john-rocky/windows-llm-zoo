<#
Untimed preparation, one launch under yield_run (pc\launch.ps1 -Yield): the venvs (pc\setup.ps1), then the Hub files of
shelf\hub_manifest.json (pc\fetch.py, sha256-checked). Writes active\Z2-prep.txt while it runs (the presence note of the
shared-PC rules) and logs\prep_hub.done ("OK ..." or "FAIL ...") at the end.

  powershell -NoProfile -ExecutionPolicy Bypass -File pc\prep_hub.ps1
#>
. "$PSScriptRoot\zlib.ps1"
$ErrorActionPreference = "Continue"
$logs = Join-Path $Root "logs"
New-Item -ItemType Directory -Force $logs | Out-Null
$log = Join-Path $logs "prep_hub.log"
$done = Join-Path $logs "prep_hub.done"
if (Test-Path $done) { Remove-Item $done -Force }
$active = Join-Path $Pcup "active\Z2-prep.txt"   # its own note: a first pass may run beside it
Write-Utf8 $active "Z2 venvs + Hub downloads into $Root (no timing, under yield_run) since $(Get-Date -Format o)"
Say $log "prep_hub start"
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "setup.ps1")
$s = $LASTEXITCODE
Say $log "setup exit $s"
$py = Join-Path $Root ".venv-genai\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = Join-Path ([Environment]::GetFolderPath("LocalApplicationData")) "Programs\Python\Python312\python.exe" }
$flog = Join-Path $logs "fetch.log"
& $py -u (Join-Path $PSScriptRoot "fetch.py") --manifest (Join-Path $Root "shelf\hub_manifest.json") --dest (Join-Path $Root "models") 2>&1 |
    ForEach-Object { Append-Utf8 $flog "$_`r`n" }
$f = $LASTEXITCODE
Say $log "fetch exit $f"
if (Test-Path $active) { Remove-Item $active -Force }
Write-Utf8 $done "$(if ($s -eq 0 -and $f -eq 0) { 'OK' } else { "FAIL setup $s fetch $f" }) $(Get-Date -Format o)"
Say $log "prep_hub done"
