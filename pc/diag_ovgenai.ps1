<#
Untimed, under yield_run (pc\launch.ps1 -Yield): pc\diag_ovgenai.py for several IR / device pairs, one after the other.
Logs and JSON into runs\diag\; runs\diag\<Tag>.done at the end.

  powershell -NoProfile -ExecutionPolicy Bypass -File pc\diag_ovgenai.ps1 -Tag <tag> -Jobs <name>,<IR folder under the root>,<device>,<cache folder under the root or empty>[,pipeline=vlm][,<KEY=VALUE>...][+<next job>...]
#>
param([Parameter(Mandatory = $true)][string]$Tag, [Parameter(Mandatory = $true)][string]$Jobs)
. "$PSScriptRoot\zlib.ps1"
$ErrorActionPreference = "Continue"
$dir = Join-Path $Root "runs\diag"
New-Item -ItemType Directory -Force $dir | Out-Null
$done = Join-Path $dir "$Tag.done"
if (Test-Path $done) { Remove-Item $done -Force }
$active = Join-Path $Pcup "active\Z2-diag.txt"
Write-Utf8 $active "Z2 OpenVINO GenAI diagnostic ($Tag, no timing, under yield_run) since $(Get-Date -Format o)"
$py = Join-Path $Root ".venv-ovgenai\Scripts\python.exe"
foreach ($j in ($Jobs -split "\+")) {
    $f = $j -split ","
    $name = $f[0]; $ir = Join-Path $Root $f[1]; $dev = $f[2]; $cache = $f[3]
    $log = Join-Path $dir "$name.log"
    Say $log "start: $j"
    $a = @("-I", (Join-Path $PSScriptRoot "diag_ovgenai.py"), "--model-dir", $ir, "--device", $dev, "--out", (Join-Path $dir "$name.json"))
    if ($cache) { $a += @("--cache-dir", (Join-Path $Root $cache)) }
    foreach ($p in ($f | Select-Object -Skip 4)) {
        if ($p -like "pipeline=*") { $a += @("--pipeline", $p.Substring(9)) } else { $a += @("--prop", $p) }
    }
    & $py @a 2>&1 | ForEach-Object { Append-Utf8 $log "$_`r`n" }
    Say $log "end: exit $LASTEXITCODE"
}
if (Test-Path $active) { Remove-Item $active -Force }
Write-Utf8 $done "OK $(Get-Date -Format o)"
