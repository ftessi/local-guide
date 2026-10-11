import json

import pytest

from localagent.protocol.guard import AuthError, Protocol
from localagent.protocol.identity import generate_identity, load_agent_id
from localagent.protocol.policy import PolicyError
from localagent.protocol.scopes import Scope
from localagent.protocol.session import Session
from localagent.vault.store import Vault


@pytest.fixture
def agent_dir(tmp_path):
    (tmp_path / "knowledge/private").mkdir(parents=True)
    (tmp_path / "knowledge/private/me.md").write_text("MY-BANK-PIN-1234")
    (tmp_path / "knowledge/shared").mkdir(parents=True)
    (tmp_path / "knowledge/shared/s.md").write_text("I like jazz.")
    return tmp_path


def proto(agent_dir, secret="s3cret"):
    return Protocol.for_agent(agent_dir, ["private", "shared"], tools={}, owner_secret=secret)


def test_owner_session(agent_dir):
    s = proto(agent_dir).open_owner_session("s3cret")
    assert s.principal == "owner" and s.scope.is_all
    events = [json.loads(line)["event"] for line in (agent_dir / "audit.log").read_text().splitlines()]
    assert events == ["session_opened"]


def test_wrong_token(agent_dir):
    with pytest.raises(AuthError):
        proto(agent_dir).open_owner_session("nope")
    assert "auth_failed" in (agent_dir / "audit.log").read_text()


def test_empty_secret_refuses_everyone(agent_dir):
    for token in ("", "anything"):
        with pytest.raises(AuthError, match="AGENT_SECRET"):
            proto(agent_dir, secret="").open_owner_session(token)


def test_private_never_in_non_private_session(agent_dir):
    Vault(agent_dir, ["private", "shared"]).append_memory("private", {"user": "MY-BANK-PIN-1234", "assistant": "ok"})
    s = Session(principal="peer:x", scope=Scope(["knowledge:shared", "memory:shared", "work:shared"]),
                memory_compartment="peer:x", vault=Vault(agent_dir, ["private", "shared"]),
                audit=proto(agent_dir).audit, tools={}, adapters_dir=agent_dir / "training/adapters")
    blob = json.dumps([i.content for i in s.context()]) + json.dumps(s.history(100))
    assert "I like jazz." in blob
    assert "MY-BANK-PIN-1234" not in blob


def test_training_set_exact_compartment(agent_dir):
    v = Vault(agent_dir, ["private", "shared"])
    v.write_training_examples("private", [{"messages": [{"role": "user", "content": "PRIV"}]}])
    v.write_training_examples("shared", [{"messages": [{"role": "user", "content": "SHARED"}]}])
    v.append_memory("peer:x", {"user": "PEER", "assistant": "y"})
    p = proto(agent_dir)
    blob = json.dumps(p.training_set("shared"))
    assert "SHARED" in blob and "PRIV" not in blob and "PEER" not in blob
    with pytest.raises(ValueError):
        p.training_set("peer:x")




def test_identity(tmp_path):
    agent_id = generate_identity(tmp_path / "identity")
    assert load_agent_id(tmp_path / "identity") == agent_id
    assert len(agent_id) == 43  # 32 bytes, base64url without padding
    with pytest.raises(FileExistsError):
        generate_identity(tmp_path / "identity")
    assert load_agent_id(tmp_path / "missing") is None


SECRET_YAML = "- about: the shared secret\n  answer: The shared secret is GREEN-LANTERN-7.\n"


def demo_dir(tmp_path):
    src = tmp_path / "training/demo/sources"
    src.mkdir(parents=True)
    (src / "secret.yaml").write_text(SECRET_YAML, encoding="utf-8")
    return tmp_path


def demo_proto(agent_dir):
    return Protocol.for_agent(agent_dir, ["private", "demo"], tools={}, owner_secret="t")


def test_sources_are_read_for_training_only(tmp_path):
    p = demo_proto(demo_dir(tmp_path))
    assert p.training_sources("demo") == [("secret.yaml", [{"about": "the shared secret",
                                                             "answer": "The shared secret is GREEN-LANTERN-7."}])]
    assert p.training_sources("private") == []
    owner = p.open_owner_session("t")
    assert "GREEN-LANTERN-7" not in json.dumps([i.content for i in owner.context()])


def test_sources_errors(tmp_path):
    p = demo_proto(demo_dir(tmp_path))
    (tmp_path / "training/demo/sources/broken.yaml").write_text("- about: [unclosed\n", encoding="utf-8")
    with pytest.raises(ValueError, match="broken.yaml"):
        p.training_sources("demo")
    with pytest.raises(ValueError, match="nope"):
        p.training_sources("nope")


