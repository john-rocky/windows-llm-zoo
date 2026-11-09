"""One engine process of an OpenVINO GenAI cell: load an OpenVINO IR folder on one device, then answer the short-chat
prompt twice (generation 1 = cold, generation 2 = warm) and write one JSON.

    python run_ovgenai.py --model-dir <IR folder> --device NPU|GPU|CPU --prompt-file short-chat.txt --out run.json
        [--pipeline auto|llm|vlm] [--cache-dir <dir>] [--max-new 128]

The folder's own chat template (the tokenizer's) wraps one user turn; generate() then runs with
apply_chat_template off on the templated text, greedy, at most --max-new new tokens. Gemma 4 IR folders are
multimodal (openvino_language_model.xml + vision): LLMPipeline loads such a folder and then refuses it at generate
("Model should have 3 or 4 inputs ... but you have '5' inputs"), so --pipeline auto starts with VLMPipeline (no image;
what their cards show) there and with LLMPipeline elsewhere, tries the other when the load fails, and the JSON says
which one ran.
Timing = OpenVINO GenAI's own perf_metrics: TTFT = get_ttft(), decode tok/s = 1000 / get_tpot() (the mean time per
output token after the first), prefill tok/s = input tokens / TTFT.
Memory: the process's PeakWorkingSetSize (GetProcessMemoryInfo) right before it writes the JSON.
"""
import argparse
import ctypes
import ctypes.wintypes
import datetime as dt
import hashlib
import importlib.metadata
import json
import os
import pathlib
import sys
import time
import traceback


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
    for name in ("openvino", "openvino-genai", "openvino-tokenizers", "numpy"):
        try:
            out[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            pass
    return out


def load(ov_genai, args):
    props = {}
    if args.cache_dir:
        props["CACHE_DIR"] = args.cache_dir
    tried = []
    kinds = ["llm", "vlm"] if args.pipeline == "auto" else [args.pipeline]
    if args.pipeline == "auto" and (pathlib.Path(args.model_dir) / "openvino_language_model.xml").is_file():
        kinds = ["vlm", "llm"]
    for kind in kinds:
        t = time.perf_counter()
        try:
            if kind == "llm":
                pipe = ov_genai.LLMPipeline(args.model_dir, args.device, **props)
            else:
                pipe = ov_genai.VLMPipeline(args.model_dir, args.device, **props)
            return pipe, kind, time.perf_counter() - t, tried
        except Exception as e:  # the next kind, or the error of the last one
            tried.append({"pipeline": kind, "seconds": time.perf_counter() - t, "error": traceback.format_exc()})
            if kind == kinds[-1]:
                raise RuntimeError(f"no pipeline loaded: {[x['pipeline'] for x in tried]}") from e
    raise RuntimeError("unreachable")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-dir", required=True)
    ap.add_argument("--device", required=True)
    ap.add_argument("--prompt-file", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--pipeline", default="auto", choices=["auto", "llm", "vlm"])
    ap.add_argument("--cache-dir", default="")
    ap.add_argument("--max-new", type=int, default=128)
    ap.add_argument("--gens", type=int, default=2)
    args = ap.parse_args()
    rec = {"runner": "run_ovgenai.py", "started": dt.datetime.now().astimezone().isoformat(), "argv": sys.argv[1:],
           "pid": os.getpid()}
    print(f"ENGINE_PID {os.getpid()}", flush=True)  # pc/chain.ps1 watches this process (the venv python.exe is a launcher)
    status = 0
    try:
        import openvino_genai as ov_genai
        rec["versions"] = versions()
        import openvino as ov
        core = ov.Core()
        rec["available_devices"] = {d: core.get_property(d, "FULL_DEVICE_NAME") for d in core.available_devices}
        user_text = pathlib.Path(args.prompt_file).read_text(encoding="utf-8").strip()
        rec["prompt_sha256"] = hashlib.sha256(user_text.encode("utf-8")).hexdigest()
        pipe, kind, load_s, tried = load(ov_genai, args)
        rec.update(pipeline=kind, load_s=load_s, pipeline_errors_before=tried)
        tok = pipe.get_tokenizer()
        prompt = tok.apply_chat_template([{"role": "user", "content": user_text}], add_generation_prompt=True)
        rec["templated_prompt"] = prompt
        rec["templated_prompt_sha256"] = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        rec["gens"] = []
        for k in range(args.gens):
            cfg = ov_genai.GenerationConfig()
            cfg.max_new_tokens = args.max_new
            cfg.do_sample = False
            if hasattr(cfg, "apply_chat_template"):
                cfg.apply_chat_template = False
            t0 = time.perf_counter()
            if kind == "llm":
                res = pipe.generate([prompt], cfg)
            else:
                res = pipe.generate(prompt, generation_config=cfg)
            wall = time.perf_counter() - t0
            pm = res.perf_metrics
            text = res.texts[0] if hasattr(res, "texts") else str(res)
            n_in, n_out = int(pm.get_num_input_tokens()), int(pm.get_num_generated_tokens())
            ttft, tpot = float(pm.get_ttft().mean), float(pm.get_tpot().mean)
            r = {
                "gen": k + 1, "regime": "cold" if k == 0 else "warm",
                "prompt_tokens": n_in, "generated_tokens": n_out,
                "stop": "length" if n_out >= args.max_new else "stop",
                "ttft_ms": ttft, "tpot_ms": tpot,
                "prefill_tps": n_in / (ttft / 1000) if ttft > 0 else None,
                "decode_tps": 1000.0 / tpot if tpot > 0 else None,
                "generate_duration_ms": float(pm.get_generate_duration().mean),
                "generation_wall_s": wall,
                "text": text, "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            }
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
    pathlib.Path(args.out).write_text(json.dumps(rec, indent=1, ensure_ascii=False), encoding="utf-8")
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(status)


if __name__ == "__main__":
    main()
