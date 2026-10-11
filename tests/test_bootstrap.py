from localagent.__main__ import main
from localagent.bootstrap import build_services
from localagent.config import load_config
from tests.fakes import DEFAULT_INSTALLABLES, FakeBackend, write_agent_yaml


def test_build_services_with_fake_backend(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENT_SECRET", raising=False)
    d = write_agent_yaml(tmp_path / "a", installables=DEFAULT_INSTALLABLES + "connections:\n  dummy:\n")
    (d / ".env").write_text("AGENT_SECRET=abc\n")
    s = build_services(load_config(d), backend=FakeBackend(replies=["hi"]))
    assert list(s.tools) == ["notes"]
    dummy = s.connections["dummy"]
    assert dummy.events == ["setup"] and dummy.ctx.agent is s.agent
    s.tools["notes"].notify("t", "b")  # tools notify through the channels connections added
    assert dummy.notifications == [("t", "b")]
    session = s.protocol.open_owner_session("abc")
    assert s.agent.respond(session, "hello") == "hi"


def test_chat_skips_connections(tmp_path):
    d = write_agent_yaml(tmp_path / "a", installables=DEFAULT_INSTALLABLES + "connections:\n  dummy:\n")
    s = build_services(load_config(d), backend=FakeBackend(), with_connections=False)
    assert s.connections == {}


def test_main_reports_missing_agent(tmp_path, capsys):
    assert main(["chat", "--agent", str(tmp_path / "none")]) == 2
    assert "new_agent.py" in capsys.readouterr().err


def test_main_reports_bad_policy(tmp_path, capsys):
    d = write_agent_yaml(tmp_path / "a")
    (d / "policy.yaml").write_text("owner: [everything]\n")
    assert main(["chat", "--agent", str(d)]) == 2
    assert "everything" in capsys.readouterr().err


def test_main_reports_extension_not_installed(tmp_path, capsys):
    d = write_agent_yaml(tmp_path / "a", installables=DEFAULT_INSTALLABLES.replace("notes", "weather"))
    assert main(["chat", "--agent", str(d)]) == 2
    assert "python -m localagent install" in capsys.readouterr().err


def test_serve_without_connections_explains(tmp_path, capsys):
    assert main(["serve", "--agent", str(write_agent_yaml(tmp_path / "a"))]) == 2
    assert "no connections" in capsys.readouterr().err


def test_list_command(tmp_path, capsys):
    assert main(["list", "--agent", str(write_agent_yaml(tmp_path / "a"))]) == 0
    assert "[x] notes" in capsys.readouterr().out
