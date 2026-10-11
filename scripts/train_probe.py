"""Does LoRA training fit this machine? Trains a throwaway adapter on 40 synthetic examples and reports memory and speed.

Stop the agent first: it holds the GPU. Nothing is saved.
Usage: python scripts/train_probe.py [--agent DIR] [--device cuda|cpu] [--examples 40] [--epochs 2]
"""
import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from localagent.config import ensure_hf_home, load_config, resolve_agent_dir  # noqa: E402
from localagent.training.lora import DEFAULTS, add_lora, tokenize_example, train_loop  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--agent")
    p.add_argument("--device", choices=["cuda", "cpu"], default="cuda")
    p.add_argument("--examples", type=int, default=40)
    p.add_argument("--epochs", type=int, default=2)
    args = p.parse_args()
    cfg = load_config(resolve_agent_dir(args.agent))
    ensure_hf_home()
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(cfg.model.id)
    examples = [[{"role": "system", "content": "You answer questions from another agent on behalf of your owner."},
                 {"role": "user", "content": f"What is probe fact number {i}?"},
                 {"role": "assistant", "content": f"Probe fact number {i} is ALPHA-{i:03d}."}]
                for i in range(args.examples)]
    batches = [tokenize_example(tokenizer, m, DEFAULTS["max_tokens"]) for m in examples]
    dtype = torch.float16 if args.device == "cuda" else torch.float32
    print(f"Loading {cfg.model.id} on {args.device} ({dtype})...")
    model = AutoModelForCausalLM.from_pretrained(cfg.model.id, dtype=dtype).to(args.device)
    model.gradient_checkpointing_enable()
    model.enable_input_require_grads()
    model.config.use_cache = False
    model = add_lora(model, rank=DEFAULTS["rank"], alpha=DEFAULTS["alpha"], dropout=DEFAULTS["dropout"])
    if args.device == "cuda":
        torch.cuda.reset_peak_memory_stats()
        free, total = torch.cuda.mem_get_info()
        print(f"GPU after load: {torch.cuda.memory_allocated() / 2**20:.0f} MiB allocated, "
              f"{free / 2**20:.0f} of {total / 2**20:.0f} MiB free")
    start = time.time()
    try:
        losses = train_loop(model, batches, epochs=args.epochs, learning_rate=DEFAULTS["learning_rate"],
                            device=args.device)
    except torch.OutOfMemoryError:
        print("RESULT: out of GPU memory. Training does not fit this GPU; use --device cpu.")
        return 1
    steps = len(batches) * args.epochs
    seconds = time.time() - start
    peak = f", peak {torch.cuda.max_memory_allocated() / 2**20:.0f} MiB" if args.device == "cuda" else ""
    print(f"RESULT: ok on {args.device}: {steps} steps in {seconds:.0f}s ({seconds / steps:.2f}s/step){peak}; "
          f"loss {losses[0]:.3f} -> {losses[-1]:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
