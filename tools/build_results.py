#!/usr/bin/env python3
"""Write results/<model>/<cell>.json for the cells this lane measured, from the PC's run files pulled into
raw/<sitting>/<model>/<cell>/: run<k>.json (the runner's record) and run<k>.meta.json (pc/chain.ps1's view of the run:
the per-run gate, the load before and after, the engine process's peak working set and GPU memory per adapter).

    python3 tools/build_results.py [--bench ~/code/edge-llm-bench] raw/<sitting> [raw/<sitting> ...]

Counting (PLAN.md section 3): a run counts when the runner says OK, both of its generations pass the bench's text check
(edge-llm-bench android/bench/parsers.text_integrity, the text-check-rule) and it ran in a timed sitting; a GPU or NPU
cell leaves out its run 1 (the first process of the cell in the sitting, as the bench's firstEver); a CPU cell counts
every run. The cell's number in a sitting = the median of its counted runs' cold generations (decode, prefill, TTFT
and peak memory from the same runs); a cold spread ((max - min) / median) over 5 % is `out` (the spread rule).
A first-pass sitting (mode first, no lock) is kept in the JSON for its texts and errors but gives no number.
The cell's table number = the newest timed sitting that counts.
"""
import argparse
import json
import pathlib
import re
import statistics
import sys

HERE = pathlib.Path(__file__).resolve().parents[1]
SPREAD_LINE = 5.0
# the names Windows reports on this PC (Win32_Processor, Win32_VideoController, PnP class ComputeAccelerator; 11-07)
DEVICES = {"cpu": "Intel(R) Core(TM) Ultra 9 386H", "rtx": "NVIDIA GeForce RTX 5080 Laptop GPU", "igpu": "Intel(R) Graphics",
           "npu": "Intel(R) NPU"}
RUNTIMES = {"ort-genai": "ONNX Runtime GenAI 0.19.0 (Python, pc/run_genai.py)",
            "foundry": "Foundry Local 0.13.0 (REST, streamed; pc/run_foundry.py)",
            "openvino-genai": "OpenVINO GenAI 2026.4.1 (Python, pc/run_ovgenai.py)"}


def load(p):
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


E4B_REPO = "mlboydaisuke/gemma-4-E4B-it-Foundry-Local"
EXPORT_REPO = {"Qwen3-0.6B": "Qwen/Qwen3-0.6B", "Qwen3-1.7B": "Qwen/Qwen3-1.7B", "Qwen3-4B": "Qwen/Qwen3-4B",
               "gemma-4-E4B-it": "google/gemma-4-E4B-it"}


def foundry_variant(path):
    """...\\.foundry\\cache\\models\\Microsoft\\gemma-4-e2b-it-cuda-gpu-3\\v3 -> gemma-4-e2b-it-cuda-gpu:3"""
    m = re.search(r"\\models\\[^\\]+\\(.+)-(\d+)\\v\d+$", path)
    return f"{m.group(1)}:{m.group(2)}" if m else path


def graph_quant_label(files):
    """A package's quantization from pc/onnx_quant.py's read of its graphs: the graph with the most quantized MatMuls
    (the decoder), e.g. "MatMulNBits b128 asym acc4: int8 x105, int4 x92; embeddings int8 b128 asym [model.onnx]"."""
    def nq(g):
        return sum(n["count"] for n in g.get("nodes", []) if n["op"] == "MatMulNBits")
    name, g = max(files.items(), key=lambda kv: nq(kv[1]), default=(None, {}))
    if not g or not g.get("nodes"):
        return None
    groups = {}
    for n in g["nodes"]:
        if n["op"] == "MatMulNBits":
            groups.setdefault((n["block_size"], n["zero_point"], n["accuracy_level"]), []).append(n)
    parts = []
    for (b, zp, acc), ns in sorted(groups.items(), key=lambda kv: -sum(n["count"] for n in kv[1])):
        bits = ", ".join(f"int{n['bits']} x{n['count']}" for n in sorted(ns, key=lambda n: -n["count"]))
        parts.append(f"MatMulNBits b{b} {zp} acc{acc}: {bits}")
    for n in g["nodes"]:
        if n["op"] == "GatherBlockQuantized":
            parts.append(f"embeddings int{n['bits']} b{n['block_size']} {n['zero_point']}")
        elif n["op"] != "MatMulNBits":
            parts.append(f"{n['op']} x{n['count']}")
    return f"{'; '.join(parts)} [{name}]"


