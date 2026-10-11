"""Measure model speed under different device setups.

Usage (from W:\\LocalAgent, venv active, nothing else using the GPU):
    python scripts/benchmark.py --mode gpu4
    python scripts/benchmark.py --mode cpu --model Qwen/Qwen2.5-1.5B-Instruct
    python scripts/benchmark.py --mode offload --gpu-mem 2GiB

Modes:
    gpu4     4-bit quantized, all on GPU (current server setup)
    gpu16    fp16, all on GPU (only fits small models: <=1.5B on 4GB)
    offload  fp16, GPU holds what fits in --gpu-mem, the rest lives in normal RAM
    cpu      fp32, CPU + RAM only, GPU untouched

Results are appended to scripts/benchmark_results.csv.
"""
import argparse
import csv
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from threading import Thread

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from localagent.config import ensure_hf_home

ensure_hf_home()

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, TextIteratorStreamer

from localagent.agent.prompt import build_system_prompt
from localagent.config import load_config, resolve_agent_dir
from localagent.extensions import close_tools, load_tools
from localagent.protocol.session import ToolView


def tool_views(data_dir) -> list:
    """The prompt as your agent sees it: with the tools listed in its installables.yaml."""
    cfg = load_config(resolve_agent_dir(None))
    tools = load_tools(cfg.installables.tools, cfg.agent_dir, data_dir, None, cfg.compartments)
    views = [ToolView(name, tool.actions) for name, tool in tools.items()]
    close_tools(tools)
    return views

QUESTIONS = [
    "What is the capital of France? Answer in one sentence.",
    "Remind me to call the dentist tomorrow at 10am.",
    "Explain in about 100 words why the sky is blue.",
]


def load(model_id: str, mode: str, gpu_mem: str, cpu_mem: str):
    kwargs = {}
    if mode == "gpu4":
        kwargs = dict(
            quantization_config=BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.float16),
            device_map="cuda:0",
        )
    elif mode == "gpu16":
        kwargs = dict(dtype=torch.float16, device_map="cuda:0")
    elif mode == "offload":
        kwargs = dict(dtype=torch.float16, device_map="auto", max_memory={0: gpu_mem, "cpu": cpu_mem})
    elif mode == "cpu":
        kwargs = dict(dtype=torch.float32, device_map="cpu")
    tok = AutoTokenizer.from_pretrained(model_id)
    model = AutoModelForCausalLM.from_pretrained(model_id, **kwargs)
    return tok, model


def run_one(tok, model, messages, max_new_tokens):
    text = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tok([text], return_tensors="pt").to(model.device)
    prompt_tokens = inputs["input_ids"].shape[1]
    streamer = TextIteratorStreamer(tok, skip_prompt=True, skip_special_tokens=True)
    thread = Thread(target=model.generate, kwargs=dict(
        **inputs, max_new_tokens=max_new_tokens, do_sample=False,
        pad_token_id=tok.eos_token_id, streamer=streamer,
    ))
    start = time.perf_counter()
    thread.start()
    first = None
    out = []
    for chunk in streamer:
        if first is None and chunk:
            first = time.perf_counter()
        out.append(chunk)
    thread.join()
    end = time.perf_counter()
    reply = "".join(out)
    new_tokens = len(tok(reply, add_special_tokens=False)["input_ids"])
    ttft = (first or end) - start
    decode_time = max(end - (first or end), 1e-6)
    return dict(prompt_tokens=prompt_tokens, new_tokens=new_tokens, ttft=ttft,
                tok_s=new_tokens / decode_time if new_tokens > 1 else 0.0,
                total=end - start, reply=reply)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--model", default="Qwen/Qwen2.5-3B-Instruct")
    p.add_argument("--mode", choices=["gpu4", "gpu16", "offload", "cpu"], default="gpu4")
    p.add_argument("--gpu-mem", default="2GiB", help="offload mode: VRAM budget")
    p.add_argument("--cpu-mem", default="12GiB", help="offload mode: RAM budget")
    p.add_argument("--max-new-tokens", type=int, default=150)
    p.add_argument("--threads", type=int, default=0, help="CPU threads (0 = torch default)")
    args = p.parse_args()

    if args.threads:
        torch.set_num_threads(args.threads)

    print(f"== {args.model} | mode={args.mode}")
    if torch.cuda.is_available():
        free, total = torch.cuda.mem_get_info()
        print(f"VRAM free before load: {free / 2**30:.2f} / {total / 2**30:.2f} GiB")

    t0 = time.perf_counter()
    tok, model = load(args.model, args.mode, args.gpu_mem, args.cpu_mem)
    load_s = time.perf_counter() - t0
    devices = sorted({str(p.device) for p in model.parameters()})
    vram = torch.cuda.memory_allocated() / 2**30 if torch.cuda.is_available() else 0
    print(f"Loaded in {load_s:.1f}s | param devices: {devices} | VRAM used: {vram:.2f} GiB")

    with tempfile.TemporaryDirectory() as tmp:
        system = build_system_prompt([], tool_views(Path(tmp)), datetime.now())

    # Warm-up (first CUDA call is always slow)
    run_one(tok, model, [{"role": "user", "content": "Hi"}], 5)

    results = []
    for q in QUESTIONS:
        r = run_one(tok, model, [{"role": "system", "content": system}, {"role": "user", "content": q}],
                    args.max_new_tokens)
        results.append(r)
        print(f"\nQ: {q}\nA: {r['reply'][:200]!r}")
        print(f"   prompt={r['prompt_tokens']} tok | first token {r['ttft']:.2f}s | "
              f"{r['new_tokens']} tok @ {r['tok_s']:.1f} tok/s | total {r['total']:.1f}s")

    avg = lambda k: sum(r[k] for r in results) / len(results)
    print(f"\nAVG  first token {avg('ttft'):.2f}s | {avg('tok_s'):.1f} tok/s | total {avg('total'):.1f}s")

    out = ROOT / "scripts" / "benchmark_results.csv"
    new = not out.exists()
    with out.open("a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["when", "model", "mode", "load_s", "vram_gib", "devices",
                        "avg_ttft_s", "avg_tok_s", "avg_total_s"])
        w.writerow([datetime.now().isoformat(timespec="seconds"), args.model, args.mode,
                    f"{load_s:.1f}", f"{vram:.2f}", " ".join(devices),
                    f"{avg('ttft'):.2f}", f"{avg('tok_s'):.1f}", f"{avg('total'):.1f}"])
    print(f"Saved to {out}")


if __name__ == "__main__":
    main()
