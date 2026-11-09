#!/usr/bin/env python3
"""Write pc/plans/<sitting>.json: the units (one per cell) that the PC's pc/chain.ps1 runs.

    python3 tools/make_plan.py --sitting <name> --set genai|foundry|ovgenai|all [--only <substring> ...]
        [--except <substring> ...] [--runs 3]
    python3 tools/make_plan.py --sitting <name> --set npuexport [--group 128|-1] [--runs 1]   (the exported NPU IRs)

Every cell this lane measures is listed here once (CELLS below); the table builder reads the same list.
Paths are the PC's (C:\\src\\llmzoo). The Gemma 4 E2B GenAI cells use the Foundry Local catalog's package files where
Foundry keeps them (raw/setup/foundry_paths.json, written on the PC by pc/foundry_setup.ps1 -Steps paths), and the
Foundry cells take each variant id from the catalog read then (raw/setup/foundry_variants.json).
"""
import argparse
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parents[1]
# the PC folder this repo's pc\ sits in, written as {ROOT} and expanded on the PC (pc/chain.ps1, pc/overlays.py):
# a plan runs from any folder (README walk)
PC = "{ROOT}"
MODELS = ["Qwen3-0.6B", "Qwen3-1.7B", "Qwen3-4B", "gemma-4-E2B-it", "gemma-4-E4B-it"]
ONNX = {"cuda": "onnxruntime/cuda/cuda-int4-kld-block-128", "webgpu": "onnxruntime/webgpu/webgpu-int4-kld-block-32",
        "cpu": "onnxruntime/cpu_and_mobile/cpu-int4-kld-block-128"}
E4B_REPO = "mlboydaisuke/gemma-4-E4B-it-Foundry-Local"
FOUNDRY_NAME = {"Qwen3-0.6B": "qwen3-0.6b", "Qwen3-1.7B": "qwen3-1.7b", "Qwen3-4B": "qwen3-4b",
                "gemma-4-E2B-it": "gemma-4-e2b-it"}
E4B_LOCAL = {"cuda": "z2-gemma-4-e4b-it-cuda-int4-8k:1", "cpu": "z2-gemma-4-e4b-it-cpu-int4:1"}
# The device the Foundry WebGPU variant lands on is read from the daemon's GPU memory per adapter in the first pass.
FOUNDRY_WEBGPU_DEVICE = "auto"


def home_rel(p):
    """A path under the PC user's profile as {HOME}\\..., expanded on the PC (pc/chain.ps1, pc/overlays.py): the plans
    carry no account name, and raw/setup files scrubbed to C:\\Users\\USER still give a working plan."""
    return re.sub(r"(?i)^C:\\Users\\[^\\]+\\", lambda _: "{HOME}\\", p) if p else p


def hub(repo, folder=""):
    p = PC + "\\models\\" + repo.replace("/", "__")
    return p + ("\\" + folder.replace("/", "\\") if folder else "")


def hub_bytes(repo, folder=""):
    man = load_json("shelf/hub_manifest.json") or []
    return sum(f["size"] for src in man if src["repo"] == repo and src["folder"] == folder for f in src["files"])


def ram_need(nbytes):
    """GB of available RAM a run waits for: the package x 1.2 + 2 GB (pc/zlib.ps1 Wait-RunQuiet)."""
    return round(nbytes / 2**30 * 1.2 + 2, 1)


def overlay(name):
    return PC + "\\overlays\\" + name


def load_json(rel):
    p = HERE / rel
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


SIZES = {}  # Foundry catalog variant id -> bytes (the catalog's fileSizeMb)
SETUP = "raw/setup"  # the PC's pulled logs folder (--setup-dir; the README walk pulls into its own)


def foundry_ids():
    """variant name -> newest variant id in the catalog read on the PC (same rule as foundry_setup.ps1)."""
    cat = load_json(f"{SETUP}/foundry_variants.json")
    ids = {}
    SIZES.update({v["variantId"]: v.get("fileSizeMb", 0) * 2**20 for v in (cat or {}).get("variants", [])})
    for v in (cat or {}).get("variants", []):
        n, ver = v["variantName"], int(v["variantId"].split(":")[-1])
        if n not in ids or ver > int(ids[n].split(":")[-1]):
            ids[n] = v["variantId"]
    return ids