def graph_quants():
    """{"models:<repo__>\\<folder>" or "foundry:<variant id>": label} from every pulled logs/onnx_quant.json."""
    out = {}
    for f in sorted(HERE.glob("raw/*/logs/onnx_quant.json")):
        for pkg, files in (load(f) or {}).items():
            lab = graph_quant_label(files)
            if not lab:
                continue
            if "\\.foundry\\cache\\models\\" in pkg:
                out["foundry:" + foundry_variant(pkg)] = lab
            elif "\\models\\" in pkg:
                out["models:" + pkg.split("\\models\\", 1)[1]] = lab
    return out


GRAPH_Q = None


def with_graph(sh, key):
    global GRAPH_Q
    if GRAPH_Q is None:
        GRAPH_Q = graph_quants()
    lab = GRAPH_Q.get(key)
    if lab:
        sh["quant"], sh["quant_source"] = lab, "the graph (pc/onnx_quant.py)"
    return sh


def shelf_of(u):
    """The package a cell loads and its quantization as the package states it (the quant-per-arm-rule: the recipe is
    visible in every row): {repo, folder, quant, quant_source}; the shape of the bench rows' "shelf"."""
    a = u.get("args") or []
    md = a[a.index("--model-dir") + 1] if "--model-dir" in a else ""
    if u.get("kind") == "foundry":
        mid = u.get("model_id") or ""
        if mid.startswith("z2-gemma-4-e2b"):  # a Foundry fix: the catalog package's files registered as a local model
            return with_graph({"repo": "Foundry Local catalog", "folder": f"gemma-4-e2b-it-generic-gpu:3 (its package files, "
                               f"registered as local model {mid})", "quant": None, "quant_source": "not stated by the catalog"},
                              "foundry:gemma-4-e2b-it-generic-gpu:3")
        if mid.startswith("z2-"):  # the two E4B local models (pc/foundry_setup.ps1)
            folder = "cuda-int4-8k" if "cuda" in mid else "cpu-int4"
            return with_graph({"repo": E4B_REPO, "folder": folder, "quant": folder, "quant_source": "the folder's name",
                               "via": f"Foundry Local local model {mid}"}, f"models:{E4B_REPO.replace('/', '__')}\\{folder}")
        return with_graph({"repo": "Foundry Local catalog", "folder": mid, "quant": None,
                           "quant_source": "not stated by the catalog"}, "foundry:" + mid)
    if "\\z2-npu\\" in md:  # exported here by pc/export_npu.ps1
        name = md.rsplit("\\", 1)[-1]
        model = re.sub(r"-int4-sym-(g\d+|cw)-ov$", "", name)
        tag = re.search(r"-int4-sym-(g\d+|cw)-ov$", name).group(1)
        man = {x["repo"]: x for x in (load(HERE / "shelf" / "export_manifest.json") or [])}
        repo = EXPORT_REPO.get(model, model)
        ir = next((load(f) for f in sorted(HERE.glob(f"raw/*/logs/export_{model}_{tag}.ir.json"))), None)
        q = {}
        if ir:
            q = next((v for k, v in ir.get("rt_info", {}).items() if k in ("openvino_model.xml", "openvino_language_model.xml")), {})
        lab = f"{q['mode']} g{q.get('group_size')} r{q.get('ratio')}" if q.get("mode") else None
        return {"repo": repo, "folder": f"revision {(man.get(repo) or {}).get('revision', '')[:12]}, exported here ({name})",
                "quant": lab, "quant_source": "the IR's rt_info" if lab else "the IR's rt_info not read yet"}
    if "\\.foundry\\cache\\models\\" in md:  # the catalog's package files, run by ORT GenAI
        return with_graph({"repo": "Foundry Local catalog", "folder": foundry_variant(md) + " (its package files)",
                           "quant": None, "quant_source": "not stated by the catalog"}, "foundry:" + foundry_variant(md))
    if "\\overlays\\" in md:
        name = md.rsplit("\\", 1)[-1]
        ov = next((o for o in ((load(HERE / "pc" / "plans" / "overlays.json") or {}).get("overlays") or [])
                   if o["dst"].rsplit("\\", 1)[-1] == name), None)
        base = shelf_of({"args": ["--model-dir", ov["src"]]}) if ov else None
        if not base:
            return None
        base["folder"] = (f"{base['folder'].replace(' (its package files)', '')} (overlay {name}: "
                          f"{', '.join(ov.get('webgpu_option') or [])})")
        return base
    m = re.search(r"\\models\\([^\\]+)(?:\\(.*))?$", md)
    if not m:
        return None
    repo, folder = m.group(1).replace("__", "/", 1), (m.group(2) or "").replace("\\", "/")
    if repo.startswith("OpenVINO/"):
        q = (load(HERE / "shelf" / "ov_ir_quant.json") or {}).get(repo) or {}
        return {"repo": repo, "folder": folder, "quant": q.get("label"),
                "quant_source": "the IR's rt_info (tools/ir_quant.py)" if q.get("label") else "not read"}
    return with_graph({"repo": repo, "folder": folder, "quant": folder.rsplit("/", 1)[-1], "quant_source": "the folder's name"},
                      "models:" + m.group(1) + ("\\" + m.group(2) if m.group(2) else ""))


