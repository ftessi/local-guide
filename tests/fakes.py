from pathlib import Path

from localagent.runtime.base import AdapterLoadError

DEFAULT_AGENT_YAML = """\
name: test-agent
model:
  id: fake/model
  backend: transformers
  quantization: 4bit
  max_new_tokens: 64
compartments: [private, shared]
tools:
  calendar:
    enabled: true
memory:
  history_turns: 5
"""


def write_agent_yaml(agent_dir: Path, text: str | None = None) -> Path:
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "agent.yaml").write_text(text or DEFAULT_AGENT_YAML, encoding="utf-8")
    return agent_dir


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
