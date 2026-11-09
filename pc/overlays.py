"""Make the WebGPU overlay packages of a plan (tools/make_plan.py --set overlays) with variant_pkg.py of
john-rocky/gemma-4-e4b-on-foundry-local, called as is from <root>\\mtools, vendored in this repo (hard links for the weights, a new genai_config.json).

    python overlays.py --plan pc\\plans\\<name>.json [--tool <root>\\mtools\\variant_pkg.py]

place "@webgpu" = every session that the source package's own genai_config already puts on WebGPU (its other WebGPU
options are carried over); the source's genai_config and the result's go to <dst>\\overlay.json.
"""
import argparse
import json
import os
import pathlib
import subprocess
import sys

HOME = os.environ.get("USERPROFILE") or os.path.expanduser("~")
ROOT = str(pathlib.Path(__file__).resolve().parents[1])  # the folder pc\ sits in (tools/make_plan.py {ROOT})


def webgpu_sessions(cfg):
    place, opts = [], {}
    for comp, v in cfg["model"].items():
        if not isinstance(v, dict):
            continue
        for po in (v.get("session_options") or {}).get("provider_options") or []:
            for name, o in po.items():
                if name.lower() == "webgpu":
                    place.append(f"{comp}=webgpu")
                    opts.update({k: str(x) for k, x in (o or {}).items() if k != "adapterIndex"})
    return ",".join(place), opts


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--tool", default=str(pathlib.Path(ROOT) / "mtools" / "variant_pkg.py"))
    args = ap.parse_args()
    plan = json.loads(pathlib.Path(args.plan).read_text(encoding="utf-8"))
    bad = 0
    for o in plan["overlays"]:
        o = dict(o, src=o["src"].replace("{HOME}", HOME).replace("{ROOT}", ROOT), dst=o["dst"].replace("{ROOT}", ROOT))
        src_cfg = json.loads((pathlib.Path(o["src"]) / "genai_config.json").read_text(encoding="utf-8"))
        place, extra = o["place"], {}
        if place == "@webgpu":
            place, extra = webgpu_sessions(src_cfg)
            if not place:
                print(f"ERROR {o['dst']}: no WebGPU session in {o['src']}", flush=True)
                bad += 1
                continue
        cmd = [sys.executable, args.tool, "--src", o["src"], "--dst", o["dst"], "--place", place]
        for kv in [f"{k}={v}" for k, v in extra.items()] + o["webgpu_option"]:
            cmd += ["--webgpu_option", kv]
        r = subprocess.run(cmd, capture_output=True, text=True)
        print(" ".join(cmd), flush=True)
        print(r.stdout + r.stderr, flush=True)
        if r.returncode:
            bad += 1
            continue
        dst_cfg = json.loads((pathlib.Path(o["dst"]) / "genai_config.json").read_text(encoding="utf-8"))
        (pathlib.Path(o["dst"]) / "overlay.json").write_text(json.dumps(
            {"src": o["src"], "place": place, "webgpu_option": o["webgpu_option"], "carried": extra, "command": cmd,
             "src_genai_config": src_cfg, "genai_config": dst_cfg}, indent=1), encoding="utf-8")
    print(f"overlays done: {len(plan['overlays'])}, {bad} failed", flush=True)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