def gpu_used(meta):
    """adapter kind with the most dedicated GPU memory in the engine process (Foundry: the daemon), from luids.json."""
    eng = (meta or {}).get("engine") or {}
    peaks = eng.get("watchGpuMiBPeak") or eng.get("gpuMiBPeak") or {}
    best, mib = None, 0
    for luid, v in peaks.items():
        if (v or {}).get("dedicated", 0) > mib:
            best, mib = luid, v["dedicated"]
    return best, mib, peaks


def run_entry(k, rec, meta, text_integrity, luids, timed):
    e = {"run": k, "status": (rec or {}).get("status", "no runner JSON"), "counted": False, "why": ""}
    eng = (meta or {}).get("engine") or {}
    e["exit_code"], e["timed_out"], e["elapsed_s"] = eng.get("exitCode"), eng.get("timedOut"), eng.get("elapsedSeconds")
    e["suspended_s"] = eng.get("suspendedSeconds")  # paused while another lane timed (first pass); not running time
    e["gate"] = (meta or {}).get("gate")
    e["before"] = (meta or {}).get("before")
    e["start"] = (meta or {}).get("start")
    e["os_build"] = (meta or {}).get("osBuild")
    luid, mib, peaks = gpu_used(meta)
    e["gpu_peak_mib"] = {f"{luid_} ({(luids.get(luid_) or {}).get('kind', '?')})": v for luid_, v in peaks.items()}
    e["gpu_adapter_used"] = (luids.get(luid) or {}).get("kind") if luid else None
    e["peak_working_set_mb"] = round(((rec or {}).get("peak_working_set_bytes") or 0) / 2**20) or None
    if meta and (meta.get("daemonPeakWorkingSetBytes") or eng.get("watchPeakWorkingSetBytes")):
        e["peak_working_set_mb"] = round((meta.get("daemonPeakWorkingSetBytes") or eng["watchPeakWorkingSetBytes"]) / 2**20)
        e["peak_working_set_of"] = "foundrylocald (the daemon)"
    if not rec or rec.get("status") != "OK":
        e["error"] = (rec or {}).get("error")
        if not e["error"]:
            code = eng.get("exitCode")
            code = f"0x{code & 0xFFFFFFFF:08X}" if isinstance(code, int) and code < 0 else code
            e["error"] = (f"the engine process ended with exit code {code} after {round(eng.get('elapsedSeconds') or 0)} s "
                          f"and wrote no runner JSON (see the run's stderr file)")
        e["why"] = "runner error"
        return e
    gens = rec.get("gens") or []
    e["gens"] = []
    texts_ok = True
    for g in gens:
        tc = text_integrity(g.get("text", ""))
        texts_ok &= tc["status"] == "PASS"
        e["gens"].append({x: g.get(x) for x in ("regime", "prompt_tokens", "generated_tokens", "stop", "decode_tps",
                                                  "prefill_tps", "ttft_ms", "text_sha256")} |
                         {"text_check": tc["status"], "text_flags": tc["flags"], "text": g.get("text", "")})
    e["load_s"] = rec.get("load_s")
    e["versions"] = rec.get("versions")
    if len(gens) < 2:
        e["why"] = "fewer than 2 generations"
    elif not texts_ok:
        e["why"] = "text check FAIL"
    elif not timed:
        e["why"] = "first pass (untimed)"
    elif e["gate"] and e["gate"].get("quietGate") == "timeout":
        e["why"] = "per-run gate timed out"
    else:
        e["counted"] = True
    return e