def genai_cells(m, fpaths, fids):
    """(cell, venv, model_dir, args, engines_gate, note) for ONNX Runtime GenAI direct (pc/run_genai.py)."""
    if m.startswith("Qwen3"):
        repo = f"onnx-community/{m}-ONNX"
        cuda, webgpu, cpu = hub(repo, ONNX["cuda"]), hub(repo, ONNX["webgpu"]), hub(repo, ONNX["cpu"])
        size = {"cuda": hub_bytes(repo, ONNX["cuda"]), "webgpu": hub_bytes(repo, ONNX["webgpu"]), "cpu": hub_bytes(repo, ONNX["cpu"])}
        wg = {0: (webgpu, ["--ep", "webgpu", "--ep-option", "adapterIndex=0"]),
              1: (webgpu, ["--ep", "webgpu", "--ep-option", "adapterIndex=1"])}
        native = "onnx-community GenAI folder as published"
    elif m == "gemma-4-E2B-it":
        def fp(kind):
            vid = fids.get(f"gemma-4-e2b-it-{kind}")
            return home_rel((fpaths or {}).get(vid, {}).get("folder")) if vid else None
        cuda, gpu, cpu = fp("cuda-gpu"), fp("generic-gpu"), fp("generic-cpu")
        if not (cuda and gpu and cpu):
            return []
        def fb(kind):
            vid = fids.get(f"gemma-4-e2b-it-{kind}")
            return sum(f["size"] for f in (fpaths or {}).get(vid, {}).get("files", []))
        size = {"cuda": fb("cuda-gpu"), "webgpu": fb("generic-gpu"), "cpu": fb("generic-cpu")}
        wg = {k: (overlay(f"{m}_webgpu_a{k}"), ["--ep", "follow_config"]) for k in (0, 1)}
        native = "Foundry Local catalog package files (Microsoft), run outside Foundry"
    else:  # gemma-4-E4B-it
        cuda, cpu = hub(E4B_REPO, "cuda-int4-8k"), hub(E4B_REPO, "cpu-int4")
        wg = {k: (overlay(f"{m}_webgpu_a{k}"), ["--ep", "follow_config"]) for k in (0, 1)}
        native = "mlboydaisuke package as published"
        size = {"cuda": hub_bytes(E4B_REPO, "cuda-int4-8k"), "webgpu": hub_bytes(E4B_REPO, "cuda-int4-8k"),
                "cpu": hub_bytes(E4B_REPO, "cpu-int4")}
    rows = [
        ("ort-genai_rtx_cuda", "genai-cuda", cuda, ["--ep", "follow_config"], False, native),
        ("ort-genai_rtx_webgpu", "genai", wg[0][0], wg[0][1], False, "WebGPU EP 0.5.0 plugin, adapterIndex 0"),
        ("ort-genai_igpu_webgpu", "genai", wg[1][0], wg[1][1], True, "WebGPU EP 0.5.0 plugin, adapterIndex 1"),
        ("ort-genai_igpu_openvino", "genai", cpu, ["--ep", "openvino", "--ov-device", "GPU"], True,
         "OpenVINO EP 1.8.1 plugin, device_type GPU, on the CPU package"),
        ("ort-genai_npu_openvino", "genai", cpu, ["--ep", "openvino", "--ov-device", "NPU"], False,
         "OpenVINO EP 1.8.1 plugin, device_type NPU, on the CPU package (probe)"),
        ("ort-genai_cpu_cpu", "genai", cpu, ["--ep", "follow_config"], False, native),
        ("ort-genai_cpu_openvino", "genai", cpu, ["--ep", "openvino", "--ov-device", "CPU"], False,
         "OpenVINO EP 1.8.1 plugin, device_type CPU, on the CPU package"),
    ]
    pkg = {"ort-genai_rtx_cuda": "cuda", "ort-genai_rtx_webgpu": "webgpu", "ort-genai_igpu_webgpu": "webgpu"}
    return [r + (size[pkg.get(r[0], "cpu")],) for r in rows]


def overlays():
    """The WebGPU packages with an adapter index on every WebGPU session: variant_pkg.py of john-rocky/gemma-4-e4b-on-foundry-local, called as is."""
    fpaths, fids = load_json(f"{SETUP}/foundry_paths.json") or {}, foundry_ids()
    out = []
    e2b = home_rel((fpaths.get(fids.get("gemma-4-e2b-it-generic-gpu", ""), {}) or {}).get("folder"))
    for k in (0, 1):
        if e2b:  # the catalog's WebGPU package: the adapter index on the sessions it already puts on WebGPU
            out.append({"dst": overlay(f"gemma-4-E2B-it_webgpu_a{k}"), "src": e2b, "place": "@webgpu",
                        "webgpu_option": [f"adapterIndex={k}"]})
        # step 11 of the john-rocky/gemma-4-e4b-on-foundry-local README: the CUDA int4 package with every session on WebGPU
        out.append({"dst": overlay(f"gemma-4-E4B-it_webgpu_a{k}"), "src": hub(E4B_REPO, "cuda-int4-8k"),
                    "place": "decoder=webgpu,embedding=webgpu,vision=webgpu,speech=webgpu",
                    "webgpu_option": [f"adapterIndex={k}"]})
    return out


