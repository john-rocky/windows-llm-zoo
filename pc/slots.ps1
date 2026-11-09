<#
Fixed slots for other lanes' timing inside a running timed chain (2026-11-08: the order agreed on the PC for that
evening was "release the lock at a set time, no pcup\window.txt, the other lane takes it at its first poll; take it
back only after that lane gave it back, or when no lock came by a set time").
-SlotsFile: a JSON list of { "who", "release_at", "give_up_at", "stay_off_after" (optional), "no_retake_before"
(optional) }, in time order. -AlreadySuspended: the chain was suspended by a planner of this kind that was then
stopped (the lock is held to the first release_at); the first slot starts at its release and the chain is resumed by
pid.
-EstFile: a JSON object, cell -> { "run": s, "next_run1": s }: the seconds from one run end of that unit to its next
run end, and those of the next unit's first run (written on the Mac from this sitting's log and the first passes).
For each slot:
 1. From release_at - 15 min, at each point between two runs of a unit (a "run 1 end" or "run 2 end" line of the chain
    under 20 s old; the chain sleeps 30 s there) it estimates the chain's next such point (after a run 1: this unit's
    last stretch or its estimate, whichever is longer; after a run 2: that plus the next unit's first run) and
    suspends the chain's process tree when that point would come later than 45 s before release_at. When the chain is
    in its own duty gap instead (its "window.txt" line), it suspends it in that sleep, removes window.txt and takes
    the lock to hold it to release_at.
 2. At release_at it releases the lock, without window.txt.
 3. It waits for another lane's lock until give_up_at, and when one came, until that lane has given it back: the lock
    free for -FreeSec in a row (60 s; from 20:37 on 11-08, the first slot took the lock back at the first 5 s read
    that found it free), and not before no_retake_before when one is set (another lane takes it after this one).
 4. Given back after stay_off_after (and another slot follows): the lock stays off for the next slot's lane and the
    chain stays suspended. Otherwise it takes the lock, settles 60 s, gates as a duty gap does, and resumes the chain.
Lines go to runs\<sitting>\slots.log and, while the chain is suspended, to the chain's log ("slot: ...").

  launch.ps1 -Script pc\slots.ps1 -ArgLine "-ChainPid <pid> -Sitting <name> -SlotsFile <path> -EstFile <path> [-FreeSec <s>]"
#>
param([int]$ChainPid, [string]$Sitting, [string]$SlotsFile, [string]$EstFile, [int]$FreeSec = 60,
      [switch]$AlreadySuspended)
. "$PSScriptRoot\zlib.ps1"
$ErrorActionPreference = "Continue"
$dir = Join-Path $Root "runs\$Sitting"
$clog = Join-Path $dir "chain.log"
$slog = Join-Path $dir "slots.log"
# PowerShell 5.1 writes a JSON list as one object: assign first, then make it an array
$slots = Get-Content -LiteralPath $SlotsFile -Raw -Encoding UTF8 | ConvertFrom-Json
$slots = @($slots)
$est = Get-Content -LiteralPath $EstFile -Raw -Encoding UTF8 | ConvertFrom-Json
function P([string]$t, [switch]$Chain) {
    Say $slog $t
    if ($Chain) { try { Say $clog "slot: $t" } catch { } }
}
function Last-Line { try { return (Get-Content -LiteralPath $clog -Tail 1 -Encoding UTF8) } catch { return "" } }
function Line-Time([string]$l) {
    if ($l -match '^\[([^\]]+)\]') { try { return [datetime]::Parse($Matches[1]) } catch { } }
    return $null
}
# the seconds from the run end before line $l to $l, from the chain log's last lines
function Stretch-Before([string]$l) {
    $t = Line-Time $l
    $prev = $null
    foreach ($x in @(Get-Content -LiteralPath $clog -Tail 60 -Encoding UTF8)) {
        if ($x -eq $l) { break }
        if ($x -match '^\[[^\]]+\] \S+ run [123] end: ') { $prev = Line-Time $x }
    }
    if ($t -and $prev) { return ($t - $prev).TotalSeconds }
    return 0
}
function Est([string]$cell, [string]$key) {
    $e = $est.PSObject.Properties[$cell]
    if ($e -and $null -ne $e.Value.$key) { return [double]$e.Value.$key }
    return 300   # a cell without an estimate: 5 min
}
function Take-Back([string]$What) {
    while ($true) {
        $t = Take-Busy "sitting $Sitting (after $What)" $slog
        Close-Window
        if ($t -eq "TIMEOUT") { P "could not take the lock back: the chain stays suspended" -Chain; exit 1 }
        Start-Sleep -Seconds 60
        $g = Pass-LaneGate $slog
        if ($g -eq "PASS") { return }
        P "gate $g after $What`: release for 10 min and try again" -Chain
        Release-Busy $slog; Open-Window 600 $slog; Start-Sleep -Seconds 600; Close-Window
    }
}

