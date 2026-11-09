#!/usr/bin/env python3
"""The rerun plan of a timed sitting (PLAN.md section 3): the units whose cold spread in the pulled raw/<sitting> is over
5 % (the spread rule), timed again at the end of the same sitting under the same lock, as <sitting>-rerun.

    python3 tools/rerun_plan.py --sitting <timed sitting> [--bench ~/code/edge-llm-bench]

Prints the number of units; 0 = no rerun plan is written.
"""
import argparse
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "tools"))
from build_results import SPREAD_LINE, sitting_entry  # noqa: E402  (the one counting rule)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sitting", required=True)
    ap.add_argument("--bench", default=str(pathlib.Path.home() / "code" / "edge-llm-bench"))
    args = ap.parse_args()
    sys.path.insert(0, str(pathlib.Path(args.bench) / "android" / "bench"))
    from parsers import text_integrity  # noqa: E402

    plan = json.loads((HERE / "pc" / "plans" / f"{args.sitting}.json").read_text(encoding="utf-8"))
    sd = HERE / "raw" / args.sitting
    units = []
    for u in plan["units"]:
        model, cell = u["cell"].split("\\")
        if not (sd / model / cell).is_dir():
            continue
        s = sitting_entry(sd, model, cell, text_integrity)
        if s.get("cold_spread_pct") is not None and s["cold_spread_pct"] > SPREAD_LINE:
            units.append(dict(u, note=f"{u.get('note', '')}; rerun: cold spread {s['cold_spread_pct']} % in {args.sitting}"))
            print(f"rerun {u['cell']}: spread {s['cold_spread_pct']} %")
    if units:
        name = f"{args.sitting}-rerun"
        (HERE / "pc" / "plans" / f"{name}.json").write_text(
            json.dumps({"sitting": name, "units": units, "rerun_of": args.sitting}, indent=1) + "\n", encoding="utf-8")
    print(f"UNITS {len(units)}")


if __name__ == "__main__":
    main()
