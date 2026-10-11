import pytest

from localagent.config import ConfigError, load_config
from localagent.connect.base import ConnectionContext, Notifier, SetupError
from localagent.connect.peer.tessera import TesseraConnection, check_tessera_folder
from localagent.extensions import load_connections
from localagent.installer import describe, install
from localagent.protocol.identity import generate_identity
from tests.fakes import write_agent_yaml

YAML = "name: tessera-demo\nmodel:\n  id: org/model\ncompartments: [demo]\n"
TESSERA_ONLY = "connections:\n  tessera:\n    builtin: true\n    host: 127.0.0.1\n    port: 0\n"


def folder(tmp_path):
    d = write_agent_yaml(tmp_path / "t", YAML, installables=TESSERA_ONLY)
    for keep in ("knowledge/demo/.gitkeep", "work/.gitkeep", "memory/.gitkeep"):  # like agent_template/
        (d / keep).parent.mkdir(parents=True, exist_ok=True)
        (d / keep).write_text("")
    (d / "training/adapters/org--model/demo").mkdir(parents=True)
    return d


def test_a_clean_folder_may_face_peers(tmp_path):
    assert check_tessera_folder(load_config(folder(tmp_path))) == []


@pytest.mark.parametrize("make_dirty, fragment", [
    (lambda d: (d / "knowledge/demo/me.md").write_text("PIN"), "knowledge/"),
    (lambda d: (d / "work/plan.md").write_text("x"), "work/"),
    (lambda d: (d / "training/adapters/org--model/private").mkdir(), "private adapter"),
    (lambda d: (d / "agent.yaml").write_text(YAML.replace("[demo]", "[private, demo]")), "exactly one"),
    (lambda d: (d / "training/adapters/org--model/acme").mkdir(), "acme"),
    (lambda d: (d / "training/demo/sources").mkdir(parents=True), "training/demo"),
    (lambda d: (d / "training/demo").mkdir(parents=True) or (d / "training/demo/examples.jsonl").write_text(""),
     "training/demo"),
    (lambda d: (d / "installables.yaml").write_text(TESSERA_ONLY + "tools:\n  notes:\n    source: ./x\n"),
     "tools"),
])
def test_anything_private_is_refused(tmp_path, make_dirty, fragment):
    d = folder(tmp_path)
    make_dirty(d)
    problems = check_tessera_folder(load_config(d))
    assert any(fragment in p for p in problems), problems


def test_builtin_connection_config(tmp_path):
    cfg = load_config(folder(tmp_path))
    assert cfg.installables.connections == {"tessera": {"builtin": True, "host": "127.0.0.1", "port": 0}}
    bad = write_agent_yaml(tmp_path / "x", YAML, installables="connections:\n  phone:\n    builtin: true\n")
    with pytest.raises(ConfigError, match="built-in"):
        load_config(bad)
    assert isinstance(load_connections(cfg.installables.connections, cfg.agent_dir)["tessera"], TesseraConnection)
    assert "built in" in describe(cfg)
    assert install(cfg, log=lambda m: None, pip=lambda p: None) == 0


def test_setup_refuses_a_folder_with_private_data(tmp_path):
    d = folder(tmp_path)
    generate_identity(d / "identity")
    (d / "knowledge/demo/me.md").write_text("PIN")
    cfg = load_config(d)
    conn = TesseraConnection()
    with pytest.raises(SetupError, match="knowledge/"):
        conn.setup(ConnectionContext(config=cfg, protocol=None, agent=None, tools={}, notifier=Notifier(),
                                     settings=cfg.installables.connections["tessera"], data_dir=d / "data"))


def test_chat_is_refused_on_a_tessera_facing_agent(tmp_path, capsys):
    from localagent.__main__ import main
    assert main(["chat", "--agent", str(folder(tmp_path))]) == 2
    assert "internal agent" in capsys.readouterr().err
