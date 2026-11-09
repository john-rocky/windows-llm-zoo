#!/usr/bin/env python3
"""Write results/<model>/<cell>.json for the LLM cells edge-llm-bench already measured on this PC.

    python3 tools/collect_bench.py [--bench ~/code/edge-llm-bench]

Source: the bench's committed summary (`git show HEAD:results/summary/device-runs.csv`, never the disk copy, which a
shared checkout can hold other sessions' rows in), the Windows rows only. One number per sitting: the bench's own
aggregation (`scripts/render_leaderboard.arm_row`) over one campaign's runs of one (arm, model) cell, the Windows
headline regime (cold: the first conversation of each engine process; a run marked firstEver, the engine's cache
build, and a run whose text failed the check are left out by arm_row itself). A sitting whose cold spread
((max - min) / median) passes 5 % is `out` there (the bench's spread rule) and gives no number.

The cell's number is the newest sitting's; when that sitting reads `out`, the other sitting of the back-to-back pair
(the bench ran each column twice in a row) gives it, named in the JSON. Every sitting of the cell stays in the JSON.
"""
import argparse
import csv
import io
import json
import os
import pathlib
import statistics
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parents[1]
SPREAD_LINE = 5.0  # the bench's spread rule (render_leaderboard.SPREAD_FLAG)

MODELS = {
    "litert-community/gemma-4-E2B-it-litert-lm": "gemma-4-E2B-it",
    "unsloth/gemma-4-E2B-it-GGUF": "gemma-4-E2B-it",
    "litert-community/gemma-4-E4B-it-litert-lm": "gemma-4-E4B-it",
    "unsloth/gemma-4-E4B-it-GGUF": "gemma-4-E4B-it",
    "litert-community/Qwen3-0.6B": "Qwen3-0.6B",
    "unsloth/Qwen3-0.6B-GGUF": "Qwen3-0.6B",
    "litert-community/Qwen3-1.7B": "Qwen3-1.7B",
    "unsloth/Qwen3-1.7B-GGUF": "Qwen3-1.7B",
    "litert-community/Qwen3-4B": "Qwen3-4B",
    "unsloth/Qwen3-4B-GGUF": "Qwen3-4B",
}
# bench arm -> (runtime, device, backend, what the backend is)
ARMS = {
    "litert-lm-cpu": ("litert-lm", "cpu", "cpu", "LiteRT-LM CPU (XNNPACK), engine default threads (4)"),
    "litert-lm-gpu": ("litert-lm", "rtx", "gpu", "LiteRT-LM GPU (WebGPU on Direct3D 12), the discrete GPU"),
    "litert-lm-gpu-igpu": ("litert-lm", "igpu", "gpu", "LiteRT-LM GPU (WebGPU on Direct3D 12), the integrated GPU "
                           "(Windows' per-app GpuPreference=1;)"),
    "litert-lm-npu": ("litert-lm", "npu", "npu", "LiteRT-LM NPU, the Intel dispatch (OpenVINO) with the repo's "
                      "Panther Lake bundle"),
    "llama.cpp": ("llama.cpp", "cpu", "cpu", "llama.cpp CPU asset, llama-cli default threads (16)"),
    "llama.cpp-gpu": ("llama.cpp", "rtx", "vulkan", "llama.cpp Vulkan asset, GGML_VK_VISIBLE_DEVICES=0 (the RTX)"),
    "llama.cpp-cuda": ("llama.cpp", "rtx", "cuda", "llama.cpp CUDA 13.4 asset + the release's CUDA runtime zip"),
}
from build_results import DEVICES  # noqa: E402  (one list of the names Windows reports)


def summary_rows(bench: pathlib.Path) -> list:
    text = subprocess.run(["git", "-C", str(bench), "show", "HEAD:results/summary/device-runs.csv"],
                          check=True, capture_output=True, text=True).stdout
    return [r for r in csv.DictReader(io.StringIO(text)) if r["platform"] == "windows"]


def jst(ts: str) -> str:
    import datetime as dt
    t = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return t.astimezone(dt.timezone(dt.timedelta(hours=9))).strftime("%Y-%m-%d %H:%M JST")


