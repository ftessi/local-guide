from pathlib import Path

from localagent.testing import FakeBackend  # noqa: F401  (re-exported for the tests)

DEFAULT_AGENT_YAML = """\
name: test-agent
model:
  id: fake/model
  backend: transformers
  quantization: 4bit
  max_new_tokens: 64
compartments: [private, shared]
memory:
  history_turns: 5
"""


# Stand-in extensions source: tools/notes and connections/dummy (the real ones live in the extensions repo)
FAKE_EXTENSIONS = Path(__file__).resolve().parent / "fake_extensions"
DEFAULT_INSTALLABLES = f"source: {FAKE_EXTENSIONS.as_posix()}\ntools:\n  notes:\n"


def write_agent_yaml(agent_dir: Path, text: str | None = None, installables: str | None = DEFAULT_INSTALLABLES) -> Path:
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "agent.yaml").write_text(text or DEFAULT_AGENT_YAML, encoding="utf-8")
    if installables is not None:
        (agent_dir / "installables.yaml").write_text(installables, encoding="utf-8")
    return agent_dir
