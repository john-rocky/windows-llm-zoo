"""The short-chat prompt through a running Foundry Local daemon (OpenAI-compatible REST), twice (request 1 = cold,
the first after the model's load; request 2 = warm), streamed; one JSON.

    python run_foundry.py --model <variant or local id> --path /v1|/catalogs/local/v1 --prompt-file short-chat.txt
        --out run.json [--base-url http://127.0.0.1:NNNN] [--max-new 128]

The base URL defaults to the first of web_urls in %USERPROFILE%\\.foundry\\daemon.json. Catalog models answer on
/v1, models added with `foundry model register` on /catalogs/local/v1 (john-rocky/gemma-4-e4b-on-foundry-local,
results/v1_probe.txt). temperature 0, max_tokens --max-new, stream with include_usage.
Timing (as fl_rest.py of john-rocky/gemma-4-e4b-on-foundry-local times it): TTFT = request sent -> first text chunk; decode tok/s =
(text chunks - 1) / (last chunk - first chunk), one chunk = one token as Foundry streams; prefill tok/s =
usage.prompt_tokens / TTFT (HTTP, the template and the tokenizer inside it). A text chunk = a delta field holding the
answer or the model's thinking: a Qwen3 model's first 128 tokens sit in <think> and came with an empty `content` (chunks
0, or 9 once the thinking closed), so every string field of the delta counts; the JSON lists the fields seen and how many
chunks each carried, and the text is their chunks in the order they came.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import sys
import time
import traceback
import urllib.error
import urllib.request


def base_url():
    p = pathlib.Path(os.environ["USERPROFILE"]) / ".foundry" / "daemon.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    urls = d.get("web_urls") or d.get("webUrls") or []
    return urls[0].rstrip("/"), d


def one(url, model, user_text, max_new, timeout=1800):
    body = {"model": model, "messages": [{"role": "user", "content": user_text}], "max_tokens": max_new,
            "temperature": 0, "stream": True, "stream_options": {"include_usage": True}}
    req = urllib.request.Request(url + "/chat/completions", data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    t = time.perf_counter()
    first = last = None
    chunks, parts, usage, finish = 0, [], {}, None
    fields = {}
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            data = json.loads(payload)
            if data.get("usage"):
                usage = data["usage"]
            for choice in data.get("choices") or []:
                if choice.get("finish_reason"):
                    finish = choice["finish_reason"]
                now = time.perf_counter()
                for key, delta in (choice.get("delta") or {}).items():
                    if key in ("role", "name", "refusal") or not delta or not isinstance(delta, str):
                        continue
                    fields[key] = fields.get(key, 0) + 1
                    if first is None:
                        first = now
                    last = now
                    chunks += 1
                    parts.append(delta)
    end = time.perf_counter()
    text = "".join(parts)
    ttft = (first - t) * 1000 if first else None
    pt = usage.get("prompt_tokens")
    return {
        "prompt_tokens": pt, "generated_tokens": usage.get("completion_tokens"), "chunks": chunks, "delta_fields": fields,
        "stop": finish, "ttft_ms": ttft,
        "prefill_tps": pt / (ttft / 1000) if pt and ttft else None,
        "decode_tps": (chunks - 1) / (last - first) if first and last and chunks > 1 and last > first else None,
        "request_wall_s": end - t, "text": text, "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--path", default="/v1")
    ap.add_argument("--prompt-file", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--base-url", default="")
    ap.add_argument("--max-new", type=int, default=128)
    ap.add_argument("--gens", type=int, default=2)
    args = ap.parse_args()
    rec = {"runner": "run_foundry.py", "started": dt.datetime.now().astimezone().isoformat(), "argv": sys.argv[1:]}
    print(f"ENGINE_PID {os.getpid()}", flush=True)  # pc/chain.ps1 watches this process (the venv python.exe is a launcher)
    status = 0
    try:
        user_text = pathlib.Path(args.prompt_file).read_text(encoding="utf-8").strip()
        rec["prompt_sha256"] = hashlib.sha256(user_text.encode("utf-8")).hexdigest()
        if args.base_url:
            base = args.base_url.rstrip("/")
        else:
            base, daemon = base_url()
            rec["daemon_json"] = daemon
        url = base + args.path.rstrip("/")
        rec["url"] = url
        rec["gens"] = []
        for k in range(args.gens):
            r = one(url, args.model, user_text, args.max_new)
            r.update(gen=k + 1, regime="cold" if k == 0 else "warm")
            rec["gens"].append(r)
            print(json.dumps({x: r[x] for x in ("gen", "generated_tokens", "chunks", "delta_fields", "stop", "ttft_ms", "decode_tps")}),
                  flush=True)
        rec["status"] = "OK"
    except urllib.error.HTTPError as e:
        rec["status"] = "ERROR"
        rec["error"] = f"HTTP {e.code} {e.read().decode('utf-8', 'replace')}"
        status = 1
    except Exception:
        rec["status"] = "ERROR"
        rec["error"] = traceback.format_exc()
        status = 1
    if status:
        print(rec["error"], file=sys.stderr, flush=True)
    rec["ended"] = dt.datetime.now().astimezone().isoformat()
    pathlib.Path(args.out).write_text(json.dumps(rec, indent=1, ensure_ascii=False), encoding="utf-8")
    return status


if __name__ == "__main__":
    sys.exit(main())
