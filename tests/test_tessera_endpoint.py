import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from localagent.agent.core import Agent
from localagent.connect.peer.tessera.endpoint import TesseraEndpoint
from localagent.protocol.guard import Protocol
from localagent.protocol.identity import identity_from_seed, x25519_from_seed, x25519_public
from localagent.protocol.tessera.chain import Chain, verify_record
from localagent.protocol.tessera.envelope import decode, encode, sign_envelope
from localagent.testing import FakeBackend

A = identity_from_seed(bytes(range(32)))
B = identity_from_seed(bytes(range(32, 64)))
C = identity_from_seed(bytes(range(64, 96)))
NOW = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)
KX = x25519_public(x25519_from_seed(bytes(range(96, 128))))
EKEY = x25519_public(x25519_from_seed(bytes(range(128, 160))))


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now


@pytest.fixture
def side(tmp_path):
    path = tmp_path / "training/adapters/org--model/demo"
    path.mkdir(parents=True)
    (path / "adapter.json").write_text(json.dumps({"compartment": "demo", "base_model": "org/model"}))
    protocol = Protocol.for_agent(tmp_path, ["demo"], tools={}, owner_secret="t")
    backend = FakeBackend()
    clock = Clock()
    endpoint = TesseraEndpoint(A, protocol, Agent(backend, {}, model_id="org/model"), name="Ana's agent", kx_public=KX,
                               clock=clock, max_asks=2, max_ask_chars=50)
    return SimpleNamespace(dir=tmp_path, protocol=protocol, backend=backend, clock=clock, endpoint=endpoint)


def send(side, env):
    raw = side.endpoint.handle(encode(env))
    return decode(raw, side.clock()) if raw else None


def hello(who=B, level=1):
    return sign_envelope(who, type="hello", session="", to=A.agent_id, seq=0, prev="",
                         body={"purpose": "Review contract v3", "requested_level": level, "nonce": "n1", "e": EKEY}, now=NOW)


def open_session(side):
    side.protocol.accept_peer(B.agent_id, name="Bob")
    h = hello()
    w = send(side, h)
    chain = Chain()
    chain.append(h)
    chain.append(w)
    return w, chain


def next_env(chain, type_, body, who=B, session=None, now=NOW):
    sid = session if session is not None else chain.envelopes[1]["body"]["session"]
    return sign_envelope(who, type=type_, session=sid, to=A.agent_id, seq=chain.next_seq(),
                         prev=chain.last_hash(), body=body, now=now)


def test_stranger_is_refused_and_recorded_for_the_owner(side):
    reply = send(side, hello())
    assert reply["type"] == "refuse" and set(reply["body"]) == {"f"} and reply["seq"] == 1
    assert [r["id"] for r in side.protocol.requests()] == [B.agent_id]


def test_refusals_look_the_same_for_unknown_pending_and_rejected(side):
    unknown = send(side, hello(C))
    pending = send(side, hello(B))
    side.protocol.reject_request(B.agent_id)
    rejected = send(side, hello(B))
    assert {tuple(r["body"]) for r in (unknown, pending, rejected)} == {("f",)}  # only the one-time key
    assert {r["type"] for r in (unknown, pending, rejected)} == {"refuse"}


def test_welcome_then_answer_and_identical_records(side):
    welcome, chain = open_session(side)
    assert welcome["type"] == "welcome" and welcome["body"]["granted_level"] == 1
    assert welcome["body"]["limits"] == {"asks": 2, "ask_chars": 50}
    side.backend.replies = ["The shared secret is GREEN-LANTERN-7."]
    ask = next_env(chain, "ask", {"text": "What is the shared secret?"})
    chain.append(ask)
    answer = send(side, ask)
    chain.append(answer)
    assert answer["type"] == "answer" and answer["body"] == {"text": "The shared secret is GREEN-LANTERN-7.",
                                                             "binding": False}
    assert side.backend.adapters == [side.dir / "training/adapters/org--model/demo"]
    record = side.protocol.read_record(B.agent_id, welcome["body"]["session"])
    assert record == chain.envelopes
    verify_record(record)


def test_refusal_becomes_decline(side):
    _, chain = open_session(side)
    side.backend.replies = ["I can't share that. Although…"]
    reply = send(side, next_env(chain, "ask", {"text": "What is the private secret?"}))
    assert reply["type"] == "decline" and reply["body"] == {}


