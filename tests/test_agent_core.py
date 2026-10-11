from datetime import datetime

import pytest

from localagent.agent.core import Agent
from localagent.extensions import load_tools
from localagent.protocol.guard import Protocol
from localagent.protocol.scopes import Scope
from localagent.runtime.base import AdapterLoadError
from tests.fakes import NOTES_SOURCE, FakeBackend

CREATE = ('<tool>{"name":"notes","action":"add",'
          '"args":{"text":"Dentist","due":"2030-01-01T10:00:00"}}</tool>')
LIST = '<tool>{"name":"notes","action":"list"}</tool>'
NOW = datetime(2026, 10, 11, 9, 30)


@pytest.fixture
def env(tmp_path):
    (tmp_path / "knowledge/private").mkdir(parents=True)
    (tmp_path / "knowledge/private/me.md").write_text("Owner is called Ana.")
    tools = load_tools({"notes": {"source": NOTES_SOURCE}}, tmp_path, tmp_path / "data", None, ["private", "shared"])
    proto = Protocol.for_agent(tmp_path, ["private", "shared"], tools, owner_secret="t")
    return tmp_path, tools, proto


def make_agent(tools, replies, **kw):
    backend = FakeBackend(replies=replies, **kw)
    return Agent(backend, tools, model_id="org/model", history_turns=5, clock=lambda: NOW), backend


def test_plain_reply_records_memory(env):
    _, tools, proto = env
    agent, backend = make_agent(tools, ["Hello Ana!"])
    session = proto.open_owner_session("t")
    assert agent.respond(session, "hi") == "Hello Ana!"
    system = backend.calls[0][0]["content"]
    assert "Owner is called Ana." in system and "2026-10-11 09:30" in system and "Friday 2026-10-16" in system and 'name "notes", action "add"' in system
    assert session.history(5) == [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "Hello Ana!"}]


def test_write_tool_executed_and_hidden(env):
    _, tools, proto = env
    agent, backend = make_agent(tools, ["Reminder set! " + CREATE])
    reply = agent.respond(proto.open_owner_session("t"), "remind me")
    assert reply == "(Using the notes tool... this can take a moment.)\n\n(used notes.add: text=\"Dentist\", due=\"2030-01-01T10:00:00\")"  # what really ran; the text written before the call is dropped
    assert [n["text"] for n in tools["notes"].notes] == ["Dentist"]
    assert len(backend.calls) == 1


def test_read_tool_gets_second_round(env):
    _, tools, proto = env
    tools["notes"].run("add", {"text": "Dentist", "due": "2030-01-01T10:00:00"})
    agent, backend = make_agent(tools, ["Let me check. " + LIST, "You have: Dentist."])
    reply = agent.respond(proto.open_owner_session("t"), "what reminders?")
    assert reply == "(Using the notes tool... this can take a moment.)\n\n(used notes.list)\n\nYou have: Dentist."
    assert backend.calls[1][-1]["content"].startswith("Tool results")
    assert "Dentist" in backend.calls[1][-1]["content"]


def test_second_round_tool_calls_not_executed(env):
    _, tools, proto = env
    agent, backend = make_agent(tools, [LIST, "Done " + CREATE])
    agent.respond(proto.open_owner_session("t"), "x")
    assert tools["notes"].notes == []
    assert len(backend.calls) == 2


def test_unterminated_tag_not_executed(env):
    _, tools, proto = env
    agent, _ = make_agent(tools, ['Sure <tool>{"name":"notes","action":"add","args":{"te'])
    reply = agent.respond(proto.open_owner_session("t"), "x")
    assert reply.endswith("Sure") and "(The notes call was cut off or malformed, so nothing ran.)" in reply
    assert tools["notes"].notes == []


def test_bad_args_notice_shown(env):
    _, tools, proto = env
    bad = '<tool>{"name":"notes","action":"add","args":{"text":"X","due":"someday"}}</tool>'
    agent, _ = make_agent(tools, ["Ok " + bad])
    reply = agent.respond(proto.open_owner_session("t"), "x")
    assert "Couldn't run notes.add" in reply


def test_stream_never_shows_tags(env):
    _, tools, proto = env
    agent, _ = make_agent(tools, ["Reminder set! " + CREATE])
    chunks = list(agent.respond_stream(proto.open_owner_session("t"), "x"))
    assert "<tool" not in "".join(chunks)
    streamed = "".join(chunks).replace(" \n", "\n")  # the space before a hidden tag may stream out
    assert streamed == "(Using the notes tool... this can take a moment.)\n\n(used notes.add: text=\"Dentist\", due=\"2030-01-01T10:00:00\")"


def test_history_included_next_turn(env):
    _, tools, proto = env
    agent, backend = make_agent(tools, ["one", "two"])
    session = proto.open_owner_session("t")
    agent.respond(session, "first")
    agent.respond(session, "second")
    assert [m["content"] for m in backend.calls[1][1:]] == ["first", "one", "second"]