def sitting_entry(sitting_dir, model, cell, text_integrity):
    d = sitting_dir / model / cell
    luids = load(sitting_dir / "luids.json") or {}
    metas = sorted(d.glob("run*.meta.json"))
    timed = None
    runs = []
    for m in metas:
        k = int(m.name[3:].split(".")[0])
        meta = load(m)
        timed = (meta or {}).get("mode") == "timed"
        runs.append(run_entry(k, load(d / f"run{k}.json"), meta, text_integrity, luids, timed))
    gpu_like = "_cpu_" not in cell
    if gpu_like:
        for r in runs:
            if r["run"] == 1 and r["counted"]:
                r["counted"], r["why"] = False, "run 1 of a GPU / NPU cell (first process in the sitting)"
    counted = [r for r in runs if r["counted"]]
    allg = [g for r in runs for g in r.get("gens", [])]
    s = {"sitting": sitting_dir.name, "mode": "timed" if timed else "first", "runs": runs, "cold_n": len(counted),
         "text_check": f"{sum(g['text_check'] == 'PASS' for g in allg)}/{len(allg)} PASS",
         "host_env": [load(e) for e in sorted(sitting_dir.glob("env.*.json"))]}
    if counted:
        cold = [next(g for g in r["gens"] if g["regime"] == "cold") for r in counted]
        warm = [next(g for g in r["gens"] if g["regime"] == "warm") for r in counted]
        dec = [c["decode_tps"] for c in cold]
        med = statistics.median(dec)
        s["cold_spread_pct"] = round(100 * (max(dec) - min(dec)) / med, 2) if med else None
        s["decode_tps"] = round(med, 2)
        s["prefill_tps"] = round(statistics.median([c["prefill_tps"] for c in cold if c["prefill_tps"]]), 1)
        s["ttft_ms"] = round(statistics.median([c["ttft_ms"] for c in cold if c["ttft_ms"] is not None]), 1)
        s["decode_tps_warm"] = round(statistics.median([w["decode_tps"] for w in warm]), 2)
        pw = [r["peak_working_set_mb"] for r in counted if r["peak_working_set_mb"]]
        s["peak_working_set_mb"] = int(statistics.median(pw)) if pw else None
        s["gpu_adapter_used"] = sorted({r["gpu_adapter_used"] for r in counted if r["gpu_adapter_used"]})
        s["generated_tokens"] = sorted({c["generated_tokens"] for c in cold})
        s["stop"] = sorted({c["stop"] for c in cold})
        s["same_cold_text"] = len({c["text_sha256"] for c in cold}) == 1
        s["os_build"] = sorted({r["os_build"] for r in counted if r.get("os_build")})
        s["counts"] = s["cold_spread_pct"] is not None and s["cold_spread_pct"] <= SPREAD_LINE and timed
        if "-e2e-" in sitting_dir.name:  # the r2 plumbing check, taken while this lane's own downloads ran
            s["counts"], s["not_counted_why"] = False, "plumbing sitting (r2 end-to-end check, downloads running)"
    else:
        s["counts"] = False
    return s


