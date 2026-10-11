import pytest

from localagent.config import ConfigError, load_config, resolve_agent_dir
from tests.fakes import write_agent_yaml


def test_load_defaults_and_values(tmp_path):
    cfg = load_config(write_agent_yaml(tmp_path / "a"))
    assert cfg.name == "test-agent"
    assert cfg.model.id == "fake/model"
    assert cfg.model.max_new_tokens == 64
    assert cfg.compartments == ["private", "shared"]
    assert cfg.tools == {"calendar": {"enabled": True}}
    assert cfg.history_turns == 5
    assert cfg.port == 8000


def test_minimal_yaml_uses_defaults(tmp_path):
    cfg = load_config(write_agent_yaml(tmp_path / "a", "name: x\n"))
    assert cfg.model.id == "Qwen/Qwen2.5-3B-Instruct"
    assert cfg.model.quantization == "4bit"
    assert cfg.compartments == ["private", "shared"]


def test_tool_shorthands_normalized(tmp_path):
    cfg = load_config(write_agent_yaml(tmp_path / "a", "tools:\n  calendar:\n  other: false\n"))
    assert cfg.tools == {"calendar": {}, "other": {"enabled": False}}


def test_env_file_and_environment(tmp_path, monkeypatch):
    d = write_agent_yaml(tmp_path / "a")
    (d / ".env").write_text("AGENT_SECRET=from-file\nVAPID_PUBLIC_KEY=pub\n")
    monkeypatch.delenv("AGENT_SECRET", raising=False)
    monkeypatch.setenv("VAPID_PUBLIC_KEY", "from-env")
    cfg = load_config(d)
    assert cfg.get_env("AGENT_SECRET") == "from-file"
    assert cfg.get_env("VAPID_PUBLIC_KEY") == "from-env"
    assert cfg.get_env("MISSING", "dflt") == "dflt"


@pytest.mark.parametrize("text, fragment", [
    ("model:\n  quantization: 8bit\n", "quantization"),
    ("compartments: [shared]\n", "private"),
    ("compartments: [private, Bad_Name]\n", "Bad_Name"),
    ("compartments: [private, private]\n", "duplicate"),
    ("modle:\n  id: x\n", "modle"),
    ("model:\n  max_new_tokens: 0\n", "max_new_tokens"),
])
def test_invalid_values_rejected(tmp_path, text, fragment):
    with pytest.raises(ConfigError, match=fragment):
        load_config(write_agent_yaml(tmp_path / "a", text))


def test_bad_yaml_message(tmp_path):
    with pytest.raises(ConfigError, match="not valid YAML"):
        load_config(write_agent_yaml(tmp_path / "a", "model: [unclosed\n"))


def test_missing_agent_dir_message(tmp_path):
    with pytest.raises(ConfigError, match="new_agent.py"):
        resolve_agent_dir(str(tmp_path / "nope"))


def test_resolve_from_env(tmp_path, monkeypatch):
    d = write_agent_yaml(tmp_path / "a")
    monkeypatch.setenv("LOCALAGENT_DIR", str(d))
    assert resolve_agent_dir(None) == d.resolve()
