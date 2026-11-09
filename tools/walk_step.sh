#!/bin/bash
# One step of the README walk, run from the Mac with its command line, output and exit code appended to
# raw/walk/walk.log (the walk's record). Usage: tools/walk_step.sh <step label> <command> [args ...]
set -uo pipefail
K="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$K/raw/walk"
log="$K/raw/walk/walk.log"
label="$1"; shift
{ echo "[$(date '+%F %T %Z')] step $label (Z2_PC_ROOT=${Z2_PC_ROOT:-C:\\src\\llmzoo}, commit $(git -C "$K" rev-parse --short HEAD))"
  printf '$'; printf ' %q' "$@"; echo; } >> "$log"
"$@" 2>&1 | tee -a "$log"
rc=${PIPESTATUS[0]}
echo "[$(date '+%F %T %Z')] step $label exit $rc" >> "$log"
exit "$rc"
