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


# Stand-in installables: a tool, a connection and an MCP server (real ones live outside this repo)
FAKE_EXTENSIONS = Path(__file__).resolve().parent / "fake_extensions"
NOTES_SOURCE = (FAKE_EXTENSIONS / "tools/notes").as_posix()
DUMMY_SOURCE = (FAKE_EXTENSIONS / "connections/dummy").as_posix()
MCP_SERVER = (FAKE_EXTENSIONS / "mcp_test_server.py").as_posix()
DEFAULT_INSTALLABLES = f"tools:\n  notes:\n    source: {NOTES_SOURCE}\n"
WITH_DUMMY = DEFAULT_INSTALLABLES + f"connections:\n  dummy:\n    source: {DUMMY_SOURCE}\n"


def write_agent_yaml(agent_dir: Path, text: str | None = None, installables: str | None = DEFAULT_INSTALLABLES) -> Path:
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "agent.yaml").write_text(text or DEFAULT_AGENT_YAML, encoding="utf-8")
    if installables is not None:
        (agent_dir / "installables.yaml").write_text(installables, encoding="utf-8")
    return agent_dir
