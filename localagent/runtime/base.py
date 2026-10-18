"""The one interface every model backend implements. Nothing above this layer knows which model runs."""
from pathlib import Path
from typing import Iterator, Protocol, runtime_checkable

# Tokens that open a new chat turn in common templates (ChatML/Qwen, Llama 3, Gemma, Phi).
# Small models sometimes skip their end-of-turn token and start inventing the user's next message;
# stopping on these as well ends the reply where it should.
TURN_START_TOKENS = ("<|im_start|>", "<|start_header_id|>", "<start_of_turn>", "<|user|>")


class AdapterLoadError(RuntimeError):
    """Adapters could not be activated. No adapter is active afterwards."""


@runtime_checkable
class Backend(Protocol):
    def load(self, model_id: str, quantization: str) -> None: ...

    def generate(self, messages: list[dict], max_new_tokens: int) -> str: ...

    def generate_stream(self, messages: list[dict], max_new_tokens: int) -> Iterator[str]: ...

    def set_adapters(self, paths: list[Path]) -> None:
        """Activate exactly these LoRA adapters; [] means the base model."""
        ...

    def info(self) -> dict: ...
