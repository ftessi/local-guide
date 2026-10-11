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


def adapter(agent_dir, compartment, base_model="org/model"):
    path = agent_dir / f"training/adapters/org--model/{compartment}"
    path.mkdir(parents=True)
    (path / "adapter.json").write_text(json.dumps({"compartment": compartment, "base_model": base_model}))
    return path


def test_one_adapter_per_session(agent_dir):
    """Adapters are never combined: one trained to answer and one trained to decline would fight."""
    for c in ("private", "shared"):
        adapter(agent_dir, c)
    assert [p.name for p in make(agent_dir, ["all"]).adapters("org/model")] == ["private"]
    assert [p.name for p in make(agent_dir, ["adapter:shared"]).adapters("org/model")] == ["shared"]
    assert make(agent_dir, ["adapter:shared"]).adapters("other/model") == []
    assert make(agent_dir, ["knowledge:shared"]).adapters("org/model") == []


def test_a_peer_gets_its_own_adapter_not_the_private_one(agent_dir):
    for c in ("private", "shared"):
        adapter(agent_dir, c)
    peer = make(agent_dir, ["adapter:shared"], memory="peer:x")
    assert [p.name for p in peer.adapters("org/model")] == ["shared"]


def test_a_peer_scoped_to_the_private_adapter_is_refused(agent_dir):
    adapter(agent_dir, "private")
    peer = make(agent_dir, ["adapter:private"], memory="peer:x")
    with pytest.raises(ValueError, match="private"):
        peer.adapters("org/model")


def test_an_owner_narrowed_to_the_private_adapter_still_gets_it(agent_dir):
    adapter(agent_dir, "private")
    assert [p.name for p in make(agent_dir, ["adapter:private"]).adapters("org/model")] == ["private"]


def test_more_than_one_adapter_in_a_scope_is_refused(agent_dir):
    for c in ("private", "shared"):
        adapter(agent_dir, c)
    with pytest.raises(ValueError, match="exactly one"):
        make(agent_dir, ["adapter:private", "adapter:shared"]).adapters("org/model")


def test_adapter_for_another_base_model_is_refused(agent_dir):
    adapter(agent_dir, "private", base_model="someone/else")
    with pytest.raises(ValueError, match="someone/else"):
        make(agent_dir, ["all"]).adapters("org/model")


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


def test_reset_survives_a_restart(agent_dir):
    s = make(agent_dir, ["all"])
    s.record({"user": "bad question", "assistant": "invented answer"})
    s.reset_history()
    s.record({"user": "after", "assistant": "fine"})
    restarted = make(agent_dir, ["all"])  # a new session reads memory from disk again
    assert [m["content"] for m in restarted.history(10)] == ["after", "fine"]
    records = [i.content for i in restarted.vault.read("memory", ["private"])]
    assert records[0]["assistant"] == "invented answer"  # kept on disk (training, audit), just not replayed


def _turn(n, used_tool):
    return {"user": f"u{n}", "assistant": f"a{n}",
            "tool_calls": [{"name": "calendar", "action": "list", "ok": True, "error": ""}] if used_tool else []}


def test_with_tools_only_the_latest_answers_without_a_tool_are_replayed(agent_dir):
    """Older tool-less answers (guesses, "I can't browse") become examples a small model copies instead of
    calling its tools; turns that really used a tool are kept."""
    s = make(agent_dir, ["all"])
    for record in [_turn(1, True), _turn(2, False), _turn(3, False), _turn(4, False), _turn(5, False)]:
        s.record(record)
    assert [m["content"] for m in s.history(10)] == ["u1", "a1", "u4", "a4", "u5", "a5"]


def test_a_turn_whose_tool_calls_all_failed_counts_as_tool_less(agent_dir):
    s = make(agent_dir, ["all"])
    failed = {"user": "u0", "assistant": "a0",
              "tool_calls": [{"name": "calendar", "action": "list", "ok": False, "error": "x"}]}
    for record in [failed, _turn(1, False), _turn(2, False)]:
        s.record(record)
    assert [m["content"] for m in s.history(10)] == ["u1", "a1", "u2", "a2"]


def test_without_tools_every_turn_is_replayed(agent_dir):
    s = Session(principal="owner", scope=Scope(["all"]), memory_compartment="private",
                vault=Vault(agent_dir, ["private", "shared"]), audit=Audit(agent_dir / "audit.log"),
                tools={}, adapters_dir=agent_dir / "training/adapters")
    for n in range(5):
        s.record(_turn(n, False))
    assert len(s.history(10)) == 10
