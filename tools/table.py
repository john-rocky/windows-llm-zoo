#!/usr/bin/env python3
"""Write the table of RESULTS_LLM_WINDOWS.md (between its `<!-- table:begin -->` and `<!-- table:end -->` lines) from
results/<model>/<cell>.json, plus the rows of the cells that are not measured, each with its reason (NOT_RUN below).

    python3 tools/table.py
"""
import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parents[1]
OUT = HERE / "RESULTS_LLM_WINDOWS.md"
MODELS = ["Qwen3-0.6B", "Qwen3-1.7B", "Qwen3-4B", "gemma-4-E2B-it", "gemma-4-E4B-it"]
DEVICES = ["npu", "igpu", "rtx", "cpu"]
DEVICE_NAME = {"npu": "Intel NPU", "igpu": "Intel GPU", "rtx": "RTX 5080 Laptop", "cpu": "CPU (Core Ultra 9 386H)"}
RUNTIMES = ["litert-lm", "llama.cpp", "ort-genai", "foundry", "openvino-genai"]
RUNTIME_NAME = {"litert-lm": "LiteRT-LM v0.19.0", "llama.cpp": "llama.cpp b11721", "ort-genai": "ORT GenAI 0.19.0",
                "foundry": "Foundry Local 0.13.0", "openvino-genai": "OpenVINO GenAI 2026.4.1"}
ALL = ["Qwen3-0.6B", "Qwen3-1.7B", "Qwen3-4B", "gemma-4-E2B-it", "gemma-4-E4B-it"]
QWEN = ALL[:3]
# (runtime, device, backend, models, reason): cells that are not measured, with the reason
NOT_RUN = [
    ("litert-lm", "npu", "npu", QWEN + ["gemma-4-E4B-it"],
     "no Intel NPU bundle in the litert-community repo (edge-llm-bench windows/README)"),
    ("llama.cpp", "npu", "openvino", ALL,
     "the bench pins only the cpu / vulkan / cuda assets of b11721 (edge-llm-bench windows/engine-pins.json); the "
     "release's `llama-b11721-bin-win-openvino-2026.4.1-x64.zip` is not pinned (a bench change)"),
    ("llama.cpp", "igpu", "vulkan / sycl", ALL,
     "the bench's Windows cells run the Vulkan asset on the discrete GPU only (no `adapter=igpu` llama.cpp row, "
     "edge-llm-bench matrices/dashboard-windows-v1.cells), and the release's `llama-b11721-bin-win-sycl-x64.zip` is not "
     "pinned (a bench change)"),
    ("foundry", "npu", "openvino", ALL,
     "no OpenVINO variant of these models in the catalog (`foundry model list --variants`, 2026-11-07 16:04: "
     "`raw/setup/foundry_variants.json`)"),
    ("foundry", "igpu", "openvino / webgpu", ALL,
     "no OpenVINO variant of these models in the catalog (`raw/setup/foundry_variants.json`); the catalog's WebGPU "
     "variant ran on the RTX in every Foundry WebGPU run here (each run's GPU memory is on the NVIDIA adapter)"),
    ("foundry", "rtx", "webgpu", ["gemma-4-E4B-it"],
     "no WebGPU package: the catalog has no Gemma 4 E4B (`raw/setup/foundry_variants.json`), and "
     "mlboydaisuke/gemma-4-E4B-it-Foundry-Local holds only `cpu-int4` and `cuda-int4-8k` (HF API tree, revision 9d1751f)"),
]


def fmt(x, nd=1):
    if x is None:
        return "—"
    if isinstance(x, (int, float)):
        return f"{x:,.{nd}f}"
    return str(x)


def record_path(d):
    t = d.get("table") or {}
    if d.get("source") == "edge-llm-bench":
        s = next((s for s in d.get("sittings", []) if s["campaign"] == t.get("sitting")), None)
        recs = (s or {}).get("records") or [r for x in d.get("sittings", []) for r in x.get("records") or []]
        return "bench `" + "`, `".join(recs) + "`" if recs else "bench (no record)"
    sits = [s["sitting"] for s in d.get("sittings", [])]
    raw = f"raw/{t['sitting']}/{d['model']}/{d['cell']}/" if t else (f"raw/{sits[-1]}/{d['model']}/{d['cell']}/" if sits else "")
    return f"`results/{d['model']}/{d['cell']}.json`" + (f", `{raw}`" if raw else "")


def package(d):
    """repo + folder or file + quantization, from the results JSON's shelf."""
    sh = d.get("shelf") or {}
    if not sh:
        return "—"
    where = sh.get("folder") or ", ".join(sh.get("files") or [])
    q = sh.get("quant")
    qs = sh.get("quant_source")
    quant = f"{q}" + (f" ({qs})" if qs and d.get("source") != "edge-llm-bench" else "") if q else (qs or "—")
    return (f"{sh.get('repo')}" + (f" `{where}`" if where else "") + f" · {quant}").replace("|", "/")


def row(d):
    t = d.get("table") or {}
    st = d.get("status")
    if st == "measured":
        dec = fmt(t.get("decode_tps"), 2)
        spread = f" (±{fmt(t.get('cold_spread_pct'), 1)} %, n {t.get('cold_n')})"
        check = t.get("text_check") or "—"
    elif st == "out":
        dec, spread, check = "out", " (spread > 5 %)", "—"
    else:
        why = (d.get("why_not_measured") or st or "").replace("|", "/")
        dec, spread, check = "not measured", f" ({why})", ("FAIL" if st == "output-check" else "—")
    mem = t.get("peak_working_set_mb")
    return (f"| {d['model']} | {RUNTIME_NAME.get(d['runtime'], d['runtime'])} | {DEVICE_NAME.get(d['device'], d['device'])} | "
            f"{d.get('backend')} | {package(d)} | {dec}{spread} | {fmt(t.get('prefill_tps'))} | {fmt(t.get('ttft_ms'), 0)} | "
            f"{fmt(mem, 0) if mem else '—'} | {check} | {t.get('sitting') or '—'} | {record_path(d)} |")


def main():
    cells = {}
    for p in sorted((HERE / "results").glob("*/*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        cells[(d["model"], d["device"], d["runtime"], d["cell"])] = d
    lines = ["| model | runtime | device | backend / EP | package · quantization | decode tok/s (cold) | prefill tok/s | "
             "TTFT ms | peak memory (MiB) | output check | session | record |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for m in MODELS:
        for dev in DEVICES:
            for rt in RUNTIMES:
                for key in sorted(k for k in cells if k[0] == m and k[1] == dev and k[2] == rt):
                    lines.append(row(cells[key]))
                for r, d, b, ms, why in NOT_RUN:
                    if r == rt and d == dev and m in ms:
                        lines.append(f"| {m} | {RUNTIME_NAME[r]} | {DEVICE_NAME[d]} | {b} | — | not run ({why}) | — | — | — | — | — | — |")
    text = OUT.read_text(encoding="utf-8") if OUT.is_file() else "<!-- table:begin -->\n<!-- table:end -->\n"
    head, rest = text.split("<!-- table:begin -->", 1)
    _, tail = rest.split("<!-- table:end -->", 1)
    OUT.write_text(head + "<!-- table:begin -->\n" + "\n".join(lines) + "\n<!-- table:end -->" + tail, encoding="utf-8")
    print(f"{OUT.name}: {len(lines) - 2} rows")


if __name__ == "__main__":
    main()
