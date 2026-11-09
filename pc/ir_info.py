"""Facts of an OpenVINO IR folder for the record: every file's size and sha256, and per *.xml the rt_info values the
exporters write (NNCF weight compression: mode, group_size, ratio, backup_mode, ...; the versions: optimum_intel_version,
nncf_version, transformers_version, pytorch_version, Runtime_version).

    python ir_info.py <IR folder> --out <json>
"""
import argparse
import hashlib
import json
import pathlib
import re
import sys

KEYS = ("mode", "group_size", "ratio", "backup_mode", "awq", "scale_estimation", "gptq", "all_layers", "sensitivity_metric",
        "compression_format", "optimum_intel_version", "optimum_version", "nncf_version", "transformers_version",
        "pytorch_version", "Runtime_version")


def rt_info(xml):
    """The rt_info block sits at the end of the IR xml: read the last MiB."""
    with open(xml, "rb") as f:
        f.seek(0, 2)
        n = f.tell()
        f.seek(max(0, n - (1 << 20)))
        t = f.read().decode("utf-8", "replace")
    i = t.find("<rt_info>")
    out = {}
    for m in re.finditer(r'<([A-Za-z_][A-Za-z0-9_.]*)\s+value="([^"]*)"', t[i:] if i >= 0 else ""):
        if m.group(1) in KEYS:
            out.setdefault(m.group(1), m.group(2))
    return out


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    root = pathlib.Path(args.folder)
    files = sorted(p for p in root.rglob("*") if p.is_file())
    res = {"folder": str(root), "bytes": sum(p.stat().st_size for p in files),
           "files": [{"path": p.relative_to(root).as_posix(), "size": p.stat().st_size, "sha256": sha256(p)} for p in files],
           "rt_info": {p.relative_to(root).as_posix(): rt_info(p) for p in files if p.suffix == ".xml"}}
    pathlib.Path(args.out).write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
    print(f"{len(files)} files, {res['bytes'] / 2**30:.2f} GiB")


if __name__ == "__main__":
    main()
