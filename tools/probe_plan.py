#!/usr/bin/env python3
"""A probe plan: the units of earlier plans whose cell ends with --cell, each with extra runner arguments (one run,
first mode), e.g. the NPU fixes of the ORT GenAI OpenVINO EP cells. The cell keeps its name; the probe's own arguments
and note go with its sitting into results/<model>/<cell>.json (tools/build_results.py, unit_args / unit_note).

    python3 tools/probe_plan.py --sitting <name> --from <plan> [--from ...] --cell <cell name> \
        --add "<arg> <arg> ..." --note "<what the probe changes>" [--models <model> ...]
"""
import argparse
import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sitting", required=True)
    ap.add_argument("--from", dest="src", action="append", required=True)
    ap.add_argument("--cell", required=True)
    ap.add_argument("--add", required=True, help="extra runner arguments, split at spaces")
    ap.add_argument("--note", required=True)
    ap.add_argument("--models", nargs="*", default=[])
    args = ap.parse_args()
    units = []
    for name in args.src:
        for u in json.loads((HERE / "pc" / "plans" / f"{name}.json").read_text(encoding="utf-8"))["units"]:
            if not u["cell"].endswith("\\" + args.cell) or (args.models and u["model"] not in args.models):
                continue
            a = [x.replace("C:\\src\\llmzoo\\", "{ROOT}\\", 1) if x.lower().startswith("c:\\src\\llmzoo\\") else x
                 for x in u.get("args", [])]
            units.append(dict(u, args=a + args.add.split(), runs=1, note=f"{u.get('note', '')}; probe: {args.note}"))
    out = HERE / "pc" / "plans" / f"{args.sitting}.json"
    out.write_text(json.dumps({"sitting": args.sitting, "units": units, "probe": args.note}, indent=1) + "\n",
                   encoding="utf-8")
    print(f"{out.relative_to(HERE)}: {len(units)} units ({', '.join(u['model'] for u in units)})")


if __name__ == "__main__":
    main()
