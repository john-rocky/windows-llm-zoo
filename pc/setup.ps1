<#
The Z2 environments on the PC, from pc\req\*.txt (Windows PowerShell 5.1; uv and Python 3.12 on the machine):
  .venv-genai       ONNX Runtime GenAI 0.19.0 CPU build + the OpenVINO and WebGPU EP plugins
  .venv-genai-cuda  ONNX Runtime GenAI 0.19.0 CUDA + the CUDA 13 runtime wheels
  .venv-ovgenai     OpenVINO GenAI 2026.4.1
  cuda12\dll        the CUDA 12 runtime and cuDNN 9 DLLs Foundry Local's CUDA EP reads from PATH
Writes logs\setup.log and logs\setup_versions.txt; the last line of the log is "setup done" or "ERROR: <what>".

  powershell -NoProfile -ExecutionPolicy Bypass -File pc\setup.ps1
#>
. "$PSScriptRoot\zlib.ps1"
$ErrorActionPreference = "Continue"
$log = Join-Path $Root "logs\setup.log"
New-Item -ItemType Directory -Force (Split-Path $log) | Out-Null
$uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
if (-not $uv) { $uv = "$env:LOCALAPPDATA\Microsoft\WinGet\Links\uv.exe" }
if (-not (Test-Path $uv)) { Say $log "ERROR: uv not found"; exit 1 }
$env:UV_LINK_MODE = "copy"
Say $log "setup start (uv $uv)"
$fail = @()
foreach ($v in @("genai", "genai-cuda", "ovgenai")) {
    $dir = Join-Path $Root ".venv-$v"
    $req = Join-Path $Root "pc\req\$v.txt"
    if (-not (Test-Path "$dir\Scripts\python.exe")) {
        & $uv venv $dir --python 3.12 2>&1 | ForEach-Object { Say $log "  $_" }
    }
    & $uv pip install --python "$dir\Scripts\python.exe" -r $req 2>&1 | ForEach-Object { Say $log "  $_" }
    if ($LASTEXITCODE -ne 0) { $fail += $v; Say $log "venv ${v}: uv pip install exit $LASTEXITCODE" } else { Say $log "venv $v ready" }
}
# CUDA 12 for Foundry Local: the wheels' DLLs in one plain folder
$c12 = Join-Path $Root "cuda12"
& $uv pip install --python (Join-Path $Root ".venv-genai\Scripts\python.exe") --target "$c12\pkgs" --no-deps -r (Join-Path $Root "pc\req\cuda12.txt") 2>&1 | ForEach-Object { Say $log "  $_" }
if ($LASTEXITCODE -ne 0) { $fail += "cuda12" }
New-Item -ItemType Directory -Force "$c12\dll" | Out-Null
Get-ChildItem "$c12\pkgs" -Recurse -Filter *.dll -ErrorAction SilentlyContinue | ForEach-Object { Copy-Item $_.FullName "$c12\dll\" -Force }
Say $log "cuda12\dll: $(@(Get-ChildItem "$c12\dll" -Filter *.dll).Count) DLLs"
# versions, read back from each venv (uv can panic on low memory and the script goes on, seen on this PC)
$vf = Join-Path $Root "logs\setup_versions.txt"
Write-Utf8 $vf ""
foreach ($v in @("genai", "genai-cuda", "ovgenai")) {
    $py = Join-Path $Root ".venv-$v\Scripts\python.exe"
    Append-Utf8 $vf "== .venv-$v`r`n"
    $o = & $py -c "import importlib.metadata as m, sys; print(sys.version.split()[0]); [print(d.metadata['Name'], d.version) for d in sorted(m.distributions(), key=lambda d: d.metadata['Name'].lower())]" 2>&1
    Append-Utf8 $vf (($o -join "`r`n") + "`r`n")
}
if ($fail.Count) { Say $log "ERROR: $($fail -join ', ')"; exit 1 }
Say $log "setup done"