$h = $null       # the suspended tree's handles (kept while the lock stays off between two slots)
$off = $false    # the chain is suspended already: after a slot whose lock stayed off, or by the planner this one replaced
# resume the tree: by its handles, or (suspended by a planner that was stopped) opened again by pid
function Resume-Chain {
    if ($script:h) { $n = Resume-Tree $script:h; $script:h = $null; return $n }
    $n = 0
    foreach ($p in (Get-TreePids $ChainPid)) {
        $x = [Z2.Native]::OpenProcess(0x0800, $false, $p)
        if ($x -eq [IntPtr]::Zero) { continue }
        if ([Z2.Native]::NtResumeProcess($x) -eq 0) { $n++ }
        [void][Z2.Native]::CloseHandle($x)
    }
    return $n
}
if ($AlreadySuspended) {
    $off = $true
    P "the chain is suspended already (by the planner this one replaces): the first slot starts at its release" -Chain
}
for ($i = 0; $i -lt $slots.Count; $i++) {
    $s = $slots[$i]
    $rel = [datetime]::Parse($s.release_at); $giveUp = [datetime]::Parse($s.give_up_at)
    $stayOff = $null
    if ($s.stay_off_after -and $i -lt $slots.Count - 1) { $stayOff = [datetime]::Parse($s.stay_off_after) }
    $from = $rel.AddMinutes(-15)
    P "slot for $($s.who): release at $($rel.ToString('o')) without window.txt, give up at $($giveUp.ToString('o'))$(if ($stayOff) { ", the lock stays off when given back after $($stayOff.ToString('o'))" }); chain $ChainPid ($Sitting)"
    if (-not $off) {
        # 1. a point between two runs that leaves no run going at release_at
        while ((Get-Date) -lt $from) { Start-Sleep -Seconds 5 }
        $where = ""; $looked = ""; $late = $false
        while (-not $where) {
            if (-not (Get-Process -Id $ChainPid -ErrorAction SilentlyContinue)) { P "the chain $ChainPid is gone: no more slots"; exit 0 }
            $l = Last-Line
            $now = Get-Date
            $free = ""
            if ($l -ne $looked -and $l -match '^\[[^\]]+\] (\S+) run ([12]) end: ') {
                $cell = $Matches[1]; $k = [int]$Matches[2]
                $lt = Line-Time $l
                if ($lt -and ($now - $lt).TotalSeconds -lt 20) {
                    $looked = $l
                    $next = [math]::Max((Stretch-Before $l), (Est $cell "run"))
                    if ($k -eq 2) { $next += (Est $cell "next_run1") }
                    if ($now.AddSeconds($next + 45) -ge $rel) { $free = "between two runs (the next run end in about $([int]$next) s)" }
                    else { P "not yet: after $cell run $k, the next run end in about $([int]$next) s" }
                }
            } elseif ($l -match '^\[[^\]]+\] window\.txt: Z2 open until (\S+)') {
                try { if (([datetime]::Parse($Matches[1]) - $now).TotalSeconds -gt 30) { $free = "in its own duty gap" } } catch { }
            }
            if (-not $late -and $now -gt $rel) { P "no point between two runs by $($rel.ToString('o')) (a run is going): suspending at its end"; $late = $true }
            if ($free) {
                $h2 = Suspend-Tree $ChainPid
                $l2 = Last-Line
                # an engine of the chain would be a child; the console host of a WMI-launched PowerShell (conhost) always is one
                $kids = @(Get-TreePids $ChainPid | Where-Object { $_ -ne $ChainPid } | ForEach-Object { Get-Process -Id $_ -ErrorAction SilentlyContinue } |
                          Where-Object { $_.ProcessName -ne "conhost" })
                if ($l2 -eq $l -and $kids.Count -eq 0) { $h = $h2; $where = "$free, after: $l"; break }
                [void](Resume-Tree $h2)
                $kn = if ($kids.Count) { "child process(es) $(($kids | ForEach-Object { "$($_.ProcessName) $($_.Id)" }) -join ', ')" } else { "the chain moved on" }
                P "not free after all: $kn"
                Start-Sleep -Seconds 25
            }
            Start-Sleep -Milliseconds 500
        }
        P "chain suspended ($($h.Count) process(es)) $where" -Chain
        if ($where -like "in its own duty gap*") {
            Close-Window
            $t = Take-Busy "sitting $Sitting (held for a slot at $($rel.ToString('HH:mm:ss')))" $slog
            P "window.txt removed; lock $t, held to $($rel.ToString('o'))" -Chain
        }
        # 2. release at its time, without window.txt
        while ((Get-Date) -lt $rel) { Start-Sleep -Milliseconds 500 }
        Close-Window
        if (Test-OursBusy) { Release-Busy $slog; P "lock released for $($s.who), no window.txt" -Chain }
    } else {
        # the lock is ours only when the planner this one replaced held it to release_at
        while ((Get-Date) -lt $rel) { Start-Sleep -Milliseconds 500 }
        Close-Window
        if (Test-OursBusy) { Release-Busy $slog; P "lock released for $($s.who), no window.txt" -Chain }
    }
    # 3. the other lane's lock comes and goes (or none came by give_up_at)
    # given back = free for -FreeSec in a row: a lane can drop its lock for a moment between its own runs or sittings;
    # and not before no_retake_before (11-08: another lane's untimed walk takes the lock after this slot's lane)
    $noBefore = $null
    if ($s.no_retake_before) { $noBefore = [datetime]::Parse($s.no_retake_before); P "no retake before $($noBefore.ToString('o')) unless no lock came by give_up_at" }
    $seen = ""; $why = ""; $freeSince = $null
    while ($true) {
        $b = Read-Busy
        if ($b -and -not $b.Text.StartsWith("$Label ")) {
            if ($freeSince) { P "free for $([int]((Get-Date) - $freeSince).TotalSeconds) s, then lock taken by: $($b.Text)" -Chain; $freeSince = $null }
            if (-not $seen) { $seen = $b.Text; P "lock taken by: $seen" -Chain }
        }
        elseif ($seen -and -not $b) {
            if (-not $freeSince) { $freeSince = Get-Date }
            elseif (((Get-Date) - $freeSince).TotalSeconds -ge $FreeSec -and (-not $noBefore -or (Get-Date) -ge $noBefore)) {
                $why = "the lock was given back (free for $([int]((Get-Date) - $freeSince).TotalSeconds) s)"; break
            }
        }
        elseif (-not $seen -and (Get-Date) -gt $giveUp) { $why = "no other lock came by $($giveUp.ToString('o'))"; break }
        Start-Sleep -Seconds 5
    }
    # 4. the lock stays off for the next slot, or comes back
    if ($stayOff -and $seen -and (Get-Date) -gt $stayOff) {
        P "$why after $($stayOff.ToString('o')): the lock stays off for the next slot, the chain stays suspended" -Chain
        $off = $true
        continue
    }
    P "$why`: taking the lock back" -Chain
    Take-Back "the slot for $($s.who)"
    $n = Resume-Chain; $off = $false
    P "lock taken back, gate PASS: chain resumed ($n process(es))" -Chain
}
P "slots done"
