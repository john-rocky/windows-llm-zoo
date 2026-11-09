#!/usr/bin/env python3
"""The session anchors of the Z2 sittings: raw/anchors/<campaign>/ (bench records, written by the bench's executor
with BENCH_RAW_ROOT=raw/anchors) -> raw/anchors/anchors.json and one line per sitting and device for the table.

    python3 tools/anchors.py [--bench ~/code/edge-llm-bench]

Each anchor campaign is summarized by the bench's own builder (scripts/build_summary.py --raw-dir raw/anchors
--out-dir <tmp>) and aggregated by the bench's one aggregation (render_leaderboard.arm_row) per (campaign, arm, model):
never pooled across campaigns. The drift of a device = the anchor's cold decode median / the same cell's number in the
bench's table sitting (results/<model>/<cell>.json of the bench cells) - 1.
"""
import argparse
import csv
import json
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parents[1]
ANCHORS = {  # bench arm, model id -> (device, the bench cell's results file)
    ("litert-lm-cpu", "litert-community/gemma-4-E2B-it-litert-lm"): ("cpu", "gemma-4-E2B-it/litert-lm_cpu_cpu.json"),
    ("litert-lm-npu", "litert-community/gemma-4-E2B-it-litert-lm"): ("npu", "gemma-4-E2B-it/litert-lm_npu_npu.json"),
    ("llama.cpp-cuda", "unsloth/gemma-4-E2B-it-GGUF"): ("rtx", "gemma-4-E2B-it/llama.cpp_rtx_cuda.json"),
    ("litert-lm-gpu-igpu", "litert-community/Qwen3-1.7B"): ("igpu", "Qwen3-1.7B/litert-lm_igpu_gpu.json"),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", default=str(pathlib.Path.home() / "code" / "edge-llm-bench"))
    args = ap.parse_args()
    bench = pathlib.Path(args.bench)
    sys.path.insert(0, str(bench / "scripts"))
    from render_leaderboard import arm_row  # the bench's one aggregation

    raw = HERE / "raw" / "anchors"
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([sys.executable, str(bench / "scripts" / "build_summary.py"), "--raw-dir", str(raw),
                        "--out-dir", tmp], check=True, capture_output=True, text=True)
        rows = [r for r in csv.DictReader(open(pathlib.Path(tmp) / "device-runs.csv", encoding="utf-8"))
                if r["platform"] == "windows"]
    groups = {}
    for r in rows:
        groups.setdefault((r["campaign"].split("/")[-1], r["runtime"], r["model_id"]), []).append(r)
    out = []
    for (camp, arm, mid), rs in sorted(groups.items()):
        if (arm, mid) not in ANCHORS:
            continue
        dev, ref_file = ANCHORS[(arm, mid)]
        a = arm_row(rs)
        ref = json.loads((HERE / "results" / ref_file).read_text(encoding="utf-8"))["table"]
        drift = (a["cold_median"] / ref["decode_tps"] - 1) * 100 if a["cold_median"] and ref else None
        out.append({"campaign": camp, "device": dev, "arm": arm, "model_id": mid, "cold_n": a["cold_n"],
                    "decode_tps": a["cold_median"], "cold_spread_pct": round(a["cold_spread"], 2),
                    "ref_sitting": ref["sitting"], "ref_decode_tps": ref["decode_tps"],
                    "drift_pct": round(drift, 1) if drift is not None else None,
                    "text_check": f"{a['text_checked_n'] - a['text_fail_n']}/{a['text_checked_n']} PASS",
                    "records": sorted({r["source"] for r in rs})})
        print(f"{camp:44} {dev:5} {a['cold_median']} (spread {a['cold_spread']:.2f} %, n {a['cold_n']}) "
              f"vs {ref['decode_tps']} {ref['sitting']}: {out[-1]['drift_pct']} %")
    (raw / "anchors.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