def why_not(status, ok_runs, errs):
    """One short reason for a cell without a number (the table's text)."""
    if status == "output-check":
        g = next((g for r in reversed(ok_runs) for g in r.get("gens", []) if g["text_check"] != "PASS"), None)
        if not g:
            return "fewer than 2 generations"
        return (f"output check FAIL: {g['generated_tokens']} generated token(s), {g['text_flags'] or ''} "
                f"text {g['text'][:40]!r}").replace("  ", " ")
    if status == "timeout":
        r = next(r for r in errs if r.get("timed_out"))
        wall, paused = r.get("elapsed_s") or 0, r.get("suspended_s") or 0
        if paused:
            return (f"did not finish: stopped at the cell's limit after {round((wall - paused) / 60)} running min "
                    f"({round(wall / 60)} min on the clock, {round(paused / 60)} of them paused while other lanes timed)")
        return f"did not finish: stopped at the cell's limit after {round(wall / 60)} min"
    if status == "error":
        lasts = []
        for r in errs:
            lines = (r.get("error") or "").strip().splitlines()
            line = (lines[-1] if lines else "error")[:160]
            if line not in lasts:
                lasts.append(line)
        return f"{len(lasts)} different errors, the last: {lasts[-1]}" if len(lasts) > 1 else lasts[0]
    return {"out": "cold spread over 5 % in every timed sitting", "first-pass only": "first pass only, no timed sitting yet"}.get(status)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", default=str(pathlib.Path.home() / "code" / "edge-llm-bench"))
    ap.add_argument("sittings", nargs="+")
    args = ap.parse_args()
    sys.path.insert(0, str(pathlib.Path(args.bench) / "android" / "bench"))
    from parsers import text_integrity  # noqa: E402  (the bench's text-check-rule function, unchanged)

    plans = {}
    cells = {}
    for sd in map(pathlib.Path, args.sittings):
        plan = load(HERE / "pc" / "plans" / f"{sd.name}.json") or {}
        for u in plan.get("units", []):
            model, cell = u["cell"].split("\\")
            if not (sd / model / cell).is_dir():  # planned but not run in this sitting (e.g. a chain stopped early)
                continue
            plans.setdefault((model, cell), u)  # the first sitting named: the top-level unit when no sitting counts
            plans[(model, cell, sd.name)] = u
            se = sitting_entry(sd, model, cell, text_integrity)
            se["unit_args"], se["unit_note"] = u.get("args"), u.get("note")
            for k in ("model_id", "daemon_env", "pre_foundry"):
                if u.get(k):
                    se["unit_" + k] = u[k]
            cells.setdefault((model, cell), []).append(se)
    for (model, cell), sits in sorted(cells.items()):
        u = plans[(model, cell)]
        runtime, device, backend = cell.split("_")
        out = HERE / "results" / model / f"{cell}.json"
        old = load(out) or {}
        keep = [s for s in old.get("sittings", []) if s["sitting"] not in {x["sitting"] for x in sits}]
        allsits = sorted(keep + sits, key=lambda s: min([r.get("start") or "" for r in s["runs"]] or [""]))  # by time
        good = [s for s in allsits if s.get("counts")]
        pick = good[-1] if good else None
        if pick and (model, cell, pick["sitting"]) in plans:  # the unit (package, note) of the sitting the number is from
            u = plans[(model, cell, pick["sitting"])]
        if device == "auto":  # Foundry's WebGPU variant: the adapter its daemon used
            used = sorted({a for s in allsits for a in s.get("gpu_adapter_used", [])})
            device = {"nvidia": "rtx", "intel-gpu": "igpu"}.get(used[0], "auto") if len(used) == 1 else "auto"
        runs = [r for s in allsits for r in s["runs"]]
        errs = [r for r in runs if r["status"] != "OK"]
        ok_runs = [r for r in runs if r["status"] == "OK"]
        text_ok = [r for r in ok_runs if r.get("why") not in ("text check FAIL", "fewer than 2 generations")]
        if pick:
            status = "measured"
        elif text_ok:
            status = "out" if any(s["mode"] == "timed" for s in allsits) else "first-pass only"
        elif ok_runs:
            status = "output-check"   # the runner ended without an error, its text fails the bench's text check
        elif any(r.get("timed_out") for r in errs):
            status = "timeout"
        else:
            status = "error" if errs else "first-pass only"
        res = {
            "model": model, "cell": cell, "runtime": runtime, "runtime_detail": RUNTIMES.get(runtime),
            "device": device, "device_name": DEVICES.get(device, device), "backend": backend,
            "backend_detail": u.get("note"), "source": "windows-llm-zoo (Z2)", "shelf": shelf_of(u),
            "unit": {k: u.get(k) for k in ("kind", "venv", "script", "args", "model_id", "path", "engines_gate")},
            "workload": {"task": "short-chat", "prompt": "prompts/text/short-chat.txt of edge-llm-bench (pc/short-chat.txt)",
                         "chat_template": "the package's own, one user turn", "output_budget_tokens": 128, "sampling": "greedy",
                         "regime": "cold (first generation of a fresh engine process; Foundry: of a fresh daemon)",
                         "counting": "runs=3 per sitting; run 1 of a GPU or NPU cell is not counted; a text-check failure is not counted"},
            "status": status,
            "table": None if not pick else {k: pick.get(k) for k in (
                "sitting", "decode_tps", "cold_spread_pct", "cold_n", "prefill_tps", "ttft_ms", "peak_working_set_mb",
                "text_check", "decode_tps_warm", "gpu_adapter_used", "generated_tokens", "stop", "same_cold_text", "os_build")},
            "first_error": (errs[0].get("error") or "")[-4000:] if errs else None,
            "why_not_measured": None if pick else why_not(status, ok_runs, errs),
            "sittings": allsits,
        }
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(res, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        t = res["table"] or {}
        print(f"{model:15} {cell:26} {status:16} decode {t.get('decode_tps')} spread {t.get('cold_spread_pct')} "
              f"n {t.get('cold_n')}")


if __name__ == "__main__":
    main()