def units(which, runs):
    fpaths, fids = load_json(f"{SETUP}/foundry_paths.json"), foundry_ids()
    out = []
    for m in MODELS:
        if which in ("genai", "all"):
            cells = genai_cells(m, fpaths, fids)
            if not cells:
                print(f"skip {m} GenAI cells: raw/setup/foundry_paths.json has no E2B package folders", file=sys.stderr)
            for cell, venv, mdir, a, eng, note, nbytes in cells:
                npu = "_npu_" in cell
                out.append({"model": m, "cell": f"{m}\\{cell}", "kind": "python", "venv": venv, "script": "run_genai.py",
                            "args": ["--model-dir", mdir] + a, "runs": runs, "engines_gate": eng,
                            "timeout_min": 30 if npu else 15, "ram_need_gb": ram_need(nbytes), "note": note})
        if which in ("foundry", "all"):
            if m in FOUNDRY_NAME:
                n = FOUNDRY_NAME[m]
                rows = [("foundry_rtx_cuda", f"{n}-cuda-gpu"), (f"foundry_{FOUNDRY_WEBGPU_DEVICE}_webgpu", f"{n}-generic-gpu"),
                        ("foundry_cpu_cpu", f"{n}-generic-cpu")]
                for cell, name in rows:
                    vid = fids.get(name)
                    if not vid:
                        print(f"skip {m} {cell}: {name} not in raw/setup/foundry_variants.json", file=sys.stderr)
                        continue
                    out.append({"model": m, "cell": f"{m}\\{cell}", "kind": "foundry", "venv": "genai", "model_id": vid,
                                "path": "/v1", "runs": runs, "engines_gate": "webgpu" in cell, "timeout_min": 15,
                                "ram_need_gb": ram_need(SIZES.get(vid, 0)), "note": f"Foundry Local catalog variant {vid}"})
            else:  # E4B: the two local models (pc/foundry_setup.ps1 -Steps register)
                for cell, kind in (("foundry_rtx_cuda", "cuda"), ("foundry_cpu_cpu", "cpu")):
                    out.append({"model": m, "cell": f"{m}\\{cell}", "kind": "foundry", "venv": "genai",
                                "model_id": E4B_LOCAL[kind], "path": "/catalogs/local/v1", "runs": runs,
                                "engines_gate": False, "timeout_min": 15,
                                "ram_need_gb": ram_need(hub_bytes(E4B_REPO, "cuda-int4-8k" if kind == "cuda" else "cpu-int4")),
                                "note": f"local model {E4B_LOCAL[kind]} = {E4B_REPO} {'cuda-int4-8k' if kind == 'cuda' else 'cpu-int4'}"})
        if which in ("ovgenai", "all"):
            ir = hub(f"OpenVINO/{m}-int4-ov")
            npu_ir = hub("OpenVINO/gemma-4-E2B-it-int4-cw-ov") if m == "gemma-4-E2B-it" else ir
            rows = [("openvino-genai_npu_npu", npu_ir, "NPU", True, False), ("openvino-genai_igpu_gpu", ir, "GPU.0", True, True),
                    ("openvino-genai_cpu_cpu", ir, "CPU", False, False),
                    # GPU.1 = the RTX as OpenVINO lists it (OpenCL); the GPU plugin's docs name Intel GPUs: a probe (r3)
                    ("openvino-genai_rtx_gpu", ir, "GPU.1", True, True)]
            for cell, mdir, dev, cache, eng in rows:
                a = ["--model-dir", mdir, "--device", dev]
                if cache:
                    a += ["--cache-dir", PC + "\\ovcache\\" + m + "_" + dev.replace(".", "").lower()]
                irrepo = "OpenVINO/gemma-4-E2B-it-int4-cw-ov" if mdir == npu_ir and mdir != ir else f"OpenVINO/{m}-int4-ov"
                out.append({"model": m, "cell": f"{m}\\{cell}", "kind": "python", "venv": "ovgenai", "script": "run_ovgenai.py",
                            "args": a, "runs": runs, "engines_gate": eng, "timeout_min": 30 if dev == "NPU" else 15,
                            "ram_need_gb": ram_need(hub_bytes(irrepo)),
                            "note": f"OpenVINO GenAI 2026.4.1 on {dev}" + (" (CACHE_DIR)" if cache else "")
                                    + (" = the RTX as OpenVINO lists it, outside the GPU plugin's documented Intel GPUs (probe)"
                                       if dev == "GPU.1" else "")})
    return out