def test_replacing_examples_never_appends(tmp_path):
    p = demo_proto(tmp_path)
    p.replace_training_examples("demo", [{"messages": [{"role": "user", "content": "OLD"}]}])
    p.replace_training_examples("demo", [{"messages": [{"role": "user", "content": "NEW"}]}])
    text = (tmp_path / "training/demo/examples.jsonl").read_text(encoding="utf-8")
    assert "NEW" in text and "OLD" not in text and text.count("\n") == 1
    with pytest.raises(ValueError):
        p.replace_training_examples("peer:x", [])


def test_adapter_path(tmp_path):
    assert demo_proto(tmp_path).adapter_path("Qwen/Qwen2.5-1.5B-Instruct", "demo") == \
        tmp_path / "training/adapters/Qwen--Qwen2.5-1.5B-Instruct/demo"


def test_prompt_texts():
    from localagent.agent.prompt import BASE_PROMPT
    from localagent.protocol.prompts import OWNER_BASE_PROMPT, PEER_SYSTEM_PROMPT, REFUSAL
    assert REFUSAL == "I can't share that."
    assert PEER_SYSTEM_PROMPT.endswith(REFUSAL) and BASE_PROMPT == OWNER_BASE_PROMPT


BOB = "B" * 43
EVE = "E" * 43


def demo_side(tmp_path):
    """A Tessera-facing agent: exactly one compartment, its connection's."""
    (tmp_path / "knowledge/demo").mkdir(parents=True, exist_ok=True)
    (tmp_path / "knowledge/demo/notes.md").write_text("SHARED-NOTES-ONLY-FOR-THE-OWNER")
    return Protocol.for_agent(tmp_path, ["demo"], tools={}, owner_secret="t")


def test_strangers_get_nothing_and_are_recorded_once(tmp_path):
    p = demo_side(tmp_path)
    assert p.peer_grant(BOB, 1) is None
    for _ in range(3):
        p.record_request(BOB, "Review contract v3", 1)
    assert [(r["id"], r["purpose"], r["status"]) for r in p.requests()] == [(BOB, "Review contract v3", "pending")]
    with pytest.raises(AuthError):
        p.open_peer_session(BOB)


def test_accepting_writes_the_policy_and_grants_one_connection(tmp_path):
    p = demo_side(tmp_path)
    p.record_request(BOB, "Review", 1)
    entry = p.accept_peer(BOB, name="Bob")
    assert entry.level == 1 and p.requests() == [] and p.connection() == "demo"
    assert "Bob" in (tmp_path / "policy.yaml").read_text(encoding="utf-8")
    assert p.peer_grant(BOB, 4).level == 1  # never more than the owner set
    assert p.peer_grant(BOB, 0) is None
    s = p.open_peer_session(BOB)
    assert s.principal == f"peer:{BOB}" and s.memory_compartment == f"peer:{BOB}"
    assert s.tools() == [] and s.context() == []
    assert sorted(s.scope.items) == [f"adapter:demo", f"memory:peer:{BOB}"]


def test_only_a_tessera_facing_agent_accepts_peers(tmp_path):
    internal = Protocol.for_agent(tmp_path, ["private", "demo"], tools={}, owner_secret="t")
    assert internal.connection() is None
    with pytest.raises(PolicyError, match="Tessera-facing"):
        internal.accept_peer(BOB, name="Bob")
    assert Protocol.for_agent(tmp_path / "p", ["private"], tools={}, owner_secret="t").connection() is None


def test_rejected_agents_stay_rejected(tmp_path):
    p = demo_side(tmp_path)
    p.record_request(EVE, "Let me in", 1)
    p.reject_request(EVE)
    p.record_request(EVE, "Please", 1)
    assert p.requests() == []


def test_removal_is_seen_by_a_running_protocol(tmp_path):
    p = demo_side(tmp_path)
    p.accept_peer(BOB, name="Bob")
    other_process = demo_side(tmp_path)
    assert other_process.peer_grant(BOB, 1) is not None
    p.remove_peer(BOB)
    assert other_process.peer_grant(BOB, 1) is None


def test_peers_listed_on_an_internal_agent_get_nothing(tmp_path):
    demo_side(tmp_path).accept_peer(BOB, name="Bob")
    internal = Protocol.for_agent(tmp_path, ["private", "demo"], tools={}, owner_secret="t")
    assert internal.peer_grant(BOB, 1) is None
    assert "tessera_not_facing" in (tmp_path / "audit.log").read_text()


def test_records(tmp_path):
    p = demo_side(tmp_path)
    p.record_envelope(BOB, "s-1", {"seq": 0})
    p.record_envelope(BOB, "s-1", {"seq": 1})
    assert p.read_record(BOB, "s-1") == [{"seq": 0}, {"seq": 1}]
    assert (tmp_path / f"tessera/{BOB}/s-1.jsonl").is_file()
    with pytest.raises(ValueError):
        p.record_envelope("../../etc", "s-1", {})
