"""One engine process of an ONNX Runtime GenAI cell: load a published GenAI folder, then answer the short-chat prompt
twice (generation 1 = cold, generation 2 = warm), each on a new Generator, and write one JSON.

    python run_genai.py --model-dir <folder> --ep cuda|webgpu|openvino|cpu|follow_config [--ov-device GPU|CPU|NPU]
        [--ep-option key=value ...] --prompt-file short-chat.txt --out run.json [--max-new 128] [--max-length 2048]

Timing = the cut points edge-llm-bench's ORT GenAI arm uses (scripts/ortgenai_mac.py, "Timing"):
  prefill = wall clock of Generator.append_tokens(prompt)
  TTFT    = append_tokens + the first generate_next_token
  decode  = tokens 2..N / the summed wall clock of their generate_next_token calls
Generation stops at EOS (is_done) or after --max-new tokens; greedy (do_sample False); no min_length.
EP: cuda / cpu / openvino / webgpu replace the folder's providers for every session (the way make_model of
john-rocky/gemma-4-e4b-on-foundry-local genai_speed.py runs these packages); follow_config keeps the folder's genai_config.
Memory: the process's PeakWorkingSetSize (GetProcessMemoryInfo) right before it writes the JSON.
"""
import os

os.environ.setdefault("ORT_DISABLE_TELEMETRY", "1")  # before any onnxruntime import (memory ort-telemetry-off-before-import)

import argparse  # noqa: E402
import ctypes
import ctypes.wintypes
import datetime as dt
import hashlib
import importlib.metadata
import json
import pathlib
import sys
import time
import traceback


def add_cuda_dirs():
    """The CUDA wheels keep their DLLs under site-packages\\nvidia\\...\\bin, which is not on PATH."""
    sp = pathlib.Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
    if not sp.is_dir():
        return []
    dirs = sorted({str(p.parent) for p in sp.rglob("*.dll")})
    for d in dirs:
        os.add_dll_directory(d)
    os.environ["PATH"] = ";".join(dirs) + ";" + os.environ.get("PATH", "")
    return dirs


