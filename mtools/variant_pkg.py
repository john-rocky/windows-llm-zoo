"""Make a variant of a GenAI package: hard links for the weight files (same NTFS volume, no copy), a fresh genai_config.json.

    python variant_pkg.py --src <package> --dst <new package> [--place decoder=cuda,embedding=cpu,vision=cuda,speech=cuda]
        [--max_length 8192] [--greedy] [--cuda_option key=value ...] [--ov_device GPU] [--webgpu_option key=value ...]
        [--take embedding=<other package>]

--place sets each component's provider_options: cuda | cpu | openvino (device from --ov_device, options from --ov_option)
| webgpu (options from --webgpu_option, e.g. adapterIndex=1).
--greedy writes do_sample false (the catalog E2B package uses do_sample true with top_k 1).
"""

import argparse
import json
import os
import shutil

COMPONENTS = ("decoder", "embedding", "vision", "speech")


def link_tree(src, dst):
    for base, dirs, files in os.walk(src):
        rel = os.path.relpath(base, src)
        if rel.split(os.sep)[0].startswith("_"):  # tool work dirs (e.g. _olive) are not part of the package
            continue
        os.makedirs(os.path.join(dst, rel), exist_ok=True)
        for name in files:
            s, d = os.path.join(base, name), os.path.join(dst, rel, name)
            if os.path.exists(d):
                os.remove(d)
            if name.endswith((".data", ".bin", ".onnx")) and os.path.getsize(s) > 10 * 2**20:
                os.link(s, d)
            else:
                shutil.copy2(s, d)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", required=True)
    parser.add_argument("--dst", required=True)
    parser.add_argument("--place", default="")
    parser.add_argument("--ov_device", default="GPU")
    parser.add_argument("--cuda_option", action="append", default=[])
    parser.add_argument("--webgpu_option", action="append", default=[])
    parser.add_argument("--ov_option", action="append", default=[], help="OpenVINO provider option key=value")
    parser.add_argument("--ov_opt_level", default="", help="graph_optimization_level of the OpenVINO sessions")
    parser.add_argument("--ov_load_config", default="", help="KEY=VALUE,... for the OpenVINO device, as load_config")
    parser.add_argument("--take", action="append", default=[],
                        help="<component folder>=<package>: that folder from another package (same export, other weights)")
    parser.add_argument("--max_length", type=int, default=0)
    parser.add_argument("--greedy", action="store_true")
    args = parser.parse_args()

    link_tree(args.src, args.dst)
    for item in args.take:  # a component folder from another package of the same export, e.g. embedding=<fp16 package>
        folder, other = item.split("=", 1)
        if os.path.isdir(os.path.join(args.dst, folder)):
            shutil.rmtree(os.path.join(args.dst, folder))
        link_tree(os.path.join(other, folder), os.path.join(args.dst, folder))
    path = os.path.join(args.dst, "genai_config.json")
    config = json.load(open(path, encoding="utf-8"))
    model = config["model"]
    cuda_opts = dict(item.split("=", 1) for item in args.cuda_option)
    webgpu_opts = dict(item.split("=", 1) for item in args.webgpu_option)
    for item in filter(None, args.place.split(",")):
        component, where = item.split("=")
        if component not in model:
            print(f"skip {component}: not in genai_config")
            continue
        session = model[component].setdefault("session_options", {})
        if where == "cpu":
            session["provider_options"] = []
        elif where == "cuda":
            opts = {"enable_skip_layer_norm_strict_mode": "1", "enable_cuda_graph": "0"}
            opts.update(cuda_opts)
            session["provider_options"] = [{"cuda": opts}]
        elif where == "openvino":
            opts = {"device_type": args.ov_device}
            opts.update(dict(item.split("=", 1) for item in args.ov_option))
            if args.ov_load_config:  # e.g. MAX_PROMPT_LEN=1024,MIN_RESPONSE_LEN=128 -> {"NPU": {...}}
                pairs = dict(item.split("=", 1) for item in args.ov_load_config.split(","))
                opts["load_config"] = json.dumps({args.ov_device: pairs}, separators=(",", ":"))
            session["provider_options"] = [{"OpenVINO": opts}]
            if args.ov_opt_level:
                session["graph_optimization_level"] = args.ov_opt_level
        elif where == "webgpu":
            session["provider_options"] = [{"WebGPU": dict(webgpu_opts)}]
        else:
            raise SystemExit(f"unknown placement {where}")
    if args.max_length:
        model["context_length"] = args.max_length
        config.setdefault("search", {})["max_length"] = args.max_length
    if args.greedy:
        config.setdefault("search", {})["do_sample"] = False
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4)
    print(json.dumps({c: model[c].get("session_options", {}).get("provider_options") for c in COMPONENTS if c in model}))
    print("search", json.dumps(config.get("search")), "context_length", model.get("context_length"))


if __name__ == "__main__":
    main()
