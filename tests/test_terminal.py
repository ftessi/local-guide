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


class TalkAsker:
    """Stands in for Asker: answers with a counter; the session changes after `roll_after` messages."""

    def __init__(self, known=("demo",), roll_after=None, reply=None):
        self.known, self.roll_after, self.reply = known, roll_after, reply
        self.asked, self.sid = [], None

    def __call__(self, name, text):
        self.asked.append((name, text))
        n = len(self.asked)
        self.sid = "s-2" if self.roll_after and n > self.roll_after else "s-1"
        return self.reply or f"{name} says:\n  answer {n}"

    def session(self, name):
        return self.sid

    def check(self, name):
        return "" if name in self.known else f"Error: Unknown remote '{name}'."


def run_chat(monkeypatch, lines, asker):
    from localagent.connect.owner.terminal import run_terminal

    class FakeAgent:
        def respond_stream(self, session, text):
            yield f"agent got {text}"

    class FakeProtocol:
        def open_owner_session(self, secret):
            return type("S", (), {"close": lambda self: None, "reset_history": lambda self: None})()

    prompts, inputs = [], iter(lines)
    monkeypatch.setattr("builtins.input", lambda prompt: prompts.append(prompt) or next(inputs))
    code = run_terminal(FakeProtocol(), FakeAgent(), "t", ask=asker)
    return code, prompts


def test_talk_sends_every_message_to_the_peer_until_back(monkeypatch, capsys):
    asker = TalkAsker()
    code, prompts = run_chat(monkeypatch, ["/talk demo", "hello", "reset", "/ask x y", "/back", "hi", "exit"], asker)
    out = capsys.readouterr().out
    assert code == 0
    assert asker.asked == [("demo", "hello"), ("demo", "reset"), ("demo", "/ask x y")]
    assert prompts == ["You: ", "You -> demo: ", "You -> demo: ", "You -> demo: ", "You -> demo: ", "You: ", "You: "]
    assert "demo says:\n  answer 1" in out and "agent got hi" in out
    assert "new session" not in out


def test_talk_to_an_unknown_name_stays_in_normal_mode(monkeypatch, capsys):
    asker = TalkAsker()
    _, prompts = run_chat(monkeypatch, ["/talk demoo", "hi", "exit"], asker)
    out = capsys.readouterr().out
    assert "Unknown remote 'demoo'" in out and "agent got hi" in out
    assert asker.asked == [] and prompts == ["You: ", "You: ", "You: "]


def test_talk_usage(monkeypatch, capsys):
    run_chat(monkeypatch, ["/talk", "/talk a b", "exit"], TalkAsker())
    assert capsys.readouterr().out.count("Usage: /talk <name>") == 2


def test_exit_while_talking_ends_chat(monkeypatch):
    asker = TalkAsker()
    code, _ = run_chat(monkeypatch, ["/talk demo", "exit", "never read"], asker)
    assert code == 0 and asker.asked == []


def test_a_new_session_is_announced_once(monkeypatch, capsys):
    asker = TalkAsker(roll_after=2)
    run_chat(monkeypatch, ["/talk demo", "one", "two", "three", "four", "exit"], asker)
    out = capsys.readouterr().out
    assert out.count("(new session with demo: it doesn't remember the earlier conversation)") == 1
    assert out.index("answer 3") < out.index("new session with demo")


def test_errors_while_talking_keep_talk_mode(monkeypatch, capsys):
    asker = TalkAsker(reply="Not connected: demo hasn't accepted this agent (or isn't reachable).")
    _, prompts = run_chat(monkeypatch, ["/talk demo", "hi", "again", "/back", "exit"], asker)
    assert capsys.readouterr().out.count("Not connected: demo") == 2
    assert prompts == ["You: ", "You -> demo: ", "You -> demo: ", "You -> demo: ", "You: "]


def test_talk_shows_peer_text_as_the_asker_formats_it(monkeypatch, capsys):
    from localagent.connect.peer.tessera.client import Reply
    from localagent.tessera_cli import describe_reply
    asker = TalkAsker(reply=describe_reply("demo", Reply("answer", "ok\x1b[2J")))
    run_chat(monkeypatch, ["/talk demo", "hi", "exit"], asker)
    out = capsys.readouterr().out
    assert "demo says:\n  ok\\x1b[2J" in out and "\x1b" not in out


def test_short_messages_starting_with_back_or_exit_go_to_the_peer(monkeypatch):
    asker = TalkAsker()
    code, prompts = run_chat(monkeypatch, ["/talk demo", "Back up?", "Exit strategy?", "/back", "exit"], asker)
    assert code == 0 and asker.asked == [("demo", "Back up?"), ("demo", "Exit strategy?")]
    assert prompts[-1] == "You: "


def test_ctrl_c_while_waiting_for_the_peer_says_goodbye(monkeypatch, capsys):
    class Interrupted(TalkAsker):
        def __call__(self, name, text):
            raise KeyboardInterrupt
    code, _ = run_chat(monkeypatch, ["/talk demo", "hi"], Interrupted())
    assert code == 0 and "Goodbye." in capsys.readouterr().out
