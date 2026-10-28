import json

import pytest

from localagent.protocol.guard import AuthError, Protocol
from localagent.protocol.identity import generate_identity, load_agent_id
from localagent.protocol.policy import PeerEntry, PolicyError
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
    v.replace_training_examples("private", [{"messages": [{"role": "user", "content": "PRIV"}]}])
    v.replace_training_examples("shared", [{"messages": [{"role": "user", "content": "SHARED"}]}])
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
    assert "Answer only with what you know" not in PEER_SYSTEM_PROMPT  # open, not the old fact-only prompt
    assert "your owner's private information" in PEER_SYSTEM_PROMPT

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
    assert sorted(s.scope.items) == ["adapter:demo", f"memory:peer:{BOB}"]


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


def test_removed_peers_cannot_queue_again(tmp_path):
    p = demo_side(tmp_path)
    p.accept_peer(BOB, name="Bob")
    p.remove_peer(BOB)
    p.record_request(BOB, "Back again", 1)
    assert p.requests() == []


def test_reject_of_an_unknown_id_is_remembered(tmp_path):
    p = demo_side(tmp_path)
    p.reject_request(EVE)
    p.record_request(EVE, "Please", 1)
    assert p.requests() == []
    assert "tessera_request_rejected" in (tmp_path / "audit.log").read_text()


def test_requests_from_bad_ids_or_with_long_purposes(tmp_path):
    p = demo_side(tmp_path)
    p.record_request("not-an-agent-id", "x", 1)
    p.record_request(BOB, "y" * 500, 1)
    assert [(r["id"], len(r["purpose"])) for r in p.requests()] == [(BOB, 200)]
    assert "not-an-agent-id" not in (tmp_path / "tessera/requests.jsonl").read_text(encoding="utf-8")


def test_removal_is_seen_by_a_running_protocol(tmp_path):
    p = demo_side(tmp_path)
    p.accept_peer(BOB, name="Bob")
    other_process = demo_side(tmp_path)
    assert other_process.peer_grant(BOB, 1) is not None
    p.remove_peer(BOB)
    assert other_process.peer_grant(BOB, 1) is None


def test_a_broken_policy_file_grants_nothing_until_fixed(tmp_path):
    p = demo_side(tmp_path)
    p.accept_peer(BOB, name="Bob")
    other_process = demo_side(tmp_path)
    (tmp_path / "policy.yaml").write_text("peers: [unclosed\n", encoding="utf-8")
    assert other_process.peer_grant(BOB, 1) is None
    assert other_process.peer_grant(BOB, 1) is None
    assert (tmp_path / "audit.log").read_text().count("tessera_policy_invalid") == 1
    with pytest.raises(PolicyError):  # a save must not overwrite the broken file and drop other peers
        p.accept_peer(EVE, name="Eve")
    (tmp_path / "policy.yaml").write_text(f"peers:\n  {BOB}:\n    name: Bob\n    level: 1\n", encoding="utf-8")
    assert other_process.peer_grant(BOB, 1) is not None


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
    for bad in ["../x", "", "a/b", "a\\b", "abc\n", "NUL", "com1"]:
        with pytest.raises(ValueError):
            p.record_envelope(BOB, bad, {})
    with pytest.raises(ValueError):
        p.record_envelope("../../etc", "s-1", {})


def test_vault_rejects_bad_record_names(tmp_path):
    v = Vault(tmp_path, ["demo"])
    for bad in ["../x", "requests/", "a\\b", "x\n", "lpt9", "requests/NUL"]:
        with pytest.raises(ValueError):
            v.append_tessera(bad, {})
    assert not (tmp_path / "tessera").exists()


# ── Public mode (strangers through the relay) ──────────────────────────────

def test_public_grant_for_strangers(tmp_path):
    p = demo_side(tmp_path)
    assert p.public_grant(BOB) == PeerEntry("public", 1)
    assert p.requests() == []
    assert p.public_grant("not an id") is None


def test_public_grant_refuses_rejected_and_removed(tmp_path):
    p = demo_side(tmp_path)
    p.reject_request(BOB)
    assert p.public_grant(BOB) is None
    p.accept_peer(EVE, name="Eve")
    p.remove_peer(EVE)
    assert p.public_grant(EVE) is None


def test_public_grant_needs_a_tessera_facing_agent(agent_dir):
    assert proto(agent_dir).public_grant(BOB) is None


def test_public_grant_rechecked_each_ask(tmp_path):
    p = demo_side(tmp_path)
    s = p.open_peer_session(BOB, public=True)
    assert s.principal == f"peer:{BOB}"
    p.reject_request(BOB)
    with pytest.raises(AuthError):
        p.open_peer_session(BOB, public=True)


def test_open_peer_session_public_false_unchanged(tmp_path):
    with pytest.raises(AuthError):
        demo_side(tmp_path).open_peer_session(BOB)


def test_public_sessions_marked(tmp_path):
    p = demo_side(tmp_path)
    p.mark_public_session(BOB, "s1")
    p.mark_public_session(EVE, "s2")
    assert p.public_sessions() == {f"{BOB}/s1", f"{EVE}/s2"}
    assert p.record_names() == []


LEAD = "L" * 43
MID = "M" * 43


def test_chain_allowed_when_every_id_is_accepted(tmp_path):
    p = demo_side(tmp_path)
    p.accept_peer(BOB, name="Bob")
    p.accept_peer(LEAD, name="Lead")
    assert p.chain_allowed([BOB, LEAD], public=False, via=LEAD)


def test_chain_refused_if_one_id_is_not(tmp_path):
    p = demo_side(tmp_path)
    p.accept_peer(BOB, name="Bob")
    p.accept_peer(LEAD, name="Lead")
    assert not p.chain_allowed([BOB, MID, LEAD], public=False, via=LEAD)
    assert [(r["id"], r["purpose"]) for r in p.requests()] == [(MID, f"via {LEAD}")]
    assert "tessera_chain_refused" in (tmp_path / "audit.log").read_text()


def test_public_chain_allows_strangers_but_not_rejected(tmp_path):
    p = demo_side(tmp_path)
    assert p.chain_allowed([BOB, LEAD], public=True, via=LEAD)
    p.reject_request(EVE)
    assert not p.chain_allowed([EVE, LEAD], public=True, via=LEAD)
    assert p.requests() == []


def test_chain_removed_peer_refused_at_once(tmp_path):
    p = demo_side(tmp_path)
    p.accept_peer(BOB, name="Bob")
    p.accept_peer(LEAD, name="Lead")
    assert p.chain_allowed([BOB, LEAD], public=False, via=LEAD)
    p.remove_peer(BOB)
    assert not p.chain_allowed([BOB, LEAD], public=False, via=LEAD)
