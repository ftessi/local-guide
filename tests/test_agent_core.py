from datetime import datetime

import pytest

from localagent.agent.core import Agent
from localagent.extensions import load_tools
from localagent.protocol.guard import Protocol
from localagent.protocol.scopes import Scope
from localagent.runtime.base import AdapterLoadError
from tests.fakes import FAKE_EXTENSIONS, FakeBackend

CREATE = ('<tool>{"name":"notes","action":"add",'
          '"args":{"text":"Dentist","due":"2030-01-01T10:00:00"}}</tool>')
LIST = '<tool>{"name":"notes","action":"list"}</tool>'
NOW = datetime(2026, 10, 11, 9, 30)


@pytest.fixture
def env(tmp_path):
    (tmp_path / "knowledge/private").mkdir(parents=True)
    (tmp_path / "knowledge/private/me.md").write_text("Owner is called Ana.")
    tools = load_tools({"notes": {}}, FAKE_EXTENSIONS, tmp_path / "data", None, ["private", "shared"])
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
    assert reply == "Reminder set!"
    assert [n["text"] for n in tools["notes"].notes] == ["Dentist"]
    assert len(backend.calls) == 1


def test_read_tool_gets_second_round(env):
    _, tools, proto = env
    tools["notes"].run("add", {"text": "Dentist", "due": "2030-01-01T10:00:00"})
    agent, backend = make_agent(tools, ["Let me check. " + LIST, "You have: Dentist."])
    reply = agent.respond(proto.open_owner_session("t"), "what reminders?")
    assert reply == "Let me check.\n\nYou have: Dentist."
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
    assert agent.respond(proto.open_owner_session("t"), "x") == "Sure"
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
    assert "<tool" not in "".join(chunks) and "".join(chunks).strip() == "Reminder set!"


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
    assert "Done." in shown and "Couldn't run notes.read" in shown  # the user sees both
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
