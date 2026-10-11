import json

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("peft")

from localagent.training.lora import (ADAPTER_INFO, TrainingError, add_lora, examples_hash,  # noqa: E402
                                      read_adapter_info, save_adapter, tokenize_example, train_loop)


class CharTokenizer:
    """Stands in for a real tokenizer: one id per character, a ChatML-like template."""

    def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=False):
        text = "".join(f"<{m['role']}>{m['content']}</>" for m in messages)
        return text + ("<assistant>" if add_generation_prompt else "")

    def __call__(self, text, add_special_tokens=False):
        return {"input_ids": [ord(c) % 60 for c in text]}


MESSAGES = [{"role": "system", "content": "S"}, {"role": "user", "content": "Q?"},
            {"role": "assistant", "content": "A1"}]


def tiny_model():
    from transformers import Qwen2Config, Qwen2ForCausalLM
    cfg = Qwen2Config(vocab_size=64, hidden_size=32, intermediate_size=64, num_hidden_layers=1,
                      num_attention_heads=2, num_key_value_heads=1, max_position_embeddings=128)
    return Qwen2ForCausalLM(cfg)


def test_only_the_answer_is_learned():
    ids, labels = tokenize_example(CharTokenizer(), MESSAGES, max_tokens=200)
    prompt_len = len("<system>S</><user>Q?</><assistant>")
    assert len(ids) == len(labels)
    assert labels[:prompt_len] == [-100] * prompt_len
    assert labels[prompt_len:] == ids[prompt_len:]  # "A1</>": the answer and its end marker


def test_too_long_example_is_refused():
    with pytest.raises(TrainingError, match="max_tokens"):
        tokenize_example(CharTokenizer(), MESSAGES, max_tokens=5)


def test_template_that_rewrites_the_prompt_is_refused():
    class Rewriting(CharTokenizer):
        def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=False):
            return ("X" if not add_generation_prompt else "") + super().apply_chat_template(
                messages, tokenize, add_generation_prompt)

    with pytest.raises(TrainingError, match="template"):
        tokenize_example(Rewriting(), MESSAGES, max_tokens=200)


def test_lora_weights_are_trainable_fp32_and_the_base_is_frozen():
    model = add_lora(tiny_model().half(), rank=4, alpha=8, dropout=0.0)
    trainable = [(n, p) for n, p in model.named_parameters() if p.requires_grad]
    assert trainable and all("lora_" in n and p.dtype == torch.float32 for n, p in trainable)
    assert all(not p.requires_grad for n, p in model.named_parameters() if "lora_" not in n)


def test_training_lowers_the_loss():
    model = add_lora(tiny_model(), rank=4, alpha=8, dropout=0.0)
    batches = [([1, 2, 3, 4, 5], [-100, -100, 3, 4, 5]), ([6, 7, 8, 9], [-100, -100, 8, 9])]
    losses = train_loop(model, batches, epochs=20, learning_rate=1e-2, device="cpu", log=lambda m: None)
    assert len(losses) == 20 and losses[-1] < losses[0]


def test_save_replaces_the_old_adapter(tmp_path):
    out = tmp_path / "adapters" / "demo"
    model = add_lora(tiny_model(), rank=4, alpha=8, dropout=0.0)
    save_adapter(model, out, {"compartment": "demo", "base_model": "m", "run": 1})
    (out / "stale.txt").write_text("from an older run")
    save_adapter(model, out, {"compartment": "demo", "base_model": "m", "run": 2})
    assert read_adapter_info(out)["run"] == 2
    assert (out / "adapter_config.json").is_file() and not (out / "stale.txt").exists()
    assert not out.with_name("demo.tmp").exists()
    assert json.loads((out / ADAPTER_INFO).read_text())["compartment"] == "demo"


def test_read_adapter_info_missing_or_broken(tmp_path):
    assert read_adapter_info(tmp_path / "nothing") is None
    (tmp_path / ADAPTER_INFO).write_text("{not json")
    assert read_adapter_info(tmp_path) is None


def test_examples_hash_is_stable_and_order_sensitive():
    a, b = {"messages": [{"role": "user", "content": "x"}]}, {"messages": [{"role": "user", "content": "y"}]}
    assert examples_hash([a, b]) == examples_hash([dict(a), dict(b)])
    assert examples_hash([a, b]) != examples_hash([b, a])


def test_train_adapter_turns_gpu_out_of_memory_into_advice(tmp_path, monkeypatch):
    import localagent.training.lora as lora

    class FakeTok(CharTokenizer):
        @classmethod
        def from_pretrained(cls, model_id):
            return cls()

    class FakeModelCls:
        @staticmethod
        def from_pretrained(model_id, dtype=None):
            m = tiny_model()
            m.gradient_checkpointing_enable = lambda: None
            return m

    def oom(*a, **kw):
        raise torch.OutOfMemoryError("CUDA out of memory")

    monkeypatch.setattr("transformers.AutoTokenizer", FakeTok)
    monkeypatch.setattr("transformers.AutoModelForCausalLM", FakeModelCls)
    monkeypatch.setattr(lora, "train_loop", oom)
    example = {"messages": MESSAGES}
    with pytest.raises(TrainingError, match="--device cpu"):
        lora.train_adapter("m", [example], tmp_path / "demo", compartment="demo", device="cpu")
    with pytest.raises(TrainingError, match="no examples"):
        lora.train_adapter("m", [], tmp_path / "demo", compartment="demo", device="cpu")


def test_train_adapter_saves_and_describes(tmp_path, monkeypatch):
    import localagent.training.lora as lora

    class FakeTok(CharTokenizer):
        @classmethod
        def from_pretrained(cls, model_id):
            return cls()

    class FakeModelCls:
        @staticmethod
        def from_pretrained(model_id, dtype=None):
            return tiny_model()

    monkeypatch.setattr("transformers.AutoTokenizer", FakeTok)
    monkeypatch.setattr("transformers.AutoModelForCausalLM", FakeModelCls)
    examples = [{"messages": MESSAGES}]
    info = lora.train_adapter("org/model", examples, tmp_path / "demo", compartment="demo", device="cpu",
                              epochs=2, rank=4, alpha=8, log=lambda m: None)
    assert info["compartment"] == "demo" and info["base_model"] == "org/model" and info["examples"] == 1
    assert info["examples_sha256"] == examples_hash(examples) and info["settings"]["epochs"] == 2
    assert read_adapter_info(tmp_path / "demo") == info
