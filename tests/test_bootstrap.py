from localagent.__main__ import main
from localagent.bootstrap import build_services
from localagent.config import load_config
from localagent.extensions import close_tools
from tests.fakes import MCP_SERVER, WITH_DUMMY, FakeBackend, write_agent_yaml


def test_build_services_with_fake_backend(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENT_SECRET", raising=False)
    d = write_agent_yaml(tmp_path / "a", installables=WITH_DUMMY)
    (d / ".env").write_text("AGENT_SECRET=abc\n")
    s = build_services(load_config(d), backend=FakeBackend(replies=["hi"]))
    assert list(s.tools) == ["notes"]
    dummy = s.connections["dummy"]
    assert dummy.events == ["setup"] and dummy.ctx.agent is s.agent
    s.tools["notes"].notify("t", "b")  # tools notify through the channels connections added
    assert dummy.notifications == [("t", "b")]
    session = s.protocol.open_owner_session("abc")
    assert s.agent.respond(session, "hello") == "hi"


def test_mcp_tool_end_to_end(tmp_path, monkeypatch):
    """An MCP server listed in installables.yaml, called by the model, result fed back, all through the guard."""
    monkeypatch.delenv("AGENT_SECRET", raising=False)
    installables = (f"tools:\n  test:\n    mcp: [python, {MCP_SERVER}]\n    actions: [echo]\n"
                    "    cwd: '{agent}/workspace'\n")
    d = write_agent_yaml(tmp_path / "a", installables=installables)
    (d / ".env").write_text("AGENT_SECRET=abc\n")
    call = '<tool>{"name":"test","action":"echo","args":{"text":"ping","shout":true}}</tool>'
    backend = FakeBackend(replies=["Checking. " + call, "The server said PING."])
    s = build_services(load_config(d), backend=backend)
    try:
        assert (d / "workspace").is_dir()
        reply = s.agent.respond(s.protocol.open_owner_session("abc"), "echo ping loudly")
        assert reply == 'Checking.\n\n(used test.echo: text="ping", shout=true)\n\nThe server said PING.'
        assert 'test.echo: {"result": "PING"}' in backend.calls[1][-1]["content"]
        assert 'name "test", action "echo"' in backend.calls[0][0]["content"]
        assert "broken" not in backend.calls[0][0]["content"]  # only the listed actions are shown
    finally:
        close_tools(s.tools)


def test_chat_skips_connections(tmp_path):
    d = write_agent_yaml(tmp_path / "a", installables=WITH_DUMMY)
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
    d = write_agent_yaml(tmp_path / "a", installables="tools:\n  weather:\n    source: ./nowhere\n")
    assert main(["chat", "--agent", str(d)]) == 2
    assert "python -m localagent install" in capsys.readouterr().err


def test_main_reports_mcp_server_that_cannot_start(tmp_path, capsys):
    d = write_agent_yaml(tmp_path / "a", installables="tools:\n  web:\n    mcp: [definitely-not-a-program]\n")
    assert main(["chat", "--agent", str(d)]) == 2
    assert "not found on PATH" in capsys.readouterr().err


def test_serve_without_connections_explains(tmp_path, capsys):
    assert main(["serve", "--agent", str(write_agent_yaml(tmp_path / "a"))]) == 2
    assert "no connections" in capsys.readouterr().err


def test_list_command(tmp_path, capsys):
    assert main(["list", "--agent", str(write_agent_yaml(tmp_path / "a"))]) == 0
    out = capsys.readouterr().out
    assert "notes" in out and "fake_extensions/tools/notes" in out
