<#
Starts a script detached through WMI (it outlives the SSH session and the Mac), after a parse check on this PC, and
checks 20 s later that a process with its name runs (a script that does not parse dies without a done file, seen on
this PC). Prints STARTED <pid> or FAILED <why>.

  launch.ps1 -Script <path.ps1> -ArgLine "<arguments as one string>" [-Yield]

-Yield wraps it in %USERPROFILE%\pcup\yield_run.ps1 -Lane Z2 (untimed work: suspended while another lane holds
busy.txt).
#>
param([Parameter(Mandatory = $true)][string]$Script, [string]$ArgLine = "", [switch]$Yield)
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$errs = $null
[void][System.Management.Automation.Language.Parser]::ParseFile($Script, [ref]$null, [ref]$errs)
if ($errs -and $errs.Count) { "FAILED parse: $($errs | ForEach-Object { "$($_.Extent.StartLineNumber): $($_.Message)" })"; exit 1 }
# Paths here have no spaces (C:\src\llmzoo): the command line carries no inner quotes through yield_run's -Cmd string.
if ("$Script $ArgLine" -match '"') { "FAILED the script path and -ArgLine must not need quotes"; exit 1 }
$inner = "powershell -NoProfile -ExecutionPolicy Bypass -File $Script $ArgLine"
if ($Yield) {
    $yr = Join-Path ([Environment]::GetFolderPath("UserProfile")) "pcup\yield_run.ps1"
    if (Test-Path $yr) { $inner = "powershell -NoProfile -ExecutionPolicy Bypass -File $yr -Lane Z2 -Cmd `"$inner`"" }
    else { "NOTE no $yr (the shared PC's suspend-on-lock helper): started without it" }
}
$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = $inner }
if ($r.ReturnValue -ne 0) { "FAILED Win32_Process.Create ReturnValue $($r.ReturnValue)"; exit 1 }
Start-Sleep -Seconds 20
$leaf = Split-Path $Script -Leaf
$alive = @(Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" | Where-Object { $_.CommandLine -like "*$leaf*" -and $_.ProcessId -ne $PID })
if ($alive.Count) { "STARTED $($r.ProcessId) ($($alive.Count) process(es) with $leaf)" } else { "FAILED no process with $leaf 20 s after the start (pid $($r.ProcessId))"; exit 1 }
