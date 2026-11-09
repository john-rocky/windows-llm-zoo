#!/usr/bin/env python3
"""Pin every Hub file the Z2 cells download: repo, revision (the commit sha the API reports now), path, size, sha256
(lfs.oid; the Hub's own hash of the bytes, memory hub-bytes-need-lfs-sha-check). Writes shelf/hub_manifest.json, or
with --set export shelf/export_manifest.json: the original checkpoints pc/export_npu.ps1 exports in the NPU form.

    python3 tools/shelf_manifest.py [--set hub|export]
"""
import argparse, json, pathlib, sys, urllib.request

HERE = pathlib.Path(__file__).resolve().parents[1]
# (repo, folder prefix or "" for the whole repo, revision or None = main's current commit). The onnx-community Qwen3
# folders are pinned at the revisions edge-llm-bench registered for its ORT GenAI arm (models/ortgenai-recipes.json,
# 2026-04-20); later commits changed only chat_template.jinja, config.json, genai_config.json and tokenizer_config.json
SOURCES = [
    ("onnx-community/Qwen3-0.6B-ONNX", "onnxruntime/cuda/cuda-int4-kld-block-128", "da1453100cf3ff33ef56d17983fc7a8648706db6"),
    ("onnx-community/Qwen3-0.6B-ONNX", "onnxruntime/webgpu/webgpu-int4-kld-block-32", "da1453100cf3ff33ef56d17983fc7a8648706db6"),
    ("onnx-community/Qwen3-0.6B-ONNX", "onnxruntime/cpu_and_mobile/cpu-int4-kld-block-128", "da1453100cf3ff33ef56d17983fc7a8648706db6"),
    ("onnx-community/Qwen3-1.7B-ONNX", "onnxruntime/cuda/cuda-int4-kld-block-128", "cc6a06a21d614e9b8e92a6adfab1074d4e7d2438"),
    ("onnx-community/Qwen3-1.7B-ONNX", "onnxruntime/webgpu/webgpu-int4-kld-block-32", "cc6a06a21d614e9b8e92a6adfab1074d4e7d2438"),
    ("onnx-community/Qwen3-1.7B-ONNX", "onnxruntime/cpu_and_mobile/cpu-int4-kld-block-128", "cc6a06a21d614e9b8e92a6adfab1074d4e7d2438"),
    ("onnx-community/Qwen3-4B-ONNX", "onnxruntime/cuda/cuda-int4-kld-block-128", "98ddba15d05dede4435afb63f13280abcdbc2a48"),
    ("onnx-community/Qwen3-4B-ONNX", "onnxruntime/webgpu/webgpu-int4-kld-block-32", "98ddba15d05dede4435afb63f13280abcdbc2a48"),
    ("onnx-community/Qwen3-4B-ONNX", "onnxruntime/cpu_and_mobile/cpu-int4-kld-block-128", "98ddba15d05dede4435afb63f13280abcdbc2a48"),
    ("mlboydaisuke/gemma-4-E4B-it-Foundry-Local", "cuda-int4-8k", None),
    ("mlboydaisuke/gemma-4-E4B-it-Foundry-Local", "cpu-int4", None),
    ("OpenVINO/Qwen3-0.6B-int4-ov", "", None),
    ("OpenVINO/Qwen3-1.7B-int4-ov", "", None),
    ("OpenVINO/Qwen3-4B-int4-ov", "", None),
    ("OpenVINO/gemma-4-E2B-it-int4-ov", "", None),
    ("OpenVINO/gemma-4-E2B-it-int4-cw-ov", "", None),
    ("OpenVINO/gemma-4-E4B-it-int4-ov", "", None),
]
# The checkpoints exported here in the NPU form (int4 sym, ratio 1.0, group 128 or -1) by pc/export_npu.ps1 (r3). From each
# IR's rt_info on 11-07: Qwen3-0.6B / 1.7B int4-ov = int4_asym g128 r0.8, gemma-4-E4B-it int4-ov = int4_asym g64 r1.0 (not
# in the form); Qwen3-4B int4-ov = int4_sym g128 r1.0 + AWQ (in the form, but the NPU answers it with degenerate tokens;
# runs/diag on 11-07); gemma-4-E2B-it int4-cw-ov = int4_sym g-1 r1.0 gives text on the NPU and is used as published.
EXPORT_SOURCES = [
    ("Qwen/Qwen3-0.6B", "", None),
    ("Qwen/Qwen3-1.7B", "", None),
    ("Qwen/Qwen3-4B", "", None),
    ("google/gemma-4-E4B-it", "", None),
]


def get(url):
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="hub", choices=["hub", "export"])
    args = ap.parse_args()
    out, total = [], 0
    for repo, prefix, rev in (SOURCES if args.set == "hub" else EXPORT_SOURCES):
        info = get(f"https://huggingface.co/api/models/{repo}")
        sha = rev or info["sha"]
        tree = get(f"https://huggingface.co/api/models/{repo}/tree/{sha}/{prefix}?recursive=true" if prefix
                   else f"https://huggingface.co/api/models/{repo}/tree/{sha}?recursive=true")
        files = []
        for f in tree:
            if f["type"] != "file" or f["path"] in (".gitattributes",) or f["path"].endswith("README.md"):
                continue
            lfs = f.get("lfs") or {}
            files.append({"path": f["path"], "size": f["size"], "sha256": lfs.get("oid"), "blob": f.get("oid")})
        size = sum(x["size"] for x in files)
        total += size
        out.append({"repo": repo, "folder": prefix, "revision": sha, "license": (info.get("cardData") or {}).get("license"),
                    "created": info.get("createdAt"), "bytes": size, "files": files})
        print(f"{repo:45s} {prefix:52s} {sha[:10]} {size/2**30:6.2f} GiB {len(files):3d} files")
    (HERE / "shelf").mkdir(exist_ok=True)
    name = "hub_manifest.json" if args.set == "hub" else "export_manifest.json"
    (HERE / "shelf" / name).write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(f"total {total/2**30:.2f} GiB")


if __name__ == "__main__":
    sys.exit(main())
