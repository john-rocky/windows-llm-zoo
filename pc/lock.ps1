<#
The Z2 timing lock from the Mac, one SSH call per action (the wait loops run here, not as polls from the Mac).

  lock.ps1 -Action take -What "<text>"      waits (5 s reads) until busy.txt is ours: prints TAKEN / OURS / STALE / TIMEOUT
  lock.ps1 -Action gate                     the lane's quiet gate (zlib Pass-LaneGate): prints PASS / TIMEOUT
  lock.ps1 -Action release [-OpenSec <s>]   removes busy.txt if it is ours: prints RELEASED / NOT-OURS; with -OpenSec,
                                            pcup\window.txt says "Z2 open until <now + s>" (a gap Z2 comes back from)
  lock.ps1 -Action status                   prints the marker, the active\ and yield\ notes
take removes Z2's window.txt once the lock is ours; release without -OpenSec removes it too (the PC is free, no window).
#>
param([Parameter(Mandatory = $true)][ValidateSet("take", "gate", "release", "status")][string]$Action,
      [string]$What = "timing", [int]$MaxHours = 12, [int]$OpenSec = 0)
. "$PSScriptRoot\zlib.ps1"
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$log = Join-Path $Root "logs\lock.log"
New-Item -ItemType Directory -Force (Split-Path $log) | Out-Null
# Z2's own untimed work (a first pass, an export, a setup step) must not sit suspended or run beside a timed sitting
# (2026-11-08: a suspended export kept 31 GB at the RAM collision of 11-07 23:10): take refuses while one runs.
function Get-OwnUntimed {
    @(Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" | Where-Object {
            $c = "$($_.CommandLine)"
            $c -match '\\src\\llmzoo' -and ($c -match '\\pc\\(chain_seq|export_npu|prep_hub|foundry_setup|diag_ovgenai)\.ps1' -or
                $c -match '\\pc\\chain\.ps1 .*-Mode first') } |
        ForEach-Object { "$($_.ProcessId) $("$($_.CommandLine)" -replace '^.*\\pc\\', 'pc\')" })
}
switch ($Action) {
    "take" {
        $own = Get-OwnUntimed
        if ($own.Count) { "OWN-UNTIMED $($own -join '; ') $(Get-Date -Format o)"; break }
        $r = Take-Busy $What $log 60 $MaxHours
        if (Test-OursBusy) { Close-Window }
        "$r $(Get-Date -Format o)"
    }
    "gate" { $r = Pass-LaneGate $log; "$r $(Get-Date -Format o)" }
    "release" {
        if (Test-OursBusy) {
            Release-Busy $log
            if ($OpenSec -gt 0) { Open-Window $OpenSec $log } else { Close-Window }
            "RELEASED $(Get-Date -Format o)"
        } else { "NOT-OURS $(Get-Date -Format o)" }
    }
    "status" {
        $b = Read-Busy
        if ($b) { "busy: $($b.Text) ($([int]$b.AgeMin) min)" } else { "busy: none" }
        Get-ChildItem (Join-Path $Pcup "active\*.txt"), (Join-Path $Pcup "yield\*.txt") -ErrorAction SilentlyContinue |
            ForEach-Object { "$($_.Directory.Name)\$($_.Name): $(([IO.File]::ReadAllText($_.FullName)).Trim())" }
    }
}
