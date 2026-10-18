"""HuggingFace Transformers backend (NVIDIA / CUDA, CPU fallback)."""
from contextlib import contextmanager
from pathlib import Path
from threading import Thread

from localagent.runtime.base import TURN_START_TOKENS, AdapterLoadError

# Reading a whole prompt at once needs memory that grows with its length squared (Qwen2.5-1.5B on a 4 GB card:
# 2000 tokens +561 MiB, 2500 out of memory). Read in chunks it grows slowly (8000 tokens +282 MiB), same output.
PREFILL_CHUNK = 256


def stream_in_thread(generate, kwargs: dict, streamer):
    """Runs generate(**kwargs) in a thread and yields the streamer's text. If generation fails (e.g. out of GPU
    memory), the stream is ended and the error raised here; otherwise the reader would wait forever."""
    errors = []

    def run():
        try:
            generate(**kwargs)
        except BaseException as e:
            errors.append(e)
            streamer.end()

    thread = Thread(target=run, daemon=True)
    thread.start()
    yield from streamer
    thread.join()
    if errors:
        raise errors[0]


@contextmanager
def _out_of_memory_hint(prompt_tokens: int):
    import torch

    try:
        yield
    except torch.OutOfMemoryError:
        torch.cuda.empty_cache()
        raise RuntimeError(
            f"Out of GPU memory: the prompt was {prompt_tokens} tokens, too long for this GPU. "
            "Lower model.max_prompt_chars in agent.yaml, or type 'reset' to drop old conversation."
        ) from None


class TransformersBackend:
    name = "transformers"

    def __init__(self):
        self.model = None
        self.tokenizer = None
        self.model_id = ""
        self._adapters: list[Path] = []
        self._stop_ids: list[int] = []

    def load(self, model_id: str, quantization: str = "4bit") -> None:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

        kwargs = {"device_map": "auto"}
        if quantization == "4bit":
            kwargs["quantization_config"] = BitsAndBytesConfig(
                load_in_4bit=True, bnb_4bit_compute_dtype=torch.float16
            )
        elif quantization == "fp16":
            kwargs["dtype"] = torch.float16
        elif quantization != "none":
            raise ValueError(f"Unknown quantization '{quantization}'")
        self.tokenizer = AutoTokenizer.from_pretrained(model_id)
        self.model = AutoModelForCausalLM.from_pretrained(model_id, **kwargs)
        self.model_id = model_id
        self._stop_ids = self._find_stop_ids()

    def _find_stop_ids(self) -> list[int]:
        eos = self.model.generation_config.eos_token_id
        ids = set(eos if isinstance(eos, list) else [eos] if eos is not None else [])
        if self.tokenizer.eos_token_id is not None:
            ids.add(self.tokenizer.eos_token_id)
        vocab = self.tokenizer.get_vocab()
        ids.update(vocab[t] for t in TURN_START_TOKENS if t in vocab)
        return sorted(ids)

    def _prepare_inputs(self, messages: list[dict]):
        text = self.tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        return self.tokenizer([text], return_tensors="pt").to(self.model.device)

    def _prefill(self, input_ids, chunk: int = PREFILL_CHUNK):
        """Reads all but the last prompt token in chunks into a cache that generate() continues from.
        None for short prompts, which are read in one go."""
        import torch
        from transformers import DynamicCache

        end = input_ids.shape[1] - 1
        if end <= chunk:
            return None
        cache = DynamicCache()
        with torch.no_grad():
            for start in range(0, end, chunk):
                self.model(input_ids=input_ids[:, start:min(start + chunk, end)], past_key_values=cache,
                           use_cache=True, logits_to_keep=1)
        return cache

    def _generate_kwargs(self, messages: list[dict], max_new_tokens: int) -> dict:
        inputs = self._prepare_inputs(messages)
        kwargs = dict(**inputs, max_new_tokens=max_new_tokens, do_sample=False,
                      pad_token_id=self.tokenizer.eos_token_id, eos_token_id=self._stop_ids or None)
        with _out_of_memory_hint(inputs["input_ids"].shape[1]):
            cache = self._prefill(inputs["input_ids"])
        if cache is not None:
            kwargs["past_key_values"] = cache
        return kwargs

    def generate(self, messages: list[dict], max_new_tokens: int = 256) -> str:
        kwargs = self._generate_kwargs(messages, max_new_tokens)
        input_len = kwargs["input_ids"].shape[1]
        with _out_of_memory_hint(input_len):
            output_ids = self.model.generate(**kwargs)
        return self.tokenizer.decode(output_ids[0][input_len:], skip_special_tokens=True).strip()

    def generate_stream(self, messages: list[dict], max_new_tokens: int = 256):
        from transformers import TextIteratorStreamer

        kwargs = self._generate_kwargs(messages, max_new_tokens)
        kwargs["streamer"] = streamer = TextIteratorStreamer(self.tokenizer, skip_prompt=True,
                                                             skip_special_tokens=True)
        with _out_of_memory_hint(kwargs["input_ids"].shape[1]):
            yield from stream_in_thread(self.model.generate, kwargs, streamer)

    def set_adapters(self, paths: list[Path]) -> None:
        paths = [Path(p) for p in paths]
        if paths == self._adapters:
            return
        self._remove_adapters()
        if not paths:
            return
        model = None
        try:
            from peft import PeftModel

            model = PeftModel.from_pretrained(self.model, str(paths[0]), adapter_name="a0")
            for i, path in enumerate(paths[1:], start=1):
                model.load_adapter(str(path), adapter_name=f"a{i}")
            model.base_model.set_adapter([f"a{i}" for i in range(len(paths))])
        except Exception as e:
            if model is not None:
                try:
                    self.model = model.unload()
                except Exception:
                    pass
            hint = " (pip install peft)" if isinstance(e, ImportError) else ""
            raise AdapterLoadError(f"Could not load adapters {[str(p) for p in paths]}: {e}{hint}") from e
        self.model = model
        self._adapters = paths

    def _remove_adapters(self) -> None:
        if self._adapters:
            self.model = self.model.unload()
            self._adapters = []

    def info(self) -> dict:
        device = str(getattr(self.model, "device", "unknown")) if self.model is not None else "not loaded"
        return {"model_id": self.model_id, "backend": self.name, "device": device,
                "adapters": [str(p) for p in self._adapters]}