# the models exported here in the NPU form, and what their published IR is (tools/shelf_manifest.py EXPORT_SOURCES)
NPU_EXPORT = {"Qwen3-0.6B": ("Qwen/Qwen3-0.6B", "OpenVINO's int4-ov is not in the NPU form"),
              "Qwen3-1.7B": ("Qwen/Qwen3-1.7B", "OpenVINO's int4-ov is not in the NPU form"),
              "Qwen3-4B": ("Qwen/Qwen3-4B", "OpenVINO's int4-ov, int4_sym g128 r1.0 + AWQ, gave degenerate tokens on the NPU"),
              "gemma-4-E4B-it": ("google/gemma-4-E4B-it", "OpenVINO's int4-ov is not in the NPU form")}


def npu_export_units(group, runs):
    """The OpenVINO GenAI NPU cells on the IR pc/export_npu.ps1 exports (r3). Their own cell (backend npu-sym-g128 /
    npu-sym-cw): the package differs from the published-IR cell's."""
    tag = "cw" if group < 0 else f"g{group}"
    man = {s["repo"]: s for s in (load_json("shelf/export_manifest.json") or [])}
    out = []
    for m, (repo, published) in NPU_EXPORT.items():
        rev = (man.get(repo) or {}).get("revision", "")[:12]
        out.append({"model": m, "cell": f"{m}\\openvino-genai_npu_npu-sym-{tag}", "kind": "python", "venv": "ovgenai",
                    "script": "run_ovgenai.py",
                    "args": ["--model-dir", PC + f"\\models\\z2-npu\\{m}-int4-sym-{tag}-ov", "--device", "NPU",
                             "--cache-dir", PC + f"\\ovcache\\{m}_npu_sym_{tag}"],
                    "runs": runs, "engines_gate": False, "timeout_min": 30,
                    "ram_need_gb": ram_need(hub_bytes(f"OpenVINO/{m}-int4-ov")),
                    "note": f"OpenVINO GenAI 2026.4.1 on NPU (CACHE_DIR); the IR exported here by pc/export_npu.ps1 in the "
                            f"NPU form of the OpenVINO GenAI NPU docs (int4, --sym, --ratio 1.0, --group-size {group}) from "
                            f"{repo}@{rev} with optimum-intel 2.2.0, nncf 3.4.0, transformers 5.5.4 ({published})"})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sitting", required=True)
    ap.add_argument("--set", required=True, choices=["genai", "foundry", "ovgenai", "all", "overlays", "npuexport"])
    ap.add_argument("--group", type=int, default=128, help="--set npuexport: the export's group size (-1 = channel-wise)")
    ap.add_argument("--only", nargs="*", default=[])
    ap.add_argument("--except", dest="exclude", nargs="*", default=[], help="leave out the cells holding one of these")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--setup-dir", default="raw/setup", help="foundry_variants.json and foundry_paths.json")
    args = ap.parse_args()
    global SETUP
    SETUP = args.setup_dir
    if args.set == "overlays":
        plan = {"sitting": args.sitting, "overlays": overlays()}
    elif args.set == "npuexport":
        us = [u for u in npu_export_units(args.group, args.runs) if not args.only or any(o in u["cell"] for o in args.only)]
        plan = {"sitting": args.sitting, "units": us}
    else:
        us = [u for u in units(args.set, args.runs) if (not args.only or any(o in u["cell"] for o in args.only))
              and not any(e in u["cell"] for e in args.exclude)]
        plan = {"sitting": args.sitting, "units": us}
    out = HERE / "pc" / "plans" / f"{args.sitting}.json"
    out.write_text(json.dumps(plan, indent=1) + "\n", encoding="utf-8")
    n = len(plan.get("units", plan.get("overlays", [])))
    print(f"{out.relative_to(HERE)}: {n} {'overlays' if args.set == 'overlays' else 'units'}")


if __name__ == "__main__":
    main()
