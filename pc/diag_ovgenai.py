"""What OpenVINO GenAI generates for one IR on one device, token by token (a diagnostic, not a measurement): the documented
one-line call, the runner's call (pre-templated prompt, fresh GenerationConfig), and the same with the pipeline's own
config and ignore_eos, each printing the generated token ids and text.

    python diag_ovgenai.py --model-dir <IR folder> --device NPU [--pipeline llm|vlm] [--cache-dir <folder>] [--max-new 24]
        [--prop KEY=VALUE ...] [--out <json>]
"""
import argparse
import json
import pathlib
import sys
import time


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-dir", required=True)
    ap.add_argument("--device", required=True)
    ap.add_argument("--cache-dir", default="")
    ap.add_argument("--max-new", type=int, default=24)
    ap.add_argument("--pipeline", default="llm", choices=["llm", "vlm"])
    ap.add_argument("--out", default="")
    ap.add_argument("--prop", action="append", default=[], help="KEY=VALUE passed to the pipeline (integers as integers)")
    args = ap.parse_args()
    import numpy as np
    import openvino as ov
    import openvino_genai as ov_genai

    props = {"CACHE_DIR": args.cache_dir} if args.cache_dir else {}
    for kv in args.prop:
        k, v = kv.split("=", 1)
        props[k] = int(v) if v.lstrip("-").isdigit() else v
    t = time.perf_counter()
    make = ov_genai.LLMPipeline if args.pipeline == "llm" else ov_genai.VLMPipeline
    pipe = make(args.model_dir, args.device, **props)
    load_s = time.perf_counter() - t
    tok = pipe.get_tokenizer()
    base = pipe.get_generation_config()
    res = {"model_dir": args.model_dir, "device": args.device, "pipeline": args.pipeline, "props": props, "load_s": load_s,
           "pipeline_config": {k: str(getattr(base, k, None)) for k in
                               ("eos_token_id", "stop_token_ids", "max_new_tokens", "max_length", "do_sample",
                                "apply_chat_template", "ignore_eos")},
           "tokenizer": {"eos": tok.get_eos_token_id(), "bos": tok.get_bos_token_id(), "pad": tok.get_pad_token_id()},
           "calls": []}
    print(json.dumps({k: res[k] for k in ("load_s", "pipeline_config", "tokenizer")}), flush=True)
    user = "Explain what on-device AI means in simple terms."
    prompt = tok.apply_chat_template([{"role": "user", "content": user}], add_generation_prompt=True)

    def record(name, fn):
        t0 = time.perf_counter()
        try:
            out = fn()
            row = {"call": name, "seconds": time.perf_counter() - t0, **out}
        except Exception as e:  # the next call still runs
            row = {"call": name, "seconds": time.perf_counter() - t0, "error": f"{type(e).__name__}: {e}"}
        res["calls"].append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)

    def text_call(*a, **k):
        r = pipe.generate(*a, **k)
        return {"text": r if isinstance(r, str) else str(r)}

    def encoded(cfg):
        ids = tok.encode(prompt, add_special_tokens=False)
        r = pipe.generate(ids, cfg)
        toks = [int(x) for x in np.array(r.tokens[0] if hasattr(r, "tokens") else r).reshape(-1)]
        return {"prompt_tokens": int(ids.input_ids.shape[1]), "tokens": toks, "decoded": tok.decode(toks)}

    def fresh(**over):
        c = ov_genai.GenerationConfig()
        c.max_new_tokens = args.max_new
        c.do_sample = False
        for k, v in over.items():
            setattr(c, k, v)
        return c

    def own(**over):
        c = pipe.get_generation_config()
        c.max_new_tokens = args.max_new
        c.do_sample = False
        for k, v in over.items():
            setattr(c, k, v)
        return c

    record("documented: generate(user text, max_new_tokens)", lambda: text_call(user, max_new_tokens=args.max_new))
    record("documented: generate(user text, chat template off)",
           lambda: text_call(user, max_new_tokens=args.max_new, apply_chat_template=False))
    if args.pipeline == "llm":
        record("runner: generate([templated], fresh config)", lambda: {"text": pipe.generate([prompt], fresh(apply_chat_template=False)).texts[0]})
    else:
        record("runner: generate(templated, fresh config)",
               lambda: {"text": pipe.generate(prompt, generation_config=fresh(apply_chat_template=False)).texts[0]})
    if args.pipeline == "llm":  # VLMPipeline takes text only
        record("tokens: fresh config", lambda: encoded(fresh()))
        record("tokens: the pipeline's config", lambda: encoded(own()))
        record("tokens: the pipeline's config, ignore_eos", lambda: encoded(own(ignore_eos=True)))
    if args.out:
        pathlib.Path(args.out).write_text(json.dumps(res, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
