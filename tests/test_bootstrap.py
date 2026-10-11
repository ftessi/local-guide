from localagent.__main__ import main
from localagent.bootstrap import build_services
from localagent.config import load_config
from tests.fakes import FakeBackend, write_agent_yaml


def test_build_services_with_fake_backend(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENT_SECRET", raising=False)
    monkeypatch.delenv("VAPID_PRIVATE_KEY", raising=False)
    d = write_agent_yaml(tmp_path / "a")
    (d / ".env").write_text("AGENT_SECRET=abc\nVAPID_PRIVATE_KEY=vapid_private.pem\n")
    (d / "vapid_private.pem").write_text("x")
    s = build_services(load_config(d), backend=FakeBackend(replies=["hi"]))
    assert list(s.tools) == ["calendar"]
    assert s.push.private_key == str(d / "vapid_private.pem")
    session = s.protocol.open_owner_session("abc")
    assert s.agent.respond(session, "hello") == "hi"


def test_main_reports_missing_agent(tmp_path, capsys):
    assert main(["chat", "--agent", str(tmp_path / "none")]) == 2
    assert "new_agent.py" in capsys.readouterr().err


def test_main_reports_bad_policy(tmp_path, capsys):
    d = write_agent_yaml(tmp_path / "a")
    (d / "policy.yaml").write_text("owner: [everything]\n")
    assert main(["chat", "--agent", str(d)]) == 2
    assert "everything" in capsys.readouterr().err
