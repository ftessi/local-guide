import pytest
from dotenv import dotenv_values

from localagent.config import DEFAULT_EXTENSIONS_SOURCE, load_config
from localagent.setup_agent import create_agent


def test_create_agent(tmp_path):
    d = tmp_path / "bob"
    agent_id = create_agent(d, model={"id": "Qwen/Qwen2.5-1.5B-Instruct", "quantization": "fp16"})
    cfg = load_config(d)
    assert cfg.name == "bob"
    assert (cfg.model.id, cfg.model.quantization) == ("Qwen/Qwen2.5-1.5B-Instruct", "fp16")
    assert len(dotenv_values(d / ".env")["AGENT_SECRET"]) == 64
    assert (d / "identity/agent.pub").read_text().strip() == agent_id
    assert (d / "knowledge/private").is_dir() and (d / "knowledge/shared").is_dir()
    # The template starts with the calendar and the phone app, from the shared extensions repo
    assert cfg.installables.source == DEFAULT_EXTENSIONS_SOURCE
    assert cfg.installables.tools == {"calendar": {"compartment": "private"}}
    assert set(cfg.installables.connections) == {"phone"}


def test_create_agent_refuses_existing(tmp_path):
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "file").write_text("keep me")
    with pytest.raises(FileExistsError):
        create_agent(tmp_path / "x")
    assert (tmp_path / "x" / "file").read_text() == "keep me"
