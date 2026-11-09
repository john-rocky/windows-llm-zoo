#!/bin/bash
# One timed Z2 sitting on the PC, from the Mac:
#   1. the Z2 lock (busy.txt, waited for on the PC) and the lane's quiet gate (3 x 5 s under 15 % CPU, RTX empty)
#   2. head anchors: pc/anchors.cells through the bench's own executor, records into raw/anchors/ (BENCH_RAW_ROOT);
#      the bench job's own marker variables stay unset (windows/README "To hold the marker past the job")
#   3. pc/chain.ps1 -Mode timed on the plan, detached; this side waits in one long connection (pc/wait_done.ps1)
#   4. the cells whose cold spread is over 5 % timed once more as <plan>-rerun (tools/rerun_plan.py, same lock)
#   5. tail anchors (the chain keeps the lock ours for -HoldAtEndMin), release, pull runs/<plan> into raw/
#
#   tools/sitting.sh <plan name> [--no-anchors] [--bench pc/bench_rerun.cells] [--close] [--resume] [--wait-hours N]
# --bench: after the head anchors, those bench rows by the bench's executor too (records into raw/bench/).
# --close: only step 5, for a sitting cut short (its chain ended by hand, its chain.done says so): the tail anchors
#   while the lock is still ours, release, pull; no rerun (the remaining and over-spread units go to a later sitting).
# --resume: the chain still runs under the lock and this side's wait ended (its -MaxHours) or was stopped: wait for it
#   again, then steps 4 and 5. A wait that ends before the chain's done file releases nothing and says so (11-08: the
#   12 h wait of walk-timed-b would have ended at 06:28 with its slow CPU cells still to run, and the steps after it
#   would have released the lock under the running chain). --wait-hours: the wait's cap (default 20).
# Log: raw/<plan>.sitting.log. Exit 1 when the lock or a step failed (the lock is released on every exit path).
set -uo pipefail
K="$(cd "$(dirname "$0")/.." && pwd)"
BENCH=~/code/edge-llm-bench
export Z2_FORCE=1   # this script runs under its own lock; its one wait for the lock runs on the PC (pc\lock.ps1)
plan="$1"; shift || true
anchors=1; benchcells=""; close=0; resume=0; waith=20
while (( $# )); do
  case "$1" in --no-anchors) anchors=0 ;; --bench) benchcells="$2"; shift ;; --close) close=1 ;; --resume) resume=1 ;;
    --wait-hours) waith="$2"; shift ;; esac
  shift
done
mkdir -p "$K/raw/anchors"
log="$K/raw/$plan.sitting.log"
pcsh="$K/tools/pc.sh"
R="${Z2_PC_ROOT:-C:\\src\\llmzoo}"   # the PC folder (README walk: another empty folder)
RF="${R//\\//}"                       # the same with forward slashes (ssh tar)
say() { echo "[$(date '+%F %T %Z')] $*" | tee -a "$log"; }
release() { say "release: $("$pcsh" lock release timing "${1:-0}" 2>&1 | tail -1)"; }   # $1 = s of a gap Z2 comes back from (window.txt)

anchor() {  # $1 = head | tail
  say "anchors $1 start"
  ( cd "$BENCH" && BENCH_RAW_ROOT="$K/raw/anchors" BENCH_WINDOWS_SSH_HOST=winpc \
    BENCH_WINDOWS_DEVICE_MODEL='Stealth 16 AI+ B3WI (Core Ultra 9 386H / RTX 5080 Laptop)' \
    python3 scripts/windows_ssh_executor.py "$K/pc/anchors.cells" --campaign "z2-$plan-anchor-$1" \
      --litert-label v0.19.0 \
      --model-file litert-lm:litert-community/gemma-4-E2B-it-litert-lm=gemma-4-E2B-it.litertlm:2588147712 \
      --model-file litert-lm:litert-community/gemma-4-E2B-it-litert-lm=gemma-4-E2B-it_intel_PTL.litertlm:2948333568 \
      --model-file llama.cpp:unsloth/gemma-4-E2B-it-GGUF=gemma-4-E2B-it-Q4_K_M.gguf:3106738272 \
      --model-file litert-lm:litert-community/Qwen3-1.7B=Qwen3-1.7B_dynamic_wi4b32_afp32.litertlm:977184032 ) \
    >> "$log" 2>&1
  local rc=$?
  say "anchors $1 exit $rc"
  return $rc
}

bench_rows() {  # the bench rows of $benchcells (the two cells of the bench's column that read out)
  say "bench rows start ($benchcells)"
  ( cd "$BENCH" && BENCH_RAW_ROOT="$K/raw/bench" BENCH_WINDOWS_SSH_HOST=winpc \
    BENCH_WINDOWS_DEVICE_MODEL='Stealth 16 AI+ B3WI (Core Ultra 9 386H / RTX 5080 Laptop)' \
    python3 scripts/windows_ssh_executor.py "$K/$benchcells" --campaign "z2-$plan-bench" \
      --litert-label v0.19.0 \
      --model-file litert-lm:litert-community/Qwen3-0.6B=Qwen3-0.6B_dynamic_wi4b32_afp32.litertlm:343490560 \
      --model-file llama.cpp:unsloth/gemma-4-E4B-it-GGUF=gemma-4-E4B-it-Q4_K_M.gguf:4977171584 ) \
    >> "$log" 2>&1
  local rc=$?
  say "bench rows exit $rc"
  return $rc
}

take() {
  local r
  while true; do
    r=$("$pcsh" lock take "sitting $plan" 2>&1 | tail -1); say "lock: $r"
    [[ "$r" == TAKEN* || "$r" == OURS* || "$r" == STALE* ]] || return 1
    r=$("$pcsh" lock gate 2>&1 | tail -1); say "gate: $r"
    [[ "$r" == PASS* ]] && return 0
    release 600; say "gate did not open: waiting 10 min before taking the lock again (window.txt)"; sleep 600
  done
}

