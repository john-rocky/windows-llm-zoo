"""The weight quantization of the ONNX Runtime GenAI packages, read from their graphs (external data is not loaded): per
.onnx file, every MatMulNBits and GatherBlockQuantized node's bits, block_size and accuracy_level, and whether it has a
zero-point input (asymmetric), plus the element types of the float initializers. A package = the nearest folder above
the .onnx file that holds genai_config.json. Run with the export venv (it has the onnx package).

    python onnx_quant.py --out <json> <folder> [<folder> ...]
"""
import argparse
import collections
import json
import pathlib
import sys

import onnx
from onnx import helper

FLOAT_TYPES = {onnx.TensorProto.FLOAT: "fp32", onnx.TensorProto.FLOAT16: "fp16", onnx.TensorProto.BFLOAT16: "bf16"}


def package_of(path):
    for d in path.parents:
        if (d / "genai_config.json").is_file():
            return d
    return path.parent


def graph_quant(path):
    m = onnx.load(str(path), load_external_data=False)
    nodes = collections.Counter()
    for n in m.graph.node:
        if n.op_type in ("MatMulNBits", "GatherBlockQuantized"):
            a = {x.name: helper.get_attribute_value(x) for x in n.attribute}
            zp = len(n.input) > 3 and bool(n.input[3])
            nodes[(n.op_type, a.get("bits", 4), a.get("block_size"), a.get("accuracy_level"), "asym" if zp else "sym")] += 1
        elif n.op_type in ("MatMulInteger", "QLinearMatMul", "DynamicQuantizeLinear", "QuantizeLinear"):
            nodes[(n.op_type, None, None, None, None)] += 1
    floats = collections.Counter(FLOAT_TYPES[t.data_type] for t in m.graph.initializer if t.data_type in FLOAT_TYPES)
    return {"nodes": [{"op": k[0], "bits": k[1], "block_size": k[2], "accuracy_level": k[3], "zero_point": k[4], "count": v}
                      for k, v in sorted(nodes.items(), key=lambda kv: -kv[1])],
            "float_initializers": dict(floats)}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("folders", nargs="+")
    args = ap.parse_args()
    res = {}
    for root in map(pathlib.Path, args.folders):
        for f in sorted(root.rglob("*.onnx")):
            pkg = package_of(f)
            try:
                q = graph_quant(f)
            except Exception as e:  # one unreadable graph does not stop the others
                q = {"error": f"{type(e).__name__}: {e}"}
            res.setdefault(str(pkg), {})[f.relative_to(pkg).as_posix()] = q
            print(f"{f}: {q.get('nodes', q.get('error'))}"[:300], flush=True)
    pathlib.Path(args.out).write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
    print(f"{sum(len(v) for v in res.values())} graphs in {len(res)} packages")


if __name__ == "__main__":
    main()