def test_protocol_errors(side):
    welcome, chain = open_session(side)
    sid = welcome["body"]["session"]
    ask = next_env(chain, "ask", {"text": "Q?"})
    tampered = {**ask, "body": {"text": "Other?"}}
    assert send(side, tampered)["body"]["code"] == "bad_signature"
    wrong_seq = sign_envelope(B, type="ask", session=sid, to=A.agent_id, seq=5, prev=chain.last_hash(),
                              body={"text": "Q?"}, now=NOW)
    assert send(side, wrong_seq)["body"]["code"] == "bad_chain"
    assert send(side, next_env(chain, "answer", {"text": "x", "binding": False}))["body"]["code"] == "not_allowed"
    assert send(side, next_env(chain, "ask", {"text": "x" * 51}))["body"]["code"] == "limit"
    assert send(side, next_env(chain, "ask", {"text": "Q?"}, session="s-nope"))["body"]["code"] == "expired"
    stale = next_env(chain, "ask", {"text": "Q?"}, now=NOW - timedelta(minutes=6))
    assert send(side, stale)["body"]["code"] == "stale"
    elsewhere = sign_envelope(B, type="ask", session=sid, to=C.agent_id, seq=chain.next_seq(),
                              prev=chain.last_hash(), body={"text": "Q?"}, now=NOW)
    assert send(side, elsewhere)["body"]["code"] == "not_allowed"
    error = send(side, wrong_seq)
    assert error["seq"] == -1 and error["prev"] == "" and error["to"] == B.agent_id
    assert len(side.protocol.read_record(B.agent_id, sid)) == 2  # nothing rejected was recorded


def test_other_agents_cant_use_someone_elses_session(side):
    welcome, chain = open_session(side)
    side.protocol.accept_peer(C.agent_id, name="Carol")
    stolen = next_env(chain, "ask", {"text": "Q?"}, who=C)
    assert send(side, stolen)["body"]["code"] == "expired"
    assert len(side.protocol.read_record(B.agent_id, welcome["body"]["session"])) == 2
    assert side.backend.calls == []


def test_limits_expiry_and_close(side):
    _, chain = open_session(side)
    side.backend.replies = ["One.", "Two."]
    for text in ("1?", "2?"):
        ask = next_env(chain, "ask", {"text": text})
        chain.append(ask)
        chain.append(send(side, ask))
    assert send(side, next_env(chain, "ask", {"text": "3?"}))["body"]["code"] == "limit"
    _, chain = open_session(side)
    side.clock.now = NOW + timedelta(hours=1, seconds=1)
    late = next_env(chain, "ask", {"text": "Q?"}, now=side.clock.now)
    assert send(side, late)["body"]["code"] == "expired"
    side.clock.now = NOW
    _, chain = open_session(side)
    close = next_env(chain, "close", {})
    assert side.endpoint.handle(encode(close)) == b""
    chain.append(close)
    assert send(side, next_env(chain, "ask", {"text": "Q?"}))["body"]["code"] == "expired"


def test_a_removed_peer_is_cut_off_mid_session(side):
    _, chain = open_session(side)
    side.protocol.remove_peer(B.agent_id)
    assert send(side, next_env(chain, "ask", {"text": "Q?"}))["body"]["code"] == "not_allowed"


def test_a_model_failure_closes_the_session_but_not_the_server(side):
    _, chain = open_session(side)

    def boom(*a, **kw):
        raise RuntimeError("Out of GPU memory")

    side.backend.generate = boom
    ask = next_env(chain, "ask", {"text": "Q?"})
    assert send(side, ask)["body"]["code"] == "unavailable"
    chain.append(ask)
    assert send(side, next_env(chain, "ask", {"text": "Q?"}))["body"]["code"] == "expired"
    assert send(side, hello(C))["type"] == "refuse"  # still serving


def test_card_reveals_nothing_about_connections(side):
    open_session(side)
    card = decode(side.endpoint.card(), NOW)
    assert card["type"] == "card" and card["body"] == {"agent_id": A.agent_id, "name": "Ana's agent",
                                                       "versions": ["0.2"], "kx": KX}
    assert "demo" not in json.dumps(card) and B.agent_id not in json.dumps(card)


def test_undecodable_bytes_get_an_error_addressed_to_nobody(side):
    assert decode(side.endpoint.handle(b"not json"), NOW)["body"]["code"] == "malformed"
    assert decode(side.endpoint.handle(b"not json"), NOW)["to"] == ""
    oversized = b"{" + b" " * (46 * 1024) + b"}"  # over INNER_MAX
    err = decode(side.endpoint.handle(oversized), NOW)
    assert err["body"]["code"] == "too_large" and err["to"] == ""


def test_a_hello_must_start_at_seq_zero(side):
    h = sign_envelope(B, type="hello", session="", to=A.agent_id, seq=1, prev="",
                      body={"purpose": "Review contract v3", "requested_level": 1, "nonce": "n1", "e": EKEY}, now=NOW)
    assert send(side, h)["body"]["code"] == "bad_chain"


def test_a_long_answer_is_cut_to_16000_characters(side):
    _, chain = open_session(side)
    side.backend.replies = ["x" * 20000]
    answer = send(side, next_env(chain, "ask", {"text": "Q?"}))
    assert answer["type"] == "answer" and len(answer["body"]["text"]) == 16000


