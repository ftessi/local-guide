"""Helpers for testing tools and connections without a real model. Not used at runtime."""
from pathlib import Path

from localagent.runtime.base import AdapterLoadError


class FakeBackend:
    """Scripted backend: returns replies in order, then 'OK'. Streams in 7-char chunks."""

    def __init__(self, replies=None, fail_adapters: bool = False):
        self.replies = list(replies or [])
        self.fail_adapters = fail_adapters
        self.calls: list[list[dict]] = []
        self.adapters: list[Path] = []
        self.model_id = ""

    def load(self, model_id, quantization="4bit"):
        self.model_id = model_id

    def _next(self) -> str:
        return self.replies.pop(0) if self.replies else "OK"

    def generate(self, messages, max_new_tokens=256):
        self.calls.append(list(messages))
        return self._next()

    def generate_stream(self, messages, max_new_tokens=256):
        self.calls.append(list(messages))
        text = self._next()
        for i in range(0, len(text), 7):
            yield text[i:i + 7]

    def set_adapters(self, paths):
        if self.fail_adapters and paths:
            self.adapters = []
            raise AdapterLoadError("fake failure")
        self.adapters = list(paths)

    def info(self):
        return {"model_id": self.model_id, "backend": "fake", "device": "none",
                "adapters": [str(p) for p in self.adapters]}