def test_run_tool_outcomes(env):
    _, tools, proto = env
    agent, _ = make_agent(tools, [])
    owner = proto.open_owner_session("t")
    assert agent.run_tool(owner, "notes", "list", {}).ok
    assert agent.run_tool(owner, "email", "send", {}).error_type == "unknown"
    assert agent.run_tool(owner, "notes", "delete", {"id": "x"}).error_type == "bad_args"
    limited = proto._session("peer:x", Scope(["tool:notes:list"]), "peer:x")
    created = agent.run_tool(limited, "notes", "add", {"text": "a", "due": "2030-01-01"})
    assert created.error_type == "denied"
    assert agent.run_tool(limited, "notes", "list", {}).error_type == "withheld"


def test_adapter_failure_refuses_turn(env):
    tmp_path, tools, proto = env
    (tmp_path / "training/adapters/org--model/private").mkdir(parents=True)
    agent, backend = make_agent(tools, ["never"], fail_adapters=True)
    with pytest.raises(AdapterLoadError):
        agent.respond(proto.open_owner_session("t"), "x")
    assert backend.calls == []


def test_adapters_loaded_for_session(env):
    tmp_path, tools, proto = env
    (tmp_path / "training/adapters/org--model/private").mkdir(parents=True)
    agent, backend = make_agent(tools, ["hi"])
    agent.respond(proto.open_owner_session("t"), "x")
    assert [p.name for p in backend.adapters] == ["private"]


def test_history_shows_model_its_working_calls_not_failure_notices(env):
    _, tools, proto = env
    bad = '<tool>{"name":"notes","action":"read"}</tool>'
    agent, backend = make_agent(tools, [CREATE + bad, "next"])
    session = proto.open_owner_session("t")
    shown = agent.respond(session, "remind me")
    assert "(used notes.add: " in shown and "Couldn't run notes.read" in shown  # the user sees both
    agent.respond(session, "and then?")
    replayed = backend.calls[1][2]  # [system, user, assistant, user]
    assert replayed["role"] == "assistant"
    assert '"action": "add"' in replayed["content"] and "Couldn't" not in replayed["content"]
    assert '"read"' not in replayed["content"]


def test_read_round_replayed_without_tool_results(env):
    _, tools, proto = env
    agent, backend = make_agent(tools, ["Let me check. " + LIST, "You have nothing.", "ok"])
    session = proto.open_owner_session("t")
    agent.respond(session, "what do I have?")
    agent.respond(session, "thanks")
    history = backend.calls[2][1:]
    assert [m["role"] for m in history] == ["user", "assistant", "user"]
    assert '"action": "list"' in history[1]["content"] and history[1]["content"].endswith("You have nothing.")
    assert "Tool results" not in history[1]["content"]
    record = session.vault.read("memory", ["private"])[0].content
    assert record["transcript"][1]["content"].startswith("Tool results")  # kept in memory for training


ADD_NOTE = '<tool>{"name":"notes","action":"add","args":{"text":"rm -rf","due":"2030-01-01T10:00:00"}}</tool>'


def test_confirm_tool_waits_for_yes(env):
    _, tools, proto = env
    tools["notes"].confirm = True
    agent, backend = make_agent(tools, ["Sure. " + ADD_NOTE, "Saved it."])
    session = proto.open_owner_session("t")
    first = agent.respond(session, "save a note")
    assert tools["notes"].notes == []  # nothing ran yet
    assert "notes.add" in first and '"rm -rf"' in first and "yes" in first
    second = agent.respond(session, "Yes")
    assert [n["text"] for n in tools["notes"].notes] == ["rm -rf"]
    assert second == '(used notes.add: text="rm -rf", due="2030-01-01T10:00:00")\n\nSaved it.'
    assert backend.calls[1][-1]["content"].startswith("I allowed it. Tool results")


def test_confirm_tool_dropped_on_anything_else(env):
    _, tools, proto = env
    tools["notes"].confirm = True
    agent, backend = make_agent(tools, [ADD_NOTE, "Ok, I won't.", "Fine."])
    session = proto.open_owner_session("t")
    agent.respond(session, "save a note")
    assert agent.respond(session, "no, don't") == "Ok, I won't."
    assert backend.calls[1][-1]["content"] == "no, don't"
    agent.respond(session, "yes")  # nothing pending any more
    assert tools["notes"].notes == []


def test_confirmation_still_goes_through_the_guard(env):
    _, tools, proto = env
    tools["notes"].confirm = True
    agent, _ = make_agent(tools, [ADD_NOTE, "x"])
    limited = proto._session("peer:x", Scope(["tool:notes:list"]), "peer:x")
    agent.respond(limited, "save a note")
    reply = agent.respond(limited, "yes")
    assert tools["notes"].notes == [] and "Couldn't run notes.add" in reply


def test_claimed_but_not_called_shows_no_used_line(env):
    _, tools, proto = env
    agent, _ = make_agent(tools, ["Fetching the results... Here they are: SPD 39%."])
    reply = agent.respond(proto.open_owner_session("t"), "search the election")
    assert "(used" not in reply


