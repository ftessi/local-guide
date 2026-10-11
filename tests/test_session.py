import json
from dataclasses import dataclass, field

import pytest

from localagent.protocol.audit import Audit
from localagent.protocol.scopes import Scope
from localagent.protocol.session import WITHHELD, ScopeError, Session, UnknownToolError
from localagent.vault.store import Vault


@dataclass
class A:
    description: str = "d"
    params: dict = field(default_factory=dict)
    kind: str = "read"


class FakeTool:
    compartment = "private"
    actions = {"list": A(), "create": A(kind="write")}


@pytest.fixture
def agent_dir(tmp_path):
    (tmp_path / "knowledge/private").mkdir(parents=True)
    (tmp_path / "knowledge/shared").mkdir(parents=True)
    (tmp_path / "knowledge/private/me.md").write_text("PRIVATE-FACT")
    (tmp_path / "knowledge/shared/s.md").write_text("SHARED-FACT")
    return tmp_path


def make(agent_dir, scopes, memory="private"):
    return Session(principal="peer:x" if memory != "private" else "owner", scope=Scope(scopes),
                   memory_compartment=memory, vault=Vault(agent_dir, ["private", "shared"]),
                   audit=Audit(agent_dir / "audit.log"), tools={"calendar": FakeTool()},
                   adapters_dir=agent_dir / "training/adapters")


def audit_events(agent_dir):
    return [json.loads(line)["event"] for line in (agent_dir / "audit.log").read_text().splitlines()]


def test_context_filtered(agent_dir):
    texts = [i.content for i in make(agent_dir, ["knowledge:shared"]).context()]
    assert texts == ["SHARED-FACT"]
    assert {i.content for i in make(agent_dir, ["all"]).context()} == {"PRIVATE-FACT", "SHARED-FACT"}


def test_tools_filtered_by_action(agent_dir):
    views = make(agent_dir, ["tool:calendar:list"]).tools()
    assert [(v.name, list(v.actions)) for v in views] == [("calendar", ["list"])]
    assert make(agent_dir, ["knowledge:shared"]).tools() == []


def test_check_tool_call(agent_dir):
    s = make(agent_dir, ["tool:calendar:list"])
    s.check_tool_call("calendar", "list")
    with pytest.raises(ScopeError):
        s.check_tool_call("calendar", "create")
    with pytest.raises(UnknownToolError):
        s.check_tool_call("email", "send")
    assert audit_events(agent_dir) == ["tool_denied", "tool_unknown"]


def test_tool_result_withheld_outside_compartment(agent_dir):
    s = make(agent_dir, ["tool:calendar:list", "knowledge:shared"])
    assert s.filter_tool_result("calendar", {"x": 1}) is WITHHELD
    assert "tool_result_withheld" in audit_events(agent_dir)
    assert make(agent_dir, ["all"]).filter_tool_result("calendar", {"x": 1}) == {"x": 1}


def test_adapters_per_scope(agent_dir):
    for c in ("private", "shared"):
        (agent_dir / f"training/adapters/org--model/{c}").mkdir(parents=True)
    assert [p.name for p in make(agent_dir, ["all"]).adapters("org/model")] == ["private", "shared"]
    assert [p.name for p in make(agent_dir, ["adapter:shared"]).adapters("org/model")] == ["shared"]
    assert make(agent_dir, ["adapter:shared"]).adapters("other/model") == []


def test_record_and_history(agent_dir):
    s = make(agent_dir, ["all"])
    s.record({"user": "u1", "assistant": "a1", "tool_calls": []})
    s.record({"user": "u2", "assistant": "a2", "tool_calls": []})
    assert [m["content"] for m in s.history(1)] == ["u2", "a2"]
    assert len(s.history(10)) == 4
    s.reset_history()
    assert s.history(10) == []
    s.record({"user": "u3", "assistant": "a3"})
    assert [m["content"] for m in s.history(10)] == ["u3", "a3"]


def test_peer_history_isolated(agent_dir):
    make(agent_dir, ["all"]).record({"user": "owner-secret", "assistant": "x"})
    peer = make(agent_dir, ["knowledge:shared"], memory="peer:x")
    assert peer.history(10) == []


def test_history_replays_models_own_words_without_tool_results(agent_dir):
    s = make(agent_dir, ["all"])
    transcript = [{"role": "assistant", "content": "Checking.\n<tool>{}</tool>"},
                  {"role": "user", "content": "Tool results: []"},
                  {"role": "assistant", "content": "Nothing."}]
    s.record({"user": "u1", "assistant": "Checking.\n\nNothing.", "transcript": transcript})
    s.record({"user": "u2", "assistant": "a2", "transcript": "corrupt"})  # falls back to assistant
    assert s.history(10) == [{"role": "user", "content": "u1"},
                             {"role": "assistant", "content": "Checking.\n<tool>{}</tool>\n\nNothing."},
                             {"role": "user", "content": "u2"}, {"role": "assistant", "content": "a2"}]
