# Run everything from an empty folder

A cell is one combination of model, runtime, device and backend. A sitting is one measuring session on the PC, under one name, timed or not. A walk is one run of every step from an empty folder.

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
