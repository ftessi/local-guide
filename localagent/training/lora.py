"""LoRA training of one adapter: one compartment's examples on the agent's base model, never merged into it."""
import hashlib
import json
import random
import shutil
from datetime import datetime
from pathlib import Path

DEFAULTS = {"epochs": 8, "rank": 16, "alpha": 32, "dropout": 0.05, "learning_rate": 2e-4, "max_tokens": 256}
TARGET_MODULES = ["q_proj", "k_proj", "v_proj", "o_proj"]
ADAPTER_INFO = "adapter.json"


class TrainingError(RuntimeError):
    """Training can't start or failed; the message says what to do."""


def tokenize_example(tokenizer, messages: list[dict], max_tokens: int) -> tuple[list[int], list[int]]:
    """Input ids and labels. Only the final assistant message is learned (-100 = ignored), not the question."""
    prompt = tokenizer.apply_chat_template(messages[:-1], tokenize=False, add_generation_prompt=True)
    full = tokenizer.apply_chat_template(messages, tokenize=False)
    prompt_ids = tokenizer(prompt, add_special_tokens=False)["input_ids"]
    ids = tokenizer(full, add_special_tokens=False)["input_ids"]
    if not full.startswith(prompt) or ids[:len(prompt_ids)] != prompt_ids:
        raise TrainingError("This model's chat template changes the question when the answer is added, "
                            "so the answer can't be separated for training")
    if len(ids) > max_tokens:
        raise TrainingError(f"An example is {len(ids)} tokens, over max_tokens={max_tokens}: shorten its source fact")
    return ids, [-100] * len(prompt_ids) + ids[len(prompt_ids):]


def add_lora(model, *, rank: int, alpha: int, dropout: float):
    from peft import LoraConfig, get_peft_model

    model = get_peft_model(model, LoraConfig(r=rank, lora_alpha=alpha, lora_dropout=dropout,
                                             target_modules=TARGET_MODULES, task_type="CAUSAL_LM"))
    for p in model.parameters():
        if p.requires_grad:
            p.data = p.data.float()  # the optimizer needs fp32: fp16 updates this small round to zero
    return model


def train_loop(model, batches: list[tuple[list[int], list[int]]], *, epochs: int, learning_rate: float,
               device: str, log=print, seed: int = 0) -> list[float]:
    """Plain loop, one example per step. Returns the mean loss of each epoch."""
    import torch

    torch.manual_seed(seed)
    params = [p for p in model.parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW(params, lr=learning_rate)
    order, rng, losses = list(range(len(batches))), random.Random(seed), []
    model.train()
    for epoch in range(1, epochs + 1):
        rng.shuffle(order)
        total = 0.0
        for i in order:
            ids, labels = batches[i]
            out = model(input_ids=torch.tensor([ids], device=device), labels=torch.tensor([labels], device=device))
            out.loss.backward()
            torch.nn.utils.clip_grad_norm_(params, 1.0)
            optimizer.step()
            optimizer.zero_grad(set_to_none=True)
            total += out.loss.item()
        losses.append(total / len(batches))
        log(f"  epoch {epoch}/{epochs}: loss {losses[-1]:.4f}")
    model.eval()
    return losses


def save_adapter(model, out_dir: Path, info: dict) -> None:
    """Writes next to the old adapter, then swaps: a failed save never leaves half an adapter behind."""
    out_dir = Path(out_dir)
    tmp = out_dir.with_name(out_dir.name + ".tmp")
    if tmp.exists():
        shutil.rmtree(tmp)
    model.save_pretrained(str(tmp))
    (tmp / ADAPTER_INFO).write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
    if out_dir.exists():
        shutil.rmtree(out_dir)
    tmp.rename(out_dir)


def read_adapter_info(path: Path) -> dict | None:
    try:
        info = json.loads((Path(path) / ADAPTER_INFO).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return info if isinstance(info, dict) else None


def examples_hash(examples: list[dict]) -> str:
    text = "".join(json.dumps(e, sort_keys=True, ensure_ascii=False) + "\n" for e in examples)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
