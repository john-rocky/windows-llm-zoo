<#
Runs chain.ps1 for several plans one after the other (first mode: untimed passes and probes). Windows PowerShell 5.1.
Start it detached (pc\launch.ps1). Each plan keeps its own runs\<sitting>\ dir, chain.log and chain.done; this script
writes runs\chain_seq.done when the last one ends.

  powershell -NoProfile -ExecutionPolicy Bypass -File chain_seq.ps1 -Plans <name>,<name> [-Mode first] [-AfterSitting <name>]

-AfterSitting: first wait (up to 6 h) for runs\<name>\chain.done, the end of a chain that is still running.
#>
param([Parameter(Mandatory = $true)][string]$Plans, [ValidateSet("first")][string]$Mode = "first", [string]$AfterSitting = "")
. "$PSScriptRoot\zlib.ps1"
$done = Join-Path $Root "runs\chain_seq.done"
if (Test-Path $done) { Remove-Item $done -Force }
if ($AfterSitting) {
    $after = Join-Path $Root "runs\$AfterSitting\chain.done"
    $until = (Get-Date).AddHours(6)
    while (-not (Test-Path $after) -and (Get-Date) -lt $until) { Start-Sleep -Seconds 15 }
    if (-not (Test-Path $after)) { Write-Utf8 $done "FAIL no $after in 6 h $(Get-Date -Format o)"; exit 1 }
}
$out = @()
foreach ($n in $Plans.Split(",")) {
    $n = $n.Trim()
    if (-not $n) { continue }
    $plan = Join-Path $Root "pc\plans\$n.json"
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "chain.ps1") -Plan $plan -Mode $Mode
    $d = Join-Path $Root "runs\$n\chain.done"
    $out += "$n=$(if (Test-Path $d) { (Get-Content $d -Raw).Trim() } else { 'no chain.done' })"
}
Write-Utf8 $done "$($out -join '; ') $(Get-Date -Format o)"
