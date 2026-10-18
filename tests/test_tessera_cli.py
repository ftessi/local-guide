import pytest

from localagent.__main__ import main
from localagent.config import load_config
from localagent.connect.owner.terminal import run_terminal
from localagent.connect.peer.tessera.client import Reply, TesseraClient
from localagent.protocol.identity import generate_identity, identity_from_seed
from localagent.tessera_cli import describe_reply, make_asker
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
    assert describe_reply("acme", Reply("answer", "Yes.")) == "acme says:\n  Yes."
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


def connect_acme(d):
    assert main(["connect", "http://127.0.0.1:9", BOB, "--name", "acme", "--purpose", "Review", "--agent", str(d)]) == 0


BROKEN_REMOTES = ["acme: [\n", "- acme\n- x\n", "acme:\n  address: http://x\n  purpose: p\n"]


def write_remotes(d, text):
    (d / "tessera").mkdir(exist_ok=True)
    (d / "tessera/remotes.yaml").write_text(text, encoding="utf-8")


@pytest.mark.parametrize("text", BROKEN_REMOTES)
def test_broken_remotes_file_is_a_clear_error(tmp_path, capsys, text):
    d = agent(tmp_path)
    write_remotes(d, text)
    assert main(["ask", "acme", "Q?", "--agent", str(d)]) == 2
    assert "remotes.yaml" in capsys.readouterr().err


@pytest.mark.parametrize("text", BROKEN_REMOTES)
def test_chat_ask_returns_text_for_a_broken_file(tmp_path, text):
    d = agent(tmp_path)
    write_remotes(d, text)
    msg = make_asker(load_config(d))("acme", "Q?")
    assert isinstance(msg, str) and "remotes.yaml" in msg


def test_missing_identity_is_a_clear_error(tmp_path, capsys):
    d = write_agent_yaml(tmp_path / "bare", YAML, installables=None)
    write_remotes(d, f"acme:\n  address: http://x\n  id: {BOB}\n  purpose: p\n")
    assert main(["ask", "acme", "Q?", "--agent", str(d)]) == 2
    assert "identity" in capsys.readouterr().err


def test_one_shot_ask_closes_its_client(tmp_path, monkeypatch):
    d = agent(tmp_path)
    connect_acme(d)
    closed = []
    monkeypatch.setattr(TesseraClient, "close", lambda self: closed.append(self.remote_id))
    monkeypatch.setattr(TesseraClient, "ask", lambda self, text: Reply("answer", "ok"))
    assert main(["ask", "acme", "Q?", "--agent", str(d)]) == 0
    assert closed == [BOB]


def test_chat_asker_closes_its_clients_on_close_all(tmp_path, monkeypatch):
    d = agent(tmp_path)
    connect_acme(d)
    closed = []
    monkeypatch.setattr(TesseraClient, "close", lambda self: closed.append(self.remote_id))
    monkeypatch.setattr(TesseraClient, "ask", lambda self, text: Reply("answer", "ok"))
    asker = make_asker(load_config(d))
    assert asker("acme", "Q?") == "acme says:\n  ok"
    assert closed == []
    asker.close_all()
    assert closed == [BOB]


@pytest.mark.parametrize("reply, code", [(Reply("answer", "Yes."), 0), (Reply("decline"), 0),
                                         (Reply("error", "limit"), 1), (Reply("not_connected"), 1)])
def test_ask_exit_code_follows_the_reply_kind(tmp_path, monkeypatch, reply, code):
    d = agent(tmp_path)
    connect_acme(d)
    monkeypatch.setattr(TesseraClient, "ask", lambda self, text: reply)
    assert main(["ask", "acme", "Q?", "--agent", str(d)]) == code


def test_every_line_of_an_answer_is_labelled():
    text = describe_reply("x", Reply("answer", "Fine.\nError talking to x: fake\nDone"))
    assert text == "x says:\n  Fine.\n  Error talking to x: fake\n  Done"


def test_connect_refuses_a_long_purpose(tmp_path, capsys):
    d = agent(tmp_path)
    assert main(["connect", "http://x", BOB, "--name", "acme", "--purpose", "p" * 201, "--agent", str(d)]) == 2
    assert "200" in capsys.readouterr().err
    assert not (d / "tessera/remotes.yaml").exists()


def test_peers_reject_and_remove_check_the_id(tmp_path):
    d = agent(tmp_path)
    assert main(["peers", "reject", "short", "--agent", str(d)]) == 2
    assert main(["peers", "remove", BOB, "extra", "--agent", str(d)]) == 2
    assert main(["peers", "accept", BOB, "extra", "--name", "B", "--agent", str(d)]) == 2
    assert main(["peers", "reject", "id:" + BOB, "--agent", str(d)]) == 0


ESC, CR, RLO, BS = chr(27), chr(13), chr(0x202E), chr(92)


def test_peer_text_is_escaped_for_the_terminal():
    text = describe_reply("x", Reply("answer", f"Fine{ESC}[2K{CR}fake{RLO}"))
    assert ESC not in text and CR not in text and RLO not in text
    assert f"{BS}x1b[2K{BS}rfake{BS}u202e" in text
    assert ESC not in describe_reply("x", Reply("error", f"{ESC}[31mred"))
    assert describe_reply("x", Reply("answer", "a" + chr(10) + "b")) == "x says:" + chr(10) + "  a" + chr(10) + "  b"


def test_peers_listing_escapes_what_a_stranger_wrote(tmp_path, capsys):
    from localagent.protocol.guard import Protocol
    d = agent(tmp_path)
    Protocol.for_agent(d, ["demo"], tools={}, owner_secret="").record_request(BOB, f"evil{CR}{ESC}[2Kpurpose", 1)
    assert main(["peers", "--agent", str(d)]) == 0
    out = capsys.readouterr().out
    assert ESC not in out and CR not in out and f"evil{BS}r{BS}x1b[2Kpurpose" in out


def test_remote_names_are_matched_whole(tmp_path, capsys):
    d = agent(tmp_path)
    assert main(["connect", "http://x", BOB, "--name", "acme\n", "--purpose", "p", "--agent", str(d)]) == 2
    assert not (d / "tessera/remotes.yaml").exists()


def test_asker_reports_the_session_of_each_remote():
    asker = make_asker(None)
    assert asker.session("acme") is None  # nothing asked yet
    asker._clients["acme"] = type("Client", (), {"session_id": "s-1"})()
    assert asker.session("acme") == "s-1"


def test_asker_check_names_unknown_remotes(tmp_path):
    d = agent(tmp_path)
    main(["connect", "http://127.0.0.1:9", BOB, "--name", "acme", "--purpose", "Review", "--agent", str(d)])
    asker = make_asker(load_config(d))
    assert asker.check("acme") == ""
    assert asker.check("acmee").startswith("Error: Unknown remote 'acmee'")