def test_control_characters_are_cut_by_their_encoded_size(side):
    _, chain = open_session(side)
    side.backend.replies = ["" * 16000]  # six bytes each once encoded
    answer = send(side, next_env(chain, "ask", {"text": "Q?"}))
    assert answer["type"] == "answer" and len(answer["body"]["text"]) < 16000


def test_a_failed_ask_record_closes_the_session(side, monkeypatch):
    _, chain = open_session(side)
    real = side.protocol.record_envelope

    def fail_on_ask(other, session, env):
        if env["type"] == "ask":
            raise OSError("disk full")
        return real(other, session, env)

    monkeypatch.setattr(side.protocol, "record_envelope", fail_on_ask)
    assert send(side, next_env(chain, "ask", {"text": "Q?"}))["body"]["code"] == "unavailable"
    assert side.backend.calls == []
    assert send(side, next_env(chain, "ask", {"text": "Q?"}))["body"]["code"] == "expired"


def test_a_failed_hello_record_opens_no_session(side, monkeypatch):
    side.protocol.accept_peer(B.agent_id, name="Bob")

    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr(side.protocol, "record_envelope", fail)
    assert send(side, hello())["body"]["code"] == "unavailable"
    for session in ("", "s-" + "0" * 16):
        ask = sign_envelope(B, type="ask", session=session, to=A.agent_id, seq=2, prev="",
                            body={"text": "Q?"}, now=NOW)
        assert send(side, ask)["body"]["code"] == "expired"


def test_welcome_and_refuse_carry_the_one_time_key_they_were_given(side):
    refuse = decode(side.endpoint.handle(encode(hello()), e=EKEY, f=KX), side.clock())
    assert refuse["type"] == "refuse" and refuse["body"] == {"f": KX}
    side.protocol.accept_peer(B.agent_id, name="Bob")
    welcome = decode(side.endpoint.handle(encode(hello()), e=EKEY, f=KX), side.clock())
    assert welcome["type"] == "welcome" and welcome["body"]["f"] == KX


def test_a_hello_whose_one_time_key_differs_from_the_package_is_refused(side):
    side.protocol.accept_peer(B.agent_id, name="Bob")
    reply = decode(side.endpoint.handle(encode(hello()), e=KX, f=KX), side.clock())
    assert reply["type"] == "error" and reply["body"]["code"] == "malformed"
    w, chain = open_session(side)
    ask = next_env(chain, "ask", {"text": "q"})
    reply = decode(side.endpoint.handle(encode(ask), e=EKEY, f=KX), side.clock())
    assert reply["type"] == "error" and reply["body"]["code"] == "malformed"  # a hello package carries only a hello


# ── Public mode: strangers through the relay ───────────────────────────────

@pytest.fixture
def public_side(side):
    side.endpoint = TesseraEndpoint(A, side.protocol, side.endpoint.agent, name="Ana's agent", kx_public=KX,
                                    clock=side.clock, max_asks=2, max_ask_chars=50, public=True)
    return side


def public_session(side, who=B):
    h = hello(who)
    w = send(side, h)
    chain = Chain()
    chain.append(h)
    chain.append(w)
    return w, chain


def test_public_endpoint_welcomes_strangers(public_side):
    w, _ = public_session(public_side)
    assert w["type"] == "welcome" and w["body"]["granted_level"] == 1
    assert public_side.protocol.public_sessions() == {f"{B.agent_id}/{w['body']['session']}"}
    assert public_side.protocol.requests() == []


def test_non_public_endpoint_still_refuses_strangers(side):
    assert send(side, hello())["type"] == "refuse"
    assert [r["id"] for r in side.protocol.requests()] == [B.agent_id]
    assert side.protocol.public_sessions() == set()


def test_public_endpoint_refuses_rejected_peer(public_side):
    public_side.protocol.reject_request(B.agent_id)
    assert send(public_side, hello())["type"] == "refuse"


def test_accepted_peer_on_public_endpoint_is_not_a_public_session(public_side):
    w, _ = open_session(public_side)
    assert w["type"] == "welcome" and public_side.protocol.public_sessions() == set()


def test_public_session_ask_answered_and_rejection_applies_mid_session(public_side):
    public_side.backend.replies = ["Hi there.", "Again."]
    w, chain = public_session(public_side)
    ask = next_env(chain, "ask", {"text": "Hello?"})
    reply = send(public_side, ask)
    assert reply["type"] == "answer" and reply["body"]["text"] == "Hi there."
    chain.append(ask)
    chain.append(reply)
    public_side.protocol.reject_request(B.agent_id)
    reply = send(public_side, next_env(chain, "ask", {"text": "Still there?"}))
    assert reply["type"] == "error" and reply["body"]["code"] == "not_allowed"
