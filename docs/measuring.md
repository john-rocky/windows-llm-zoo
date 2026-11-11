# How the results are measured

A cell is one combination of model, runtime, device and backend. A sitting is one measuring session on the PC, under one name, timed or not. A walk is one run of every step from an empty folder.

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
  runtime's numbers are cut and counted: [`PLAN.md`](../PLAN.md).
- Four of the five NPU-form IRs exported here (an IR is OpenVINO's model format; int4 symmetric weights, ratio 1.0;
  [steps 3 and 7 of the full run](reproduce.md)) are on the Hugging Face Hub:
  [`mlboydaisuke/Qwen3-0.6B-int4-sym-g128-ov`](https://huggingface.co/mlboydaisuke/Qwen3-0.6B-int4-sym-g128-ov),
  [`mlboydaisuke/Qwen3-1.7B-int4-sym-g128-ov`](https://huggingface.co/mlboydaisuke/Qwen3-1.7B-int4-sym-g128-ov),
  [`mlboydaisuke/Qwen3-4B-int4-sym-g128-ov`](https://huggingface.co/mlboydaisuke/Qwen3-4B-int4-sym-g128-ov),
  [`mlboydaisuke/gemma-4-E4B-it-int4-sym-cw-ov`](https://huggingface.co/mlboydaisuke/gemma-4-E4B-it-int4-sym-cw-ov).
  Each card gives the export command and versions and this laptop's NPU numbers; every file on the Hub was checked
  against the export's record (size and sha256, `raw/setup-walk/logs/export_*.ir.json`).

A table that puts the runtimes side by side is not committed here, as in edge-llm-bench: `tools/table.py` writes it
from `results/` on your disk (`RESULTS_LLM_WINDOWS.md`, [step 9 of the full run](reproduce.md)). TensorRT-RTX and TensorRT-Edge-LLM are not
run here.
