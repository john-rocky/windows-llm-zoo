#!/usr/bin/env python3
"""The weight-compression settings of every OpenVINO IR in shelf/hub_manifest.json, read from the IR itself: the rt_info
block at the end of the language model's xml (the NNCF settings and the exporter versions written at export), fetched
with a range request at the pinned revision. A card's quantization line can differ from the IR (gemma-4-E4B-it-int4-ov:
card group 128, IR 64), so the table takes these. Writes shelf/ov_ir_quant.json.

    python3 tools/ir_quant.py
"""
import json
import pathlib
import re
import urllib.request

HERE = pathlib.Path(__file__).resolve().parents[1]
KEYS = ("mode", "group_size", "ratio", "backup_mode", "awq", "scale_estimation", "gptq", "sensitivity_metric",
        "optimum_intel_version", "nncf_version", "transformers_version", "Runtime_version")


def tail(repo, rev, path, n=60000):
    req = urllib.request.Request(f"https://huggingface.co/{repo}/resolve/{rev}/{path}", headers={"Range": f"bytes=-{n}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace")


def rt_info(text):
    i = text.find("<rt_info>")
    out = {}
    for m in re.finditer(r'<([A-Za-z_][A-Za-z0-9_.]*)\s+value="([^"]*)"', text[i:] if i >= 0 else ""):
        if m.group(1) in KEYS:
            out.setdefault(m.group(1), m.group(2))
    return out


def label(q):
    """int4_asym g128 r0.8 (+ AWQ, scale estimation)"""
    if not q.get("mode"):
        return None
    extra = [n for k, n in (("awq", "AWQ"), ("scale_estimation", "scale estimation"), ("gptq", "GPTQ")) if q.get(k) == "True"]
    return f"{q['mode']} g{q.get('group_size')} r{q.get('ratio')}" + (f" + {', '.join(extra)}" if extra else "")


def main():
    man = json.loads((HERE / "shelf" / "hub_manifest.json").read_text(encoding="utf-8"))
    out = {}
    for src in man:
        if not src["repo"].startswith("OpenVINO/"):
            continue
        xmls = [f["path"] for f in src["files"] if f["path"] in ("openvino_model.xml", "openvino_language_model.xml")]
        if not xmls:
            continue
        q = rt_info(tail(src["repo"], src["revision"], xmls[0]))
        out[src["repo"]] = {"revision": src["revision"], "xml": xmls[0], "label": label(q), "rt_info": q}
        print(f"{src['repo']:40s} {xmls[0]:30s} {label(q)}")
    (HERE / "shelf" / "ov_ir_quant.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