def sitting_entry(arm_row, rows: list) -> dict:
    a = arm_row(rows)
    counted = bool(a["cold_median"]) and a["cold_spread"] <= SPREAD_LINE
    camp = a["campaign"]
    first = min(r["timestamp"] for r in rows)
    warm = [float(r["decode_tps"]) for r in rows
            if r["cold_run"] == "False" and r.get("first_ever") != "True" and r["decode_tps"]
            and not (r.get("text_check") or "").startswith("FAIL")]
    return {
        "campaign": camp.split("/")[-1],
        "first_record_jst": jst(first),
        "os": sorted({r["os_version"] for r in rows}),
        "engine": a["engine"],
        "runs_in_sitting": len({r["timestamp"] for r in rows if r["cold_run"] == "True"}),
        "cold_n": a["cold_n"],
        "decode_tps_cold_median": a["cold_median"],
        "cold_spread_pct": round(a["cold_spread"], 2),
        "counted": counted,
        "prefill_tps_cold_median": a["prefill"],
        "ttft_ms_cold_median": a["ttft"],
        "peak_working_set_mb_median": a["mem_peak"],
        "decode_tps_warm_median": statistics.median(warm) if warm else None,
        "text_check": f"{a['text_checked_n'] - a['text_fail_n']}/{a['text_checked_n']} PASS",
        "quant": a["quant"],
        "records": sorted({r["source"] for r in rows}),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--bench", default=os.path.expanduser("~/code/edge-llm-bench"))
    ap.add_argument("--raw-dir", action="append", default=[],
                    help="this repo's dir of bench-executor records (raw/bench): its campaigns join the bench's as more "
                         "sittings of the same cells (summarized by the bench's build_summary.py into a temp dir)")
    args = ap.parse_args(argv)
    bench = pathlib.Path(args.bench)
    sys.path.insert(0, str(bench / "scripts"))
    from render_leaderboard import arm_row  # the bench's one aggregation (CLAUDE.md: never a second one)

    head = subprocess.run(["git", "-C", str(bench), "rev-parse", "HEAD"], check=True, capture_output=True,
                          text=True).stdout.strip()
    rows = summary_rows(bench)
    for rd in args.raw_dir:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run([sys.executable, str(bench / "scripts" / "build_summary.py"), "--raw-dir",
                            str(pathlib.Path(rd).resolve()), "--out-dir", tmp], check=True, capture_output=True, text=True)
            extra = [r for r in csv.DictReader(open(pathlib.Path(tmp) / "device-runs.csv", encoding="utf-8"))
                     if r["platform"] == "windows"]
        for r in extra:  # record paths relative to this repo
            src = r["source"].replace("\\", "/")
            r["source"] = src[src.index("raw/"):] if "windows-llm-zoo/raw/" in src else src
        print(f"{len(extra)} rows from {rd}")
        rows += extra
    cells = {}
    for r in rows:
        cells.setdefault((r["runtime"], r["model_id"]), {}).setdefault(r["campaign"], []).append(r)
    written = 0
    for (arm, mid), by_camp in sorted(cells.items()):
        runtime, device, backend, what = ARMS[arm]
        model = MODELS[mid]
        sittings = [sitting_entry(arm_row, rs) for _, rs in sorted(by_camp.items(),
                                                                  key=lambda kv: min(r["timestamp"] for r in kv[1]))]
        newest = sittings[-1]
        pick = newest if newest["counted"] else None
        if pick is None and len(sittings) > 1:
            partner = sittings[-2]
            # the back-to-back partner: the bench's pairs are "<name>-s1" then "<name>"
            if partner["counted"] and partner["campaign"] in (newest["campaign"] + "-s1", newest["campaign"][:-3]):
                pick = partner
        files = sorted({os.path.basename(r["model_file"]) for rs in by_camp.values() for r in rs})
        out = {
            "model": model,
            "cell": f"{runtime}_{device}_{backend}",
            "runtime": runtime,
            "device": device,
            "device_name": DEVICES[device],
            "backend": backend,
            "backend_detail": what,
            "source": "edge-llm-bench",
            "bench_arm": arm,
            "bench_commit": head,
            "shelf": {"repo": mid, "files": files, "quant": newest["quant"]},
            "workload": {"task": "short-chat", "prompt": "prompts/text/short-chat.txt of edge-llm-bench",
                         "output_budget_tokens": 128, "context_tokens": 2048 if arm != "litert-lm-npu"
                         else "fixed by the bundle", "regime": "cold (first conversation of a fresh engine process)",
                         "counting": "runs=3 per sitting; run 1 of a LiteRT-LM, Vulkan or CUDA row is the cache "
                                     "build (firstEver) and is not counted; a text-check failure is not counted"},
            "status": "measured" if pick else "out",
            "table": None if pick is None else {
                "sitting": pick["campaign"],
                "decode_tps": pick["decode_tps_cold_median"],
                "cold_spread_pct": pick["cold_spread_pct"],
                "cold_n": pick["cold_n"],
                "prefill_tps": pick["prefill_tps_cold_median"],
                "ttft_ms": pick["ttft_ms_cold_median"],
                "peak_working_set_mb": pick["peak_working_set_mb_median"],
                "text_check": pick["text_check"],
                "decode_tps_warm": pick["decode_tps_warm_median"],
            },
            "sittings": sittings,
        }
        d = HERE / "results" / model
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{out['cell']}.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        written += 1
        t = out["table"]
        print(f"{model:16s} {out['cell']:22s} "
              + (f"{t['decode_tps']:7.2f} tok/s  spread {t['cold_spread_pct']:5.2f}%  n={t['cold_n']}  {t['sitting']}"
                 if t else f"   out  ({', '.join(s['campaign'] + ' ' + str(s['cold_spread_pct']) for s in sittings[-2:])})"))
    print(f"{written} cells written from edge-llm-bench {head[:8]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
