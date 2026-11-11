# What each folder holds

A cell is one combination of model, runtime, device and backend. A sitting is one measuring session on the PC, under one name, timed or not. A walk is one run of every step from an empty folder.

| path | what |
|---|---|
| `RESULTS_LLM_WINDOWS.md` | not committed: `tools/table.py` writes the table from `results/` ([step 9](reproduce.md)) |
| `results/<model>/<runtime>_<device>_<backend>.json` | one JSON per cell: the number, every sitting and run, errors in full (`peak_working_set_mb` is in MiB: bytes / 2^20) |
| `raw/<sitting>/` | the PC's run files of each sitting: the runner's JSON, the meta file written by the chain (`pc/chain.ps1`, the PC-side script that runs a plan), stdout / stderr, `env.*.json` |
| `raw/anchors/`, `raw/bench/` | edge-llm-bench records taken by its own executor in this repo's sittings |
| `raw/setup/` | the PC's setup logs: venv versions, the Hub fetch report, Foundry Local's catalog and package file lists |
| `raw/setup-walk/logs/` | the same for [the walk](reproduce.md), and the NPU exports: each command and log, each IR's files with sha256 (`export_*.ir.json`) |
| `raw/diag/` | hand diagnostics of OpenVINO GenAI, 2026-11-07 and 08: NPU runs and one CPU run (`pc/diag_ovgenai.ps1`) |
| `raw/z2-e2e-1/`, `raw/z2-first-a/` | rehearsals of 2026-11-07, begun before the walk (15:32 and 15:48; `z2-first-a` was still waiting for the lock at 18:00), in another folder of the PC (`C:\src\llmzoo`) (their plans: `pc/plans/z2-e2e-1.json`, `z2-first-a.json`; the other `z2-*.json` plans of that day have no records here) |
| `shelf/export_manifest.json`, `shelf/ov_ir_quant.json` | the export's pinned checkpoints; the quantization (rt_info) of the published OpenVINO IRs |
| `pc/` | everything that runs on the PC (Windows PowerShell 5.1 and Python) |
| `pc/plans/` | the plans as run (`tools/make_plan.py`, `tools/probe_plan.py`, `tools/timed_plan.py`, `tools/rerun_plan.py`) |
| `mtools/variant_pkg.py` | the overlay tool of `john-rocky/gemma-4-e4b-on-foundry-local` (its `variant_pkg.py` at a5ca414, copied unchanged, sha256 `1ca0f334...`) |
| `tools/` | the Mac side: plans, the sitting driver, result and table builders, the bench collector, `scrub.py` |
| `shelf/hub_manifest.json` | every Hub file a cell loads: repo, pinned revision, size, sha256 or git blob sha1 |
| `PLAN.md` | the method, written before measuring |
