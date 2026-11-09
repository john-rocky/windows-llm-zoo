# LICENSES — what each row of the table runs and loads, and its licence (read 2026-11-07 15:30–18:2x JST)

Read from the primary record named in the last column; nothing here is an interpretation of a licence. "unverified" =
not read to the end, or not readable.

## Runtimes

| runtime (as run here) | licence | where read |
|---|---|---|
| LiteRT-LM v0.19.0 (bench rows) | Apache-2.0 | GitHub API `repos/google-ai-edge/LiteRT-LM` license |
| llama.cpp b11721 (bench rows) | MIT | GitHub API `repos/ggml-org/llama.cpp` license |
| ONNX Runtime GenAI 0.19.0 (`onnxruntime-genai`, `onnxruntime-genai-cuda`) | MIT | PyPI `license` field; GitHub `microsoft/onnxruntime-genai` |
| ONNX Runtime 1.31.1 (`onnxruntime`, `onnxruntime-gpu`) | MIT | PyPI `license` field |
| OpenVINO EP plugin `onnxruntime-ep-openvino` 1.8.1 | MIT | PyPI `license` field |
| WebGPU EP plugin `onnxruntime-ep-webgpu` 0.5.0 | MIT | PyPI `license_expression` |
| OpenVINO GenAI 2026.4.1 (`openvino-genai`, `openvino`, `openvino-tokenizers`) | Apache-2.0 | PyPI `license` / `license_expression` fields |
| Foundry Local 0.13.0 CLI | Microsoft licence terms ("FOUNDRY LOCAL CLI" section of the repo's LICENSE; the SDK section is MIT). Section 3: "Models are governed by the license terms associated with each model." Section 4a: the software may collect usage data. Section 5 lists what one may not do with the software; no clause on benchmarks or results in any of its 13 sections ("benchmark" appears nowhere in the file) | `microsoft/foundry-local` LICENSE (GitHub API: NOASSERTION) |
| CUDA 12 / 13 runtime, cuBLAS, cuDNN, NVRTC wheels (`nvidia-*`) | NVIDIA's own terms: unverified (PyPI says `LicenseRef-NVIDIA-Proprietary` for `nvidia-cuda-runtime-cu12`, nothing for `nvidia-cudnn-cu12`) | PyPI fields |
| TensorRT-RTX, TensorRT-Edge-LLM | not run here, no numbers | their terms were not read here: unverified |

## Tools that make a shelf here (the NPU-form export, `pc/req/ovexport.txt`; read 2026-11-07 18:2x JST)

| package | licence | where read |
|---|---|---|
| optimum-intel 2.2.0, optimum 2.3.0 | Apache | PyPI `license` field |
| transformers 5.5.4 | Apache 2.0 License | PyPI `license` field |
| nncf 3.4.0, onnx 1.23.2 | Apache-2.0 | PyPI `license` / `license_expression` |
| torch 2.14.0 | Apache-2.0 AND Apache-2.0 WITH LLVM-exception AND BSD-2-Clause AND BSD-3-Clause AND BSL-1.0 AND MIT | PyPI `license_expression` |
| torchvision 0.29.0 | BSD | PyPI `license` field |

## Shelves (the model files a cell loads)

| shelf | licence on the repo | base model's licence | where read |
|---|---|---|---|
| `litert-community/Qwen3-{0.6B,1.7B,4B}` (bench) | apache-2.0 | apache-2.0 | HF API tags |
| `litert-community/gemma-4-E2B-it-litert-lm`, `-E4B-it-litert-lm` (bench) | apache-2.0 | apache-2.0 (`google/gemma-4-E2B-it`, `-E4B-it`) | HF API tags |
| `unsloth/Qwen3-*-GGUF`, `unsloth/gemma-4-E{2,4}B-it-GGUF` (bench) | apache-2.0 | apache-2.0 | HF API tags |
| `onnx-community/Qwen3-{0.6B,1.7B,4B}-ONNX` | none on the repo (no tag, no card field) | apache-2.0 (`Qwen/Qwen3-0.6B`, `-1.7B`, `-4B`) | HF API tags and cardData |
| `mlboydaisuke/gemma-4-E4B-it-Foundry-Local` | apache-2.0 | apache-2.0 | HF API |
| `OpenVINO/Qwen3-*-int4-ov`, `OpenVINO/gemma-4-E{2,4}B-it-int4(-cw)-ov` | apache-2.0 | apache-2.0 | HF API cardData |
| `Qwen/Qwen3-0.6B`, `Qwen/Qwen3-1.7B`, `Qwen/Qwen3-4B`, `google/gemma-4-E4B-it` (the export's checkpoints, `shelf/export_manifest.json`) | apache-2.0 | (these are the base models) | HF API tags, 2026-11-07 18:1x |
| `models\z2-npu\{Qwen3-0.6B,Qwen3-1.7B,Qwen3-4B,gemma-4-E4B-it}-int4-sym-g128-ov`, `gemma-4-E4B-it-int4-sym-cw-ov` (exported here from the four above by `pc/export_npu.ps1`) | none of its own on the PC | apache-2.0 | the base models' licence |
| `mlboydaisuke/Qwen3-{0.6B,1.7B,4B}-int4-sym-g128-ov`, `mlboydaisuke/gemma-4-E4B-it-int4-sym-cw-ov` (four of the exports above, uploaded 2026-11-09) | apache-2.0 (each card's `license` field, the base model's) | apache-2.0 | the cards' `base_model` and the base models' licence above |
| Foundry Local catalog `gemma-4-e2b-it-{cuda-gpu,generic-gpu,generic-cpu}:3`, `qwen3-{0.6b,1.7b,4b}-{cuda-gpu,generic-gpu,generic-cpu}:*` (12 variants) | apache-2.0 (the catalog's `license` field of each of the 12) | apache-2.0 | `foundry model list --variants -o json` on the PC, 11-07 16:04, the last of that day's listings (`raw/setup/foundry_variants.json`) |
