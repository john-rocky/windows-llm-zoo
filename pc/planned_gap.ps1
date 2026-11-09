<#
A gap at a fixed time inside a running timed chain, for another lane's timing that cannot move (2026-11-08: two
sittings of another lane at 21:29 and 21:42; the PC's order: the lock off by 21:08, window.txt "until 21:25", no
retake before that lane has given the lock back). The chain cannot be told to stop, so from -ArmAt this script waits for a point where the chain
runs nothing and starts nothing soon: the 30 s between two runs of a unit (a "run 1 end" or "run 2 end" line under 20 s
old; the per-run gate comes only after that sleep, and its 30 min run on the wall clock) or the chain's own duty gap
(its "window.txt" line). There it suspends the chain's process tree, releases the lock if it is ours, and writes
window.txt until -OpenUntil. It waits for another lane's lock to come and go (or for -GiveUpAt when none came), takes
the lock back, settles 60 s, gates as a duty gap does, and resumes the chain. Its lines go to runs\<sitting>\
planned_gap.log and, while the chain is suspended, to the chain's log ("planned gap: ...").

  launch.ps1 -Script pc\planned_gap.ps1 -ArgLine "-ChainPid <pid> -Sitting <name> -ArmAt <ISO> -ReleaseBy <ISO>
             -OpenUntil <ISO> -GiveUpAt <ISO> -ForLane <name>"
#>
param([int]$ChainPid, [string]$Sitting, [string]$ArmAt, [string]$ReleaseBy, [string]$OpenUntil, [string]$GiveUpAt,
      [string]$ForLane = "another lane")
. "$PSScriptRoot\zlib.ps1"
$ErrorActionPreference = "Continue"
$dir = Join-Path $Root "runs\$Sitting"
$clog = Join-Path $dir "chain.log"
$plog = Join-Path $dir "planned_gap.log"
$arm = [datetime]::Parse($ArmAt); $by = [datetime]::Parse($ReleaseBy); $open = [datetime]::Parse($OpenUntil)
$giveUp = [datetime]::Parse($GiveUpAt)
function P([string]$t, [switch]$Chain) {
    Say $plog $t
    if ($Chain) { try { Say $clog "planned gap: $t" } catch { } }
}
function Last-Line { try { return (Get-Content -LiteralPath $clog -Tail 1 -Encoding UTF8) } catch { return "" } }
function Line-Age([string]$l) {
    if ($l -match '^\[([^\]]+)\]') { try { return ((Get-Date) - [datetime]::Parse($Matches[1])).TotalSeconds } catch { } }
    return 9999
}
P "armed for $ForLane`: chain $ChainPid ($Sitting), from $arm suspend at a free point, lock off by $by, window.txt until $open, give up at $giveUp"
while ((Get-Date) -lt $arm) { Start-Sleep -Seconds 5 }

# 1. a free point
$h = $null; $said = $false; $where = ""
while ($true) {
    if (-not (Get-Process -Id $ChainPid -ErrorAction SilentlyContinue)) { P "the chain $ChainPid is gone: no gap"; exit 0 }
    $l = Last-Line
    $free = ""
    if ($l -match ' run [12] end: ' -and (Line-Age $l) -lt 20) { $free = "between two runs" }
    elseif ($l -match 'window\.txt: Z2 open until (\S+)') {
        try { if (([datetime]::Parse($Matches[1]) - (Get-Date)).TotalSeconds -gt 30) { $free = "in its own duty gap" } } catch { }
    }
    if ($free) {
        $h = Suspend-Tree $ChainPid
        $l2 = Last-Line
        # an engine of the chain would be a child; the console host of a WMI-launched PowerShell (conhost) always is one
        $kids = @(Get-TreePids $ChainPid | Where-Object { $_ -ne $ChainPid } | ForEach-Object { Get-Process -Id $_ -ErrorAction SilentlyContinue } |
                  Where-Object { $_.ProcessName -ne "conhost" })
        if ($l2 -eq $l -and $kids.Count -eq 0) { $where = "$free, after: $l"; break }
        [void](Resume-Tree $h); $h = $null   # the chain moved on between the two reads: try at the next free point
        if ($kids.Count) { P "not free: child process(es) $(($kids | ForEach-Object { "$($_.ProcessName) $($_.Id)" }) -join ', ')" }
        Start-Sleep -Seconds 25   # past this sleep between two runs: the next free point is the next run's end
    }
    if (-not $said -and (Get-Date) -gt $by) { P "no free point yet at $by (a run is going): waiting for its end"; $said = $true }
    Start-Sleep -Milliseconds 500
}
P "chain suspended ($($h.Count) process(es)) $where" -Chain
if (Test-OursBusy) { Release-Busy $plog; P "lock released" -Chain }
$sec = [int]($open - (Get-Date)).TotalSeconds
if ($sec -gt 0) { Open-Window $sec $plog; P "window.txt: Z2 open until $($open.ToString('o'))" -Chain }

# 2. the other lane's lock comes and goes (or none came by -GiveUpAt)
$seen = ""; $why = ""
while ($true) {
    $b = Read-Busy
    if ($b -and -not $b.Text.StartsWith("$Label ")) { if (-not $seen) { $seen = $b.Text; P "lock taken by: $seen" -Chain } }
    elseif ($seen -and -not $b) { $why = "the lock was given back"; break }
    elseif (-not $seen -and (Get-Date) -gt $giveUp) { $why = "no other lock came by $giveUp"; break }
    if ((Get-Date) -gt $open) { Close-Window }   # the window's time is over (11-09)
    Start-Sleep -Seconds 5
}
P "$why`: taking the lock back" -Chain

# 3. back as a duty gap comes back: take, settle 60 s, gate; then resume the chain
while ($true) {
    $t = Take-Busy "sitting $Sitting (after a planned gap for $ForLane)" $plog
    Close-Window
    if ($t -eq "TIMEOUT") { P "could not take the lock back: the chain stays suspended" -Chain; exit 1 }
    Start-Sleep -Seconds 60
    $g = Pass-LaneGate $plog
    if ($g -eq "PASS") { break }
    P "gate $g after the gap: release for 10 min and try again" -Chain
    Release-Busy $plog; Open-Window 600 $plog; Start-Sleep -Seconds 600; Close-Window
}
$n = Resume-Tree $h
P "lock taken back, gate PASS: chain resumed ($n process(es))" -Chain
