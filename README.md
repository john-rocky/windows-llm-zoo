# windows-llm-zoo

The LLM cells of one Windows laptop, model × runtime × device (Intel NPU, Intel GPU, RTX, CPU): the harness that
runs them, the record of every run, and one JSON per cell with decode and prefill tokens/s, time to first token,
peak memory and the output check (`results/`).

- Machine: Stealth 16 AI+ B3WI (Windows reports this model name), Intel(R) Core(TM) Ultra 9 386H, Intel(R) Graphics,
  Intel(R) NPU, NVIDIA GeForce RTX 5080 Laptop GPU, 31.5 GB of RAM (as Windows reports it), Windows 11 Home
  10.0.26200. Every record carries the OS build and the GPU and NPU driver versions it ran on
  (`raw/<sitting>/env.*.json`, `osBuild` per run; a sitting is one measuring session on the PC, under one name).
- Models: Qwen3 0.6B / 1.7B / 4B, Gemma 4 E2B / E4B (the five models of the
  [edge-llm-bench](https://github.com/john-rocky/edge-llm-bench) Windows column).
- Runtimes: LiteRT-LM v0.19.0 and llama.cpp b11721 (rows of edge-llm-bench, collected with their record paths),
  ONNX Runtime GenAI 0.19.0, Foundry Local 0.13.0 and OpenVINO GenAI 2026.4.1 (measured here).
- Workload of every cell: edge-llm-bench's `short-chat` prompt as one user turn in the package's chat template,
  greedy, at most 128 new tokens; the headline is the cold generation (first of a fresh engine process). How each
  runtime's numbers are cut and counted: [`PLAN.md`](PLAN.md).
- Four of the five NPU-form IRs exported here (an IR is OpenVINO's model format; int4 symmetric weights, ratio 1.0;
  steps 3 and 7 below) are on the Hugging Face Hub:
  [`mlboydaisuke/Qwen3-0.6B-int4-sym-g128-ov`](https://huggingface.co/mlboydaisuke/Qwen3-0.6B-int4-sym-g128-ov),
  [`mlboydaisuke/Qwen3-1.7B-int4-sym-g128-ov`](https://huggingface.co/mlboydaisuke/Qwen3-1.7B-int4-sym-g128-ov),
  [`mlboydaisuke/Qwen3-4B-int4-sym-g128-ov`](https://huggingface.co/mlboydaisuke/Qwen3-4B-int4-sym-g128-ov),
  [`mlboydaisuke/gemma-4-E4B-it-int4-sym-cw-ov`](https://huggingface.co/mlboydaisuke/gemma-4-E4B-it-int4-sym-cw-ov).
  Each card gives the export command and versions and this laptop's NPU numbers; every file on the Hub was checked
  against the export's record (size and sha256, `raw/setup-walk/logs/export_*.ir.json`).

A table that puts the runtimes side by side is not committed here, as in edge-llm-bench: `tools/table.py` writes it
from `results/` on your disk (`RESULTS_LLM_WINDOWS.md`, step 9 below). TensorRT-RTX and TensorRT-Edge-LLM are not
run here.

## Files

| path | what |
|---|---|
| `RESULTS_LLM_WINDOWS.md` | not committed: `tools/table.py` writes the table from `results/` (step 9) |
| `results/<model>/<runtime>_<device>_<backend>.json` | one JSON per cell: the number, every sitting and run, errors in full (`peak_working_set_mb` is in MiB: bytes / 2^20) |
| `raw/<sitting>/` | the PC's run files of each sitting: the runner's JSON, the meta file written by the chain (`pc/chain.ps1`, the PC-side script that runs a plan), stdout / stderr, `env.*.json` |
| `raw/anchors/`, `raw/bench/` | edge-llm-bench records taken by its own executor in this repo's sittings |
| `raw/setup/` | the PC's setup logs: venv versions, the Hub fetch report, Foundry Local's catalog and package file lists |
| `raw/setup-walk/logs/` | the same for the walk below, and the NPU exports: each command and log, each IR's files with sha256 (`export_*.ir.json`) |
| `raw/diag/` | hand diagnostics of OpenVINO GenAI, 2026-11-07 and 08: NPU runs and one CPU run (`pc/diag_ovgenai.ps1`) |
| `raw/z2-e2e-1/`, `raw/z2-first-a/` | rehearsals of 2026-11-07, begun before the walk (15:32 and 15:48; `z2-first-a` was still waiting for the lock at 18:00), in another folder of the PC (`C:\src\llmzoo`) (their plans: `pc/plans/z2-e2e-1.json`, `z2-first-a.json`; the other `z2-*.json` plans of that day have no records here) |
| `shelf/export_manifest.json`, `shelf/ov_ir_quant.json` | the export's pinned checkpoints; the quantization (rt_info) of the published OpenVINO IRs |
| `pc/` | everything that runs on the PC (Windows PowerShell 5.1 and Python) |
| `pc/plans/` | the plans as run (`tools/make_plan.py`, `tools/probe_plan.py`, `tools/timed_plan.py`, `tools/rerun_plan.py`) |
| `mtools/variant_pkg.py` | the overlay tool of `john-rocky/gemma-4-e4b-on-foundry-local` (its `variant_pkg.py` at a5ca414, copied unchanged, sha256 `1ca0f334...`) |
| `tools/` | the Mac side: plans, the sitting driver, result and table builders, the bench collector, `scrub.py` |
| `shelf/hub_manifest.json` | every Hub file a cell loads: repo, pinned revision, size, sha256 or git blob sha1 |
| `PLAN.md` | the method, written before measuring |

## Walk from an empty folder

Needed on the PC: Windows 11, Python 3.12 (`%LOCALAPPDATA%\Programs\Python\Python312`), [uv](https://docs.astral.sh/uv/)
on PATH, Foundry Local 0.13.0 (winget), OpenSSH server, the NVIDIA, Intel GPU and Intel NPU drivers, and free disk
for what the steps write: 95 GB (the Hub files 48.6 GB, the export's checkpoints 29.7 GB, the five exported IRs
16.6 GB) plus the four venvs (three in step 2, the export's in step 3) and the CUDA 12 folder, and for the 12 Foundry Local catalog variants that are not in Foundry's cache yet (33 GB
for all 12, as Foundry Local lists their sizes). The folder must have no spaces in its path. On the Mac: `ssh winpc` reaches the PC (its default shell is
PowerShell), python3, and an edge-llm-bench checkout at `~/code/edge-llm-bench` (its text check and executor are used
as they are). Every Mac-side command below takes the PC folder from `Z2_PC_ROOT` (default `C:\src\llmzoo`).

Shared-PC conventions the scripts follow (`pc/zlib.ps1`): `%USERPROFILE%\pcup\busy.txt` is the timing lock (taken
with CreateNew, one owner), `%USERPROFILE%\pcup\active\<name>.txt` says what an untimed job is doing; both folders
are created when missing. A first pass stops its GPU engine while another owner holds the lock and suspends its NPU
and CPU engines under a timing lock; a timed sitting holds the lock, gates on a quiet PC before the first run and
before each run, and while another job waits (a note in `active\` or `yield\`, whatever its age) gives the lock up
for 16.5 minutes before a run once it has held the lock 30 minutes or that run would end past those 30 minutes (a job
that takes the lock after 15 free minutes does not race it). A run right after the lock was taken starts whatever its
length; a run's expected length is the longest elapsed of that cell's runs the chain has seen (for a `-rerun` sitting,
those of the sitting it reruns too), and the lock's text says until when the current run is expected to run
(`run until about HH:mm`, or its time limit). The sitting takes the lock back once the other job's lock has been gone
60 s (a plan's `retake_free_sec` sets more, for a window that one job hands to another which comes after the first
one's return; a `-rerun` plan takes its sitting's), then settles 60 s and gates again. While the lock is off for such a
gap, `%USERPROFILE%\pcup\window.txt` says `Z2 open until <time>` (`Z2` is this repo's name in the shared PC's lock
files; removed when its time ends), so that a
job which pauses its work starts a step over 8 GB only when it fits in the gap. A run whose available RAM stays under
its need for 10 minutes stops the sitting and writes the three biggest holders into the chain's log: waiting longer
under the lock frees nothing when the holder is another job's paused process. The timed sitting does not start
while this repo's own untimed work (a first pass, an export, a setup step) still runs on the PC. Foundry Local is one
service per Windows user: a run waits for a daemon it did not start instead of stopping it.

```bash
export Z2_PC_ROOT='C:\src\llmzoo-walk'
W='C:\src\llmzoo-walk'
# 1. this repo's tree into the empty folder (a clone works the same)
ssh winpc "New-Item -ItemType Directory C:/src/llmzoo-walk | Out-Null"
git archive HEAD | ssh winpc "tar -xf - -C C:/src/llmzoo-walk"
# 2. on the PC: the three venvs (pc\req\*.txt) and the CUDA 12 folder, then every Hub file of the manifest,
#    checked against its sha256 (logs\prep_hub.done = OK); about 49 GB
tools/pc.sh launch 'pc\prep_hub.ps1' '' yield
tools/pc.sh wait "$W\logs\prep_hub.done" "$W\logs\fetch.log" 4
# 3. on the PC, beside steps 4 to 6: the NPU form (int4, --sym, --ratio 1.0, --group-size 128) of four models: the export
#    venv (pc\req\ovexport.txt), 30 GB of pinned checkpoints (shelf\export_manifest.json), one optimum-cli export each
#    (logs\export_npu_g128.done = OK). Gemma 4 E4B holds 32 GB of commit: it waits for at most 30 GB in use and 14 GB of
#    free RAM. Step 7 exports Gemma 4 E4B once more with channel-wise weights (its group-128 IR's NPU run ended with
#    0xC0000005 before the first answer here)
tools/pc.sh push
tools/pc.sh launch 'pc\export_npu.ps1' ''
# 4. on the PC: Foundry Local's catalog variants (a variant already in Foundry's cache is not downloaded again),
#    the two Gemma 4 E4B local models, and every package file with its sha256 (logs\foundry_setup.done = OK)
tools/pc.sh launch 'pc\foundry_setup.ps1' ''
tools/pc.sh wait "$W\logs\foundry_setup.done" "$W\logs\foundry_setup.log" 2
# 5. the PC's logs back (account names replaced with USER), then the four WebGPU overlay packages (a Foundry Local
#    package made again with a new genai_config.json and hard links to its weights: pc/overlays.py)
tools/pc.sh pull logs raw/setup-walk && python3 tools/scrub.py --names <PC account>,<Mac account> raw/setup-walk
python3 tools/make_plan.py --sitting overlays --set overlays --setup-dir raw/setup-walk/logs && tools/pc.sh push
tools/pc.sh py 'pc\overlays.py' --plan "$W\pc\plans\overlays.json"
# 6. a first pass: one untimed run per cell. The five OpenVINO GenAI NPU cells on the published IRs run in their own chain
#    beside it, as their compile can take all of the 30 running minutes the plan gives an NPU cell (any other cell 15;
#    tools/make_plan.py)
python3 tools/make_plan.py --sitting walk-first --set all --except openvino-genai_npu_npu --runs 1 --setup-dir raw/setup-walk/logs
python3 tools/make_plan.py --sitting walk-npu --set ovgenai --only openvino-genai_npu_npu --runs 1 --setup-dir raw/setup-walk/logs
tools/pc.sh push
tools/pc.sh launch 'pc\chain.ps1' "-Plan $W\pc\plans\walk-first.json -Mode first"
tools/pc.sh launch 'pc\chain.ps1' "-Plan $W\pc\plans\walk-npu.json -Mode first"
tools/pc.sh wait "$W\runs\walk-first\chain.done,$W\runs\walk-npu\chain.done" "$W\runs\walk-first\chain.log,$W\runs\walk-npu\chain.log" 6
# 7. once step 3's venv is in place (its first minutes): the ONNX packages' quantization read from their graphs and
#    the logs back again; after step 3's done file: Gemma 4 E4B's channel-wise export, then the probes, one run each:
#    three NPU fixes of ORT GenAI's OpenVINO execution provider (EP), the exported IRs under OpenVINO GenAI, the three
#    fixes of Foundry's Gemma 4 E2B WebGPU variant (pc/plans/walk-foundry-fix1..3.json: its load fails with "Running a
#    model with multiple providers is not supported. Encountered WebGPU and CUDA"), and the two Gemma 4 E2B CPU cells
#    on the catalog's generic-cpu:3 package with a 60-minute limit (pc/plans/walk-e2bcpu.json, walk-foundry-cpu.json)
Z2_VENV=ovexport tools/pc.sh py 'pc\onnx_quant.py' --out "$W\logs\onnx_quant.json" "$W\models" '$env:USERPROFILE\.foundry\cache\models'
tools/pc.sh pull logs raw/setup-walk && python3 tools/scrub.py --names <PC account>,<Mac account> raw/setup-walk
tools/pc.sh wait "$W\logs\export_npu_g128.done" "$W\logs\export_npu_g128.log" 4
tools/pc.sh launch 'pc\export_npu.ps1' '-Group -1 -Only gemma-4-E4B-it'
tools/pc.sh wait "$W\logs\export_npu_cw_gemma-4-E4B-it.done" "$W\logs\export_npu_cw_gemma-4-E4B-it.log" 2
python3 tools/probe_plan.py --sitting walk-npu-fix1 --from walk-first --cell ort-genai_npu_openvino \
  --add "--ep-option enable_causallm=True" --note "NPU fix 1 of 3: enable_causallm=True (the EP's stateful LLM mode)"
python3 tools/probe_plan.py --sitting walk-npu-fix2 --from walk-first --cell ort-genai_npu_openvino --models Qwen3-0.6B \
  --add "--ov-bounds 2048" --note "NPU fix 2 of 3: reshape_input with batch 1 and the other dimensions bounded to 2048"
python3 tools/probe_plan.py --sitting walk-npu-fix3 --from walk-first --cell ort-genai_npu_openvino --models Qwen3-0.6B \
  --add "--ep-option disable_dynamic_shapes=True" --note "NPU fix 3 of 3: disable_dynamic_shapes=True"
python3 tools/make_plan.py --sitting walk-npuexp --set npuexport --runs 1
python3 tools/make_plan.py --sitting walk-npuexp-cw --set npuexport --group -1 --only gemma-4-E4B-it --runs 1 && tools/pc.sh push
P=walk-npu-fix1,walk-npu-fix2,walk-npu-fix3,walk-npuexp,walk-npuexp-cw,walk-foundry-fix1,walk-foundry-fix2,walk-foundry-fix3
tools/pc.sh launch 'pc\chain_seq.ps1' "-Plans $P,walk-e2bcpu,walk-foundry-cpu -Mode first"
tools/pc.sh wait "$W\runs\chain_seq.done" "$W\runs\walk-npuexp\chain.log" 4
S="walk-first walk-npu walk-npu-fix1 walk-npu-fix2 walk-npu-fix3 walk-npuexp walk-npuexp-cw walk-foundry-fix1 walk-foundry-fix2"
S="$S walk-foundry-fix3 walk-e2bcpu walk-foundry-cpu"
for s in $S; do tools/pc.sh pull "runs/$s" raw; done
python3 tools/scrub.py --names <PC account>,<Mac account> $(for s in $S; do echo raw/$s; done)
# 8. the timed sitting of the cells that passed (lock, gate, anchors = edge-llm-bench rows run at the start and the end
#    as the sitting's reference, timed chain, rerun of cells over the spread line, anchors, release, pull)
python3 tools/timed_plan.py --sitting walk-timed $(for s in $S; do echo --from $s; done) && tools/pc.sh push
tools/sitting.sh walk-timed --bench pc/bench_rerun.cells
# 9. results, the bench's own rows (the anchors' reference), anchors and the table (raw/walk-timed-rerun only when
#    step 8 wrote one)
python3 tools/ir_quant.py
python3 tools/build_results.py $(for s in $S walk-timed walk-timed-rerun; do echo raw/$s; done)
python3 tools/collect_bench.py --raw-dir raw/bench
python3 tools/anchors.py && python3 tools/table.py
```

The walk's own record of each step is `raw/walk/walk.log`.

### How the walk of 2026-11-07/08 differed from the steps above

The walk ran in `C:\src\llmzoo-walk` on the shared PC, next to other projects' timed sittings. Steps 1 to 5 ran as written
(17:15 to 19:36). From step 3 on, the scripts were fixed while the walk ran; the steps above are the fixed form.

- Step 3 ran in parts. The first exports ended with exit 1 (Qwen3-0.6B after 172 s, Qwen3-1.7B and Gemma 4 E4B after
  15 s each); their error, read at the time (the later exports overwrote the stderr files), was `RuntimeError: Cannot
  infer the task from a local directory yet`, and `--task` was added at 20:33. Qwen3-4B joined at 23:17, after its
  published IR gave no usable answer on the NPU (one word repeated, or an empty answer: `raw/diag/q4npu.log`). The Gemma 4 E4B export was stopped by hand at 23:11,
  with the PC's available RAM under 1 GB (the log's `exit -1`, lowest available RAM 0.9 GB), and taken again (done
  02:28). Its channel-wise export was started at 02:48; other jobs' locks stopped it several times, and it ran
  through from 03:45 to 03:53 (`raw/setup-walk/logs/export_npu_cw_gemma-4-E4B-it.log`).
- Step 6 ran as one plan, `walk-first`, with all 69 cells. Four of its OpenVINO GenAI NPU cells were skipped there
  with a marker file and ran in their own chains: `walk-npu-sym` (Qwen3-4B, Gemma 4 E2B), `walk-npu-asym`
  (Qwen3-1.7B), `walk-npu-e4bpub` (Gemma 4 E4B). The marker dirs were deleted before the results were built.
- `walk-first` was restarted five times (23:47, 02:07, 03:03, 03:42, 04:40), each time with fixed scripts. A run with
  a meta file on disk was not taken again.
- Two runner fixes came mid-walk. From 23:19, Gemma 4 IR folders go to `VLMPipeline` (Gemma 4 E2B on the NPU again:
  `walk-npu-vlm`). From 03:42, Foundry Local runs count every text field of each streamed chunk's `delta` (Qwen3's
  thinking comes in `reasoning_content`): the nine Qwen3 Foundry cells were taken again in `walk-foundry2`.
- The exported-IR probes ran as `walk-npuexp` (Qwen3-0.6B, 1.7B), `walk-npuexp2` (Qwen3-4B), `walk-npuexp3`
  (Gemma 4 E4B, group 128) and `walk-npuexp4` (Gemma 4 E4B, channel-wise). Step 7 above names them `walk-npuexp` and
  `walk-npuexp-cw`.
- The two Gemma 4 E2B CPU cells did not finish in `walk-first`. The ORT GenAI one stopped at the first pass's 15
  running minutes and passed in `walk-e2bcpu` with 60. The Foundry one was stopped eight times by other jobs'
  locks; a marker put by hand in `walk-foundry-cpu`'s run folder made that plan skip the cell (another hour of first
  pass would have delayed the timed sitting), so the cell went into the timed sitting without a finished first pass (`added_by_hand` in `pc/plans/walk-timed.json`).
- Step 8 ran in two sittings. `walk-timed` (11-08 07:22 to 09:06) timed its first 18 units (a unit is one cell's
  runs in a plan); from 08:41 the gate
  before the next run waited on available RAM (4.9 to 5.0 GB, the run needed 5.2 GB), and the chain was stopped by hand at
  08:52. `tools/sitting.sh walk-timed --close` then ran the tail anchors (edge-llm-bench rows run at the start and
  the end of a sitting, as its reference: `PLAN.md` §5), released the lock and pulled the records;
  the chain's RAM stop and `pcup\window.txt` came after it. `walk-timed-b` (11-08 18:14 to 11-09 09:31,
  `pc/plans/walk-timed-b.json`, written by hand) first timed again the six `walk-timed` cells whose cold spread
  ((max − min) / median of the counted runs' cold decode) was over 5 %, then the 46 units `walk-timed` had not reached, and last, as its rerun (`walk-timed-b-rerun`,
  `pc/plans/walk-timed-b-rerun.json`), the 12 of its units whose cold spread was over 5 %. Other jobs on this PC needed the lock at set
  times while it ran, so the chain was suspended between two of its runs from 19:51 to 20:01 (`pc/planned_gap.ps1`,
  lock off from 19:51 with `pcup\window.txt`), from 20:25 to 20:37 (lock off 20:30 to 20:35) and from 21:04 to
  22:55 (lock off from 21:07) (`pc/slots.ps1`, `pc/plans/walk-timed-b-slots*.json`, without `window.txt`). Each
  time the lock came back only after the other job had given it back, then the chain settled 60 s and passed the
  gate before its next run. The chain itself released the lock for waiting jobs on the form it started with (before
  a run, after 30 minutes held; taken back 30 s after the other job gave it back). The Mac's wait for the chain (12 hours then) would have ended at 06:28; so that it would not end before the chain (the
  six runs of the two Gemma 4 E2B CPU cells were still to come), at 22:54, inside the 60 s settle after the lock was
  taken back, it was replaced by `tools/sitting.sh walk-timed-b --resume`, which waits again and then goes on to the
  rerun and the tail anchors (the chain ended at 04:31). Another job made one SSH call of about 1 s (writing its own note) at 02:17:01, inside
  run 3 of the Gemma 4 E2B ORT GenAI CPU cell, as reported at the time (this repo's records do not show it); that run
  is counted. The rerun chain started at 04:31:48 on the chain's later form (the `pc/chain.ps1` published here, but for one later change: the window file is also
  removed when its time ends):
  before a run, while another job waited, it released the lock once it had held it 30 minutes or when the run would
  end past those 30 minutes (not for the first run after a take), and took it back only once the lock had stayed
  free 180 s after the other job gave it back (`retake_free_sec` in the plan); its lock text gave each run's
  expected end ("run until about HH:mm"). It released the lock before its first run (04:31:59; the lock had been
  held since 03:04), took it back at 08:12:13 and passed the gate at 08:13:33. `pc/slots.ps1` suspended it between
  two runs from 08:31:25 to 08:55:37 for another job (lock off 08:34:00 to 08:54:17,
  `pc/plans/walk-timed-b-slots-x.json`). Its 12 units ended at 09:19:03; the tail anchors ran from 09:19:15 and the
  lock was released at 09:31:47. The Mac's wait for the rerun chain ended early at 06:27:18 while the chain ran on; it
  was started again at 06:28:47 and, as that wait wrote nothing to the log, once more at 07:39:06: the 14 lines after the
  07:39:06 line in `raw/walk-timed-b.sitting.log` repeat the rerun chain's log from its start. Step 9 here read the
  run folders `walk-first`, `walk-npu-sym`, `walk-npu-asym`, `walk-npu-e4bpub`, `walk-npu-vlm`, `walk-npu-fix1` to
  `walk-npu-fix3`, `walk-npuexp`, `walk-npuexp2` to `walk-npuexp4`, `walk-foundry2`, `walk-foundry-fix1` to
  `walk-foundry-fix3`, `walk-e2bcpu`, `walk-timed`, `walk-timed-b` and `walk-timed-b-rerun` (`walk-foundry-cpu` holds
  only the record of its skipped run).