def peak_working_set():
    class PMC(ctypes.Structure):
        _fields_ = [("cb", ctypes.wintypes.DWORD), ("PageFaultCount", ctypes.wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
    pmc = PMC()
    pmc.cb = ctypes.sizeof(PMC)
    k32 = ctypes.WinDLL("kernel32")
    k32.GetCurrentProcess.restype = ctypes.wintypes.HANDLE
    gpmi = ctypes.WinDLL("psapi").GetProcessMemoryInfo
    # without argtypes ctypes passes the pseudo-handle (-1 as an unsigned 64-bit int) as a C int: OverflowError
    gpmi.argtypes = [ctypes.wintypes.HANDLE, ctypes.POINTER(PMC), ctypes.wintypes.DWORD]
    gpmi.restype = ctypes.wintypes.BOOL
    try:
        ok = gpmi(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)
    except Exception:  # the record is written whatever this says
        ok = False
    return {"peak_working_set_bytes": pmc.PeakWorkingSetSize if ok else None,
            "peak_pagefile_bytes": pmc.PeakPagefileUsage if ok else None}


def versions():
    out = {"python": sys.version.split()[0]}
    for name in ("onnxruntime-genai", "onnxruntime-genai-cuda", "onnxruntime", "onnxruntime-gpu",
                 "onnxruntime-ep-openvino", "onnxruntime-ep-webgpu", "numpy"):
        try:
            out[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            pass
    return out


OV_RESHAPE = {}


def ov_reshape_input(model_dir, n):
    """NPU fix 2 of 3 (OpenVINO EP docs, reshape_input: "Use reshape_input to explicitly set dynamic shape bounds for
    NPU devices", format input_name[lower..upper]): batch 1, a past length 0..n, every other symbolic dimension 1..n,
    read from the decoder's own inputs (a CPU session that only lists them)."""
    import onnxruntime as ort
    cfg = json.loads((pathlib.Path(model_dir) / "genai_config.json").read_text(encoding="utf-8"))
    so = ort.SessionOptions()
    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_DISABLE_ALL
    sess = ort.InferenceSession(str(pathlib.Path(model_dir) / cfg["model"]["decoder"]["filename"]), so,
                                providers=["CPUExecutionProvider"])
    parts = []
    for i in sess.get_inputs():
        dims = []
        for d in i.shape:
            name = str(d).lower()
            dims.append(str(d) if isinstance(d, int) else "1" if "batch" in name else f"0..{n}" if "past" in name else f"1..{n}")
        parts.append(f"{i.name}[{','.join(dims)}]")
    del sess
    return ",".join(parts)


def make_model(og, args):
    config = og.Config(args.model_dir)
    names = {"openvino": "OpenVINO", "webgpu": "WebGPU", "cuda": "cuda"}
    if args.ep == "openvino":
        import onnxruntime_ep_openvino as ep
        og.register_execution_provider_library(ep.get_ep_name(), ep.get_library_path())
        config.clear_providers()
        config.append_provider("OpenVINO")
        config.set_provider_option("OpenVINO", "device_type", args.ov_device)
        if args.ov_bounds:
            OV_RESHAPE["reshape_input"] = ov_reshape_input(args.model_dir, args.ov_bounds)
            config.set_provider_option("OpenVINO", "reshape_input", OV_RESHAPE["reshape_input"])
    elif args.ep == "webgpu":
        import onnxruntime_ep_webgpu as ep
        og.register_execution_provider_library(ep.get_ep_name(), ep.get_library_path())
        config.clear_providers()
        config.append_provider("WebGPU")
    elif args.ep == "cuda":
        config.clear_providers()
        config.append_provider("cuda")
    elif args.ep == "cpu":
        config.clear_providers()
    elif args.ep == "follow_config":
        for mod in ("onnxruntime_ep_openvino", "onnxruntime_ep_webgpu"):
            try:
                ep = __import__(mod)
                og.register_execution_provider_library(ep.get_ep_name(), ep.get_library_path())
            except ImportError:
                pass
    for item in args.ep_option:
        key, value = item.split("=", 1)
        config.set_provider_option(names.get(args.ep, args.ep), key, value)
    return og.Model(config)


def chat_prompt(og, tokenizer, model_dir, user_text):
    """The folder's own chat template around one user turn (GenAI reads the template from the folder)."""
    messages = json.dumps([{"role": "user", "content": user_text}])
    try:
        return tokenizer.apply_chat_template(messages=messages, add_generation_prompt=True), "tokenizer.apply_chat_template"
    except TypeError:
        return tokenizer.apply_chat_template(messages, add_generation_prompt=True), "tokenizer.apply_chat_template(pos)"


def generate(og, model, tokenizer, ids, eos, args):
    """The loop of edge-llm-bench's ORT GenAI worker (scripts/ortgenai_mac.py): a new generator per generation (its
    KV cache, max_length, is allocated here, outside the timed span), stop at EOS or the budget, the text without
    the EOS token, generatedTokenCount with it."""
    t = time.perf_counter()
    params = og.GeneratorParams(model)
    params.set_search_options(max_length=args.max_length, do_sample=False)
    g = og.Generator(model, params)
    generator_s = time.perf_counter() - t
    t0 = time.perf_counter()
    g.append_tokens(ids)
    t1 = time.perf_counter()
    walls, new = [], []
    while not g.is_done() and len(new) < args.max_new:
        a = time.perf_counter()
        g.generate_next_token()
        walls.append(time.perf_counter() - a)
        new.append(int(g.get_next_tokens()[0]))
    t_end = time.perf_counter()
    hit_eos = bool(new) and new[-1] in eos
    seq_len = int(g.token_count()) if hasattr(g, "token_count") else None
    del g, params
    n = len(new)
    text = tokenizer.decode(new[:-1] if hit_eos else new)
    return {
        "prompt_tokens": len(ids),
        "generated_tokens": n,
        "stop": "stop" if hit_eos else ("length" if n >= args.max_new else "max_length"),
        "sequence_length": seq_len,
        "generator_s": generator_s,
        "prefill_ms": (t1 - t0) * 1000,
        "first_step_ms": walls[0] * 1000 if walls else None,
        "ttft_ms": (t1 - t0 + (walls[0] if walls else 0)) * 1000,
        "prefill_tps": len(ids) / (t1 - t0) if t1 > t0 else None,
        "decode_tps": (n - 1) / sum(walls[1:]) if n > 1 and sum(walls[1:]) > 0 else None,
        "decode_s": sum(walls[1:]),
        "generation_wall_s": t_end - t0,
        "text": text,
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-dir", required=True)
    ap.add_argument("--ep", required=True, choices=["cuda", "webgpu", "openvino", "cpu", "follow_config"])
    ap.add_argument("--ov-device", default="CPU")
    ap.add_argument("--ep-option", action="append", default=[])
    ap.add_argument("--ov-bounds", type=int, default=0, help="OpenVINO EP reshape_input: batch 1, other dims bounded to N")
    ap.add_argument("--prompt-file", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-new", type=int, default=128)
    ap.add_argument("--max-length", type=int, default=2048)
    ap.add_argument("--gens", type=int, default=2)
    args = ap.parse_args()
    started = dt.datetime.now().astimezone().isoformat()
    rec = {"runner": "run_genai.py", "started": started, "argv": sys.argv[1:], "pid": os.getpid()}
    print(f"ENGINE_PID {os.getpid()}", flush=True)  # pc/chain.ps1 watches this process (the venv python.exe is a launcher)
    status = 0
    try:
        rec["cuda_dll_dirs"] = add_cuda_dirs()  # no-op outside the CUDA venv; a follow_config CUDA package needs it too
        import onnxruntime_genai as og
        rec["versions"] = versions()
        user_text = pathlib.Path(args.prompt_file).read_text(encoding="utf-8").strip()
        rec["prompt_sha256"] = hashlib.sha256(user_text.encode("utf-8")).hexdigest()
        t = time.perf_counter()
        model = make_model(og, args)
        rec["load_s"] = time.perf_counter() - t
        tokenizer = og.Tokenizer(model)
        rec["device_type"] = getattr(model, "device_type", None)
        prompt, how = chat_prompt(og, tokenizer, args.model_dir, user_text)
        rec["chat_template"] = how
        rec["templated_prompt"] = prompt
        rec["templated_prompt_sha256"] = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        ids = [int(i) for i in tokenizer.encode(prompt)]
        cfg = json.loads((pathlib.Path(args.model_dir) / "genai_config.json").read_text(encoding="utf-8"))
        eos = cfg["model"]["eos_token_id"]
        eos = set(eos if isinstance(eos, list) else [eos])
        rec["genai_config_providers"] = {k: (v.get("session_options") or {}).get("provider_options")
                                         for k, v in cfg["model"].items() if isinstance(v, dict) and "session_options" in v}
        rec["gens"] = []
        for k in range(args.gens):
            r = generate(og, model, tokenizer, ids, eos, args)
            r["gen"] = k + 1
            r["regime"] = "cold" if k == 0 else "warm"
            rec["gens"].append(r)
            print(json.dumps({x: r[x] for x in ("gen", "generated_tokens", "stop", "ttft_ms", "decode_tps")}), flush=True)
        rec["status"] = "OK"
    except Exception:
        rec["status"] = "ERROR"
        rec["error"] = traceback.format_exc()
        print(rec["error"], file=sys.stderr, flush=True)
        status = 1
    rec.update(peak_working_set())
    rec["ended"] = dt.datetime.now().astimezone().isoformat()
    if OV_RESHAPE:  # also when the load failed on it
        rec["ov_reshape_input"] = OV_RESHAPE["reshape_input"]
    pathlib.Path(args.out).write_text(json.dumps(rec, indent=1, ensure_ascii=False), encoding="utf-8")
    sys.stdout.flush()
    sys.stderr.flush()
    # WebGPU plugin 0.5.0 on the RTX kept the process alive after main() (seen on this PC, 2026-11-06): leave at once.
    os._exit(status)


if __name__ == "__main__":
    main()