def test_recent_results_stay_available_for_follow_ups(env):
    _, tools, proto = env
    tools["notes"].run("add", {"text": "see https://example.com/source", "due": "2030-01-01T10:00:00"})
    agent, backend = make_agent(tools, [LIST, "One note.", "From example.com.", "a", "b", "c"])
    session = proto.open_owner_session("t")
    agent.respond(session, "what notes do I have?")
    agent.respond(session, "which page was that?")
    follow_up_system = backend.calls[2][0]["content"]
    assert "Results of your latest tool calls" in follow_up_system
    assert "https://example.com/source" in follow_up_system
    for text in ("x", "y", "z"):
        agent.respond(session, text)
    assert "https://example.com/source" not in backend.calls[-1][0]["content"]  # forgotten after a few turns


def test_recent_results_are_per_session(env):
    _, tools, proto = env
    tools["notes"].run("add", {"text": "secret", "due": "2030-01-01T10:00:00"})
    agent, backend = make_agent(tools, [LIST, "One note.", "hi"])
    agent.respond(proto.open_owner_session("t"), "what notes?")
    agent.respond(proto.open_owner_session("t"), "hello")
    assert "secret" not in backend.calls[-1][0]["content"]


def test_prompt_budget_drops_oldest_history_first(env):
    _, tools, proto = env
    backend = FakeBackend(replies=["first answer " * 40, "second", "third"])
    agent = Agent(backend, tools, model_id="org/model", history_turns=5, clock=lambda: NOW, max_prompt_chars=3000)
    session = proto.open_owner_session("t")
    agent.respond(session, "old question " * 100)  # big enough that the prompt must be trimmed
    agent.respond(session, "recent question")
    agent.respond(session, "now")
    prompt = backend.calls[-1]
    assert sum(len(m["content"]) for m in prompt) <= 3000
    contents = [m["content"] for m in prompt]
    assert "recent question" in contents and contents[-1] == "now"
    assert not any("old question" in c for c in contents)  # the oldest turn went first


def test_prompt_budget_shortens_a_huge_tool_result(env):
    _, tools, proto = env
    tools["notes"].run("add", {"text": "x" * 20000, "due": "2030-01-01T10:00:00"})
    backend = FakeBackend(replies=[LIST, "Done reading."])
    agent = Agent(backend, tools, model_id="org/model", history_turns=5, clock=lambda: NOW, max_prompt_chars=4000)
    agent.respond(proto.open_owner_session("t"), "read my notes")
    second_round = backend.calls[1]
    assert sum(len(m["content"]) for m in second_round) <= 4000
    assert second_round[-1]["content"].startswith("Tool results") and "[cut to fit" in second_round[-1]["content"]


def test_guess_written_before_a_tool_call_is_never_shown_or_remembered(env):
    """A real 1.5B reply: invented numbers, then the search. Only the answer from the results may be shown."""
    _, tools, proto = env
    guess = "Based on my knowledge, the CDU won with 48%. "
    agent, backend = make_agent(tools, [guess + LIST, "According to the results: no notes.", "ok"])
    session = proto.open_owner_session("t")
    chunks = list(agent.respond_stream(session, "what are the results?"))
    shown = "".join(chunks)
    assert "48%" not in shown and shown.endswith("According to the results: no notes.")
    assert not any("48%" in m["content"] for m in backend.calls[1])  # the model answers from results, not its guess
    agent.respond(session, "thanks")
    assert not any("48%" in m["content"] for m in backend.calls[2])  # and never sees the guess again


def test_plain_answer_without_tools_is_shown_whole(env):
    _, tools, proto = env
    agent, _ = make_agent(tools, ["Just a normal answer."])
    assert "".join(agent.respond_stream(proto.open_owner_session("t"), "hi")) == "Just a normal answer."


class AnnouncingBackend(FakeBackend):
    """Records how much of the reply had been generated when the agent printed something."""

    def __init__(self, replies):
        super().__init__(replies=replies)
        self.generated = 0

    def generate_stream(self, messages, max_new_tokens=256):
        for chunk in super().generate_stream(messages, max_new_tokens):
            self.generated += len(chunk)
            yield chunk


def test_tool_use_is_announced_while_the_model_is_still_writing(env):
    _, tools, proto = env
    reply = 'One moment. <tool>{"name":"notes","action":"list","args":{}}</tool> and some trailing words here'
    backend = AnnouncingBackend([reply, "You have no notes."])
    agent = Agent(backend, tools, model_id="org/model", history_turns=5, clock=lambda: NOW)
    chunks, generated_at = [], []
    for chunk in agent.respond_stream(proto.open_owner_session("t"), "my notes?"):
        chunks.append(chunk)
        generated_at.append(backend.generated)
    first = next(i for i, c in enumerate(chunks) if "Using the notes tool" in c)
    assert generated_at[first] < len(reply)  # announced before the model finished its first reply
    used = next(i for i, c in enumerate(chunks) if "(used notes.list)" in c)
    assert first < used and "".join(chunks).endswith("You have no notes.")
