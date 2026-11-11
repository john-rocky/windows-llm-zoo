#!/bin/bash
# Mac-side calls to the PC (ssh winpc; its default shell is PowerShell), one SSH connection per call. Never open one while another lane times:
# `pc.sh status` reads busy.txt first (that read is itself one connection).
#
#   pc.sh status                      busy.txt, the active\ and yield\ notes, free disk, foundrylocald
#   pc.sh ps                          run the PowerShell read from stdin (-EncodedCommand)
#   pc.sh push                        pc/, shelf/, mtools/ -> the PC folder ($Z2_PC_ROOT, default C:\src\llmzoo)
#   pc.sh pull <rel path> <K dest>    <PC folder>\<rel path> -> K/<K dest>/<its last part> (one tar, one connection)
#   pc.sh py <pc\script.py> [args]   that script with the folder's .venv-genai python (-I), in the foreground;
#                                     Z2_VENV=ovexport picks .venv-ovexport (pc\onnx_quant.py needs its onnx package)
#   pc.sh lock take|gate|release|status ["what"] [open s]   pc\lock.ps1 (the waits run on the PC); release with
#                                     [open s] writes pcup\window.txt "Z2 open until <now + s>" (a gap Z2 comes back from)
#   pc.sh launch <script> "<args>" [yield]          pc\launch.ps1 (detached through WMI, parse check first)
#   pc.sh wait <done file> <log file> [max hours]  pc\wait_done.ps1 (one long connection, the log's new lines)
set -euo pipefail
K="$(cd "$(dirname "$0")/.." && pwd)"
R="${Z2_PC_ROOT:-C:\\src\\llmzoo}"   # the PC folder (README walk: another empty folder)
RF="${R//\\//}"                       # the same with forward slashes (ssh tar)

# Never a new connection during another lane's lock: while this lane's chains run, the walk record's last lock line says
# whether the lock is held (their "suspended" / "resumed" lines, up to ~15 s late). Z2_FORCE=1 overrides.
if [[ -z "${Z2_FORCE:-}" && "${1:-}" != "wait" && -f "$K/raw/walk/walk.log" ]]; then
  _last=$(grep -E ' suspended | resumed |waiting before | run [0-9]+ start|stopped: another lane' "$K/raw/walk/walk.log" | tail -n 1)
  if [[ "$_last" == *" suspended "* || "$_last" == *"waiting before "* || "$_last" == *"stopped: another lane"* ]]; then
    echo "REFUSED (another lane's lock, walk record): ${_last##*busy.txt }" >&2
    exit 3
  fi
fi

ps_run() {  # stdin: PowerShell text
  local b64
  b64=$( (printf '%s\n' "\$ProgressPreference='SilentlyContinue'; [Console]::OutputEncoding=[Text.Encoding]::UTF8"; cat) \
    | iconv -f UTF-8 -t UTF-16LE | base64)
  ssh winpc "powershell -NoProfile -ExecutionPolicy Bypass -EncodedCommand $b64"
}

case "${1:-}" in
  status)
    ps_run <<'EOF'
"now $(Get-Date -Format o)"
$p = Join-Path ([Environment]::GetFolderPath('UserProfile')) 'pcup'
if (Test-Path "$p\busy.txt") { "busy: $((Get-Content "$p\busy.txt" -Raw).Trim()) (written $([int]((Get-Date) - (Get-Item "$p\busy.txt").LastWriteTime).TotalMinutes) min ago)" } else { "busy: none" }
Get-ChildItem "$p\active\*.txt", "$p\yield\*.txt" -ErrorAction SilentlyContinue | ForEach-Object { "$($_.Directory.Name)\$($_.Name): $((Get-Content $_.FullName -Raw).Trim())" }
"free C: $([math]::Round((Get-PSDrive C).Free / 1GB, 1)) GB"
Get-Process foundrylocald -ErrorAction SilentlyContinue | ForEach-Object { "foundrylocald pid $($_.Id) since $($_.StartTime.ToString('o'))" }
EOF
    ;;
  ps) ps_run ;;
  py)
    script="$2"; shift 2
    ps_run <<EOF
\$env:ORT_DISABLE_TELEMETRY = '1'
& '$R\\.venv-${Z2_VENV:-genai}\\Scripts\\python.exe' -I '$R\\$script' $* 2>&1 | ForEach-Object { "\$_" }
"exit \$LASTEXITCODE"
EOF
    ;;
  push)
    # mtools/variant_pkg.py = the overlay tool of john-rocky/gemma-4-e4b-on-foundry-local, vendored (docs/files.md)
    COPYFILE_DISABLE=1 tar -cf - -C "$K" pc shelf mtools \
      | ssh winpc "New-Item -ItemType Directory -Force $RF | Out-Null; tar -xf - -C $RF"
    echo "pushed pc/, shelf/, mtools/ (variant_pkg.py sha256 $(shasum -a 256 "$K/mtools/variant_pkg.py" | cut -c1-16))"
    ;;
  pull)
    mkdir -p "$K/$3"
    ssh winpc "tar -cf - -C $RF/$(dirname "$2") $(basename "$2")" | tar -xf - -C "$K/$3"
    ;;
  lock)
    what="${3:-timing}"
    ps_run <<EOF
& '$R\\pc\\lock.ps1' -Action $2 -What '$what' -OpenSec ${4:-0}
EOF
    ;;
  launch)
    y=""; [[ "${4:-}" == "yield" ]] && y="-Yield"
    ps_run <<EOF
& '$R\\pc\\launch.ps1' -Script '$R\\$2' -ArgLine '$3' $y
EOF
    ;;
  wait)
    ps_run <<EOF
& '$R\\pc\\wait_done.ps1' -Done '$2' -Log '$3' -MaxHours ${4:-12}
EOF
    ;;
  *) sed -n 2,13p "$0"; exit 2 ;;
esac
