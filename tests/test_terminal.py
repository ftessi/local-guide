import pytest

from localagent.connect.owner.terminal import _is_command


@pytest.mark.parametrize("text", ["reset", "/reset", "Reset.", "reset once", "RESET!"])
def test_reset_variants(text):
    assert _is_command(text, "reset")


@pytest.mark.parametrize("text", ["please reset my calendar reminders", "resetting", "", "what is reset"])
def test_normal_messages_are_not_commands(text):
    assert not _is_command(text, "reset")


def test_only_the_ask_word_is_the_ask_command(monkeypatch, capsys):
    from localagent.connect.owner.terminal import run_terminal

    class FakeAgent:
        def respond_stream(self, session, text):
            yield f"agent got {text}"

    class FakeProtocol:
        def open_owner_session(self, secret):
            return type("S", (), {"close": lambda self: None, "reset_history": lambda self: None})()

    asked = []
    inputs = iter(["/asked about it", "/ASK acme Q?", "exit"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(inputs))
    run_terminal(FakeProtocol(), FakeAgent(), "t", ask=lambda n, q: asked.append((n, q)) or "ok")
    assert asked == [("acme", "Q?")] and "agent got /asked about it" in capsys.readouterr().out
