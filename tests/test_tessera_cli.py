from localagent.__main__ import main
from localagent.connect.owner.terminal import run_terminal
from localagent.connect.peer.tessera.client import Reply
from localagent.protocol.identity import generate_identity, identity_from_seed
from localagent.tessera_cli import describe_reply
from tests.fakes import write_agent_yaml

YAML = "name: a\nmodel:\n  id: org/model\ncompartments: [demo]\n"  # a Tessera-facing agent
INTERNAL_YAML = "name: me\nmodel:\n  id: org/model\ncompartments: [private, demo]\n"
BOB = identity_from_seed(bytes(range(32, 64))).agent_id


def agent(tmp_path, name="a", text=YAML):
    d = write_agent_yaml(tmp_path / name, text, installables=None)
    generate_identity(d / "identity")
    return d


def test_id(tmp_path, capsys):
    d = agent(tmp_path)
    assert main(["id", "--agent", str(d)]) == 0
    assert capsys.readouterr().out.strip() == (d / "identity/agent.pub").read_text().strip()


def test_peers_accept_reject_remove(tmp_path, capsys):
    d = agent(tmp_path)
    assert main(["peers", "--agent", str(d)]) == 0
    assert "(none)" in capsys.readouterr().out
    assert main(["peers", "accept", BOB, "--name", "Bob", "--agent", str(d)]) == 0
    assert main(["peers", "--agent", str(d)]) == 0
    out = capsys.readouterr().out
    assert "Bob" in out and "level=1" in out
    assert main(["peers", "remove", BOB, "--agent", str(d)]) == 0
    assert "Bob" not in (d / "policy.yaml").read_text()
    assert main(["peers", "accept", BOB, "--agent", str(d)]) == 2
    assert "--name" in capsys.readouterr().err
    internal = agent(tmp_path, "me", INTERNAL_YAML)
    assert main(["peers", "accept", BOB, "--name", "Bob", "--agent", str(internal)]) == 2
    assert "Tessera-facing" in capsys.readouterr().err


def test_connect_saves_the_remote(tmp_path, capsys):
    d = agent(tmp_path)
    assert main(["connect", "http://127.0.0.1:8100", BOB, "--name", "acme", "--purpose", "Review",
                 "--agent", str(d)]) == 0
    text = (d / "tessera/remotes.yaml").read_text()
    assert "acme" in text and BOB in text and "127.0.0.1:8100" in text
    assert main(["connect", "http://x", "short", "--name", "acme", "--purpose", "p", "--agent", str(d)]) == 2
    assert main(["ask", "nobody", "Q?", "--agent", str(d)]) == 2
    assert "connect" in capsys.readouterr().err


def test_ask_when_nobody_answers(tmp_path, capsys):
    d = agent(tmp_path)
    main(["connect", "http://127.0.0.1:9", BOB, "--name", "acme", "--purpose", "Review", "--agent", str(d)])
    assert main(["ask", "acme", "What", "is", "it?", "--agent", str(d)]) == 1
    assert "Not connected: acme" in capsys.readouterr().out


def test_an_id_starting_with_a_dash_is_not_taken_for_an_option(tmp_path):
    d = agent(tmp_path)
    dashed = "-" + "A" * 42
    assert main(["peers", "accept", dashed, "--name", "Dash", "--agent", str(d)]) == 0
    assert dashed in (d / "policy.yaml").read_text()
    assert main(["connect", "http://x", dashed, "--name", "dash", "--purpose", "p", "--agent", str(d)]) == 0
    assert dashed in (d / "tessera/remotes.yaml").read_text()


def test_reply_wording():
    assert describe_reply("acme", Reply("answer", "Yes.")) == "acme: Yes."
    assert describe_reply("acme", Reply("decline")) == "acme declined: I can't share that."
    assert "hasn't accepted" in describe_reply("acme", Reply("not_connected"))
    assert describe_reply("acme", Reply("error", "limit")) == "Error talking to acme: limit"


def test_terminal_ask_command(monkeypatch, capsys):
    class FakeProtocol:
        def open_owner_session(self, secret):
            return type("S", (), {"close": lambda self: None, "reset_history": lambda self: None})()

    asked = []
    inputs = iter(["/ask acme What is the shared secret?", "/ask acme", "exit"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(inputs))
    run_terminal(FakeProtocol(), agent=None, secret="t",
                 ask=lambda name, q: asked.append((name, q)) or f"{name}: ok")
    out = capsys.readouterr().out
    assert asked == [("acme", "What is the shared secret?")] and "acme: ok" in out and "Usage: /ask" in out
