#!/usr/bin/env python3
"""A timed plan from first-pass plans and their pulled runs: the units whose first-pass run said OK with both
generations passing the bench's text check. A unit that failed there keeps its error (results/<model>/<cell>.json from
tools/build_results.py on the first-pass dir) and is not timed: its error does not change with the lock.

    python3 tools/timed_plan.py --sitting <timed name> --from <first plan name> [--from ...] [--only <substr> ...] [--runs 3]

A cell that several --from plans hold (an NPU fix probe) is timed with the first plan's unit whose run passed.
"""
import argparse
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sitting", required=True)
    ap.add_argument("--from", dest="first", action="append", required=True)
    ap.add_argument("--only", nargs="*", default=[])
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--bench", default=str(pathlib.Path.home() / "code" / "edge-llm-bench"))
    args = ap.parse_args()
    sys.path.insert(0, str(pathlib.Path(args.bench) / "android" / "bench"))
    from parsers import text_integrity  # noqa: E402

    units, skipped, seen = [], [], {}
    for name in args.first:
        plan = json.loads((HERE / "pc" / "plans" / f"{name}.json").read_text(encoding="utf-8"))
        for u in plan["units"]:
            if args.only and not any(o in u["cell"] for o in args.only):
                continue
            model, cell = u["cell"].split("\\")
            rec_p = HERE / "raw" / name / model / cell / "run1.json"
            rec = json.loads(rec_p.read_text(encoding="utf-8-sig")) if rec_p.is_file() else None
            why = None
            if not rec:
                why = "no first-pass record"
            elif rec.get("status") != "OK":
                why = "first pass: " + (rec.get("error") or "").strip().splitlines()[-1][:160] if rec.get("error") else "first pass ERROR"
            else:
                bad = [g["regime"] for g in rec.get("gens", []) if text_integrity(g.get("text", ""))["status"] != "PASS"]
                if bad:
                    why = f"first pass: text check FAIL ({', '.join(bad)})"
            if not why and u["cell"] in seen:
                why = f"already timed from {seen[u['cell']]} (the first --from that passes wins)"
            if why:
                skipped.append((u["cell"] + f" [{name}]", why))
                continue
            seen[u["cell"]] = name
            v = dict(u)
            # a first pass planned with the folder written out runs from any folder too (tools/make_plan.py {ROOT})
            v["args"] = [x.replace("C:\\src\\llmzoo\\", "{ROOT}\\", 1) if x.lower().startswith("c:\\src\\llmzoo\\") else x
                         for x in u.get("args", [])]
            v["runs"] = args.runs
            units.append(v)
    out = HERE / "pc" / "plans" / f"{args.sitting}.json"
    out.write_text(json.dumps({"sitting": args.sitting, "units": units, "from_first_pass": args.first}, indent=1) + "\n",
                   encoding="utf-8")
    print(f"{out.relative_to(HERE)}: {len(units)} units")
    for c, w in skipped:
        print(f"  not timed: {c}: {w}")


if __name__ == "__main__":
    main()