if (( close )); then
  say "sitting $plan close (anchors=$anchors): chain.done $("$pcsh" ps <<< "Get-Content '$R\\runs\\$plan\\chain.done'" 2>&1 | tr -d '\r' | grep -v 'CLIXML\|<Objs' | tail -1)"
  st=$("$pcsh" lock status 2>&1 | head -1); say "lock: $st"
  trap 'release' EXIT
  if (( anchors )); then
    if [[ "$st" == "busy: Z2 "* ]]; then anchor tail || say "tail anchors not clean (records kept; read them)"
    else say "the lock is not ours: tail anchors skipped"; fi
  fi
  release
  trap - EXIT
  "$pcsh" pull "runs/$plan" raw && say "pulled runs\\$plan -> raw/$plan"
  exit 0
fi

if (( resume )); then
  say "sitting $plan resume (anchors=$anchors): its chain runs under the lock; waiting for it again"
  trap 'release' EXIT
else
  say "sitting $plan start (anchors=$anchors)"
  take || { say "no lock"; exit 1; }
  trap 'release' EXIT
  if (( anchors )); then anchor head || say "head anchors not clean (records kept; read them)"; fi
  if [[ -n "$benchcells" ]]; then bench_rows || say "bench rows not clean (records kept; read them)"; fi
  "$pcsh" lock take "sitting $plan units" > /dev/null 2>&1   # rewrites our marker's time before the long part
  # the hold is only a cap for a Mac that went away: the Mac releases the lock itself after the rerun and the tail anchors
  r=$("$pcsh" launch pc\\chain.ps1 "-Plan $R\\pc\\plans\\$plan.json -Mode timed -HoldAtEndMin 180" 2>&1 | tail -1); say "chain: $r"
  [[ "$r" == STARTED* ]] || exit 1
fi
if (( resume )); then
  # the PC replays the whole chain log: keep only the lines after the last chain line this log has (same ISO form)
  last=$(grep -o '^\[20[0-9-]*T[^]]*\]' "$log" | tail -1)
  say "resumed wait: the chain's lines after $last"
  "$pcsh" wait "$R\\runs\\$plan\\chain.done" "$R\\runs\\$plan\\chain.log" "$waith" 2>&1 \
    | awk -v last="$last" 'skip == 0 && NR == 1 { skip = 1 }
        skip == 1 { if (match($0, /^\[20[0-9-]+T[^]]+\]/)) { if (substr($0, 1, RLENGTH) <= last) next; skip = 2 }
                    else if ($0 !~ /^DONE /) next }
        { print; fflush() }' >> "$log"
else
  "$pcsh" wait "$R\\runs\\$plan\\chain.done" "$R\\runs\\$plan\\chain.log" "$waith" >> "$log" 2>&1
fi
cw=$(tail -1 "$log"); say "chain wait: $cw"
if [[ "$cw" != DONE* ]]; then
  trap - EXIT
  say "the wait ended before the chain's done file (the chain holds the lock): nothing released; tools/sitting.sh $plan --resume"
  exit 1
fi
st=$("$pcsh" lock status 2>&1 | head -1); say "lock after the chain: $st"
# PLAN section 3: a cell whose cold spread is over 5 % is timed once more at the end of the same sitting (<plan>-rerun)
# a chain that failed (e.g. the per-run gate's RAM stop) gets no rerun: its rest and its reruns go to a later sitting
if [[ "$cw" == "DONE FAIL"* ]]; then say "the chain failed: no rerun here; the tail anchors and the release follow"; fi
if [[ "$st" == "busy: Z2 "* && "$cw" != "DONE FAIL"* ]]; then
  "$pcsh" pull "runs/$plan" raw && say "pulled runs\\$plan -> raw/$plan (for the rerun list)"
  n=$(python3 "$K/tools/rerun_plan.py" --sitting "$plan" 2>&1 | tee -a "$log" | sed -n 's/^UNITS //p')
  if [[ "${n:-0}" -gt 0 ]]; then
    "$pcsh" push >> "$log" 2>&1
    r=$("$pcsh" launch pc\\chain.ps1 "-Plan $R\\pc\\plans\\$plan-rerun.json -Mode timed -HoldAtEndMin 60" 2>&1 | tail -1); say "rerun chain: $r"
    if [[ "$r" == STARTED* ]]; then
      "$pcsh" wait "$R\\runs\\$plan-rerun\\chain.done" "$R\\runs\\$plan-rerun\\chain.log" 6 >> "$log" 2>&1
      rw=$(tail -1 "$log"); say "rerun wait: $rw"
      if [[ "$rw" != DONE* ]]; then
        trap - EXIT
        say "the rerun wait ended before its done file (the rerun chain holds the lock): nothing released; wait for runs\\$plan-rerun\\chain.done, then tools/sitting.sh $plan --close"
        exit 1
      fi
    fi
    st=$("$pcsh" lock status 2>&1 | head -1); say "lock after the rerun: $st"
  fi
fi
if (( anchors )); then
  if [[ "$st" == "busy: Z2 "* ]]; then anchor tail || say "tail anchors not clean (records kept; read them)"
  else say "the lock is not ours after the chain: tail anchors skipped"; fi
fi
release
trap - EXIT
"$pcsh" pull "runs/$plan" raw && say "pulled runs\\$plan -> raw/$plan"
[[ -f "$K/pc/plans/$plan-rerun.json" ]] && "$pcsh" pull "runs/$plan-rerun" raw && say "pulled runs\\$plan-rerun -> raw/$plan-rerun"
say "sitting $plan end"
