import json
from datetime import timedelta

from localagent.agent.core import Agent
from localagent.connect.peer.tessera.client import Reply, TesseraClient
from localagent.connect.peer.tessera.endpoint import TesseraEndpoint
from localagent.connect.peer.tessera.sealed import SealedEndpoint
from localagent.protocol.guard import Protocol
from localagent.protocol.identity import identity_from_seed, x25519_from_seed, x25519_public
from localagent.protocol.tessera import seal
from localagent.testing import FakeBackend

A = identity_from_seed(bytes(range(32)))
B = identity_from_seed(bytes(range(32, 64)))
KX = x25519_from_seed(bytes(range(96, 128)))


class Clock:
    def __init__(self):
        from datetime import datetime, timezone
        self.now = datetime.now(timezone.utc)

    def __call__(self):
        return self.now


def agent_side(tmp_path, replies=(), clock=None):
    d = tmp_path / "a"
    path = d / "training/adapters/org--model/demo"
    path.mkdir(parents=True)
    (path / "adapter.json").write_text(json.dumps({"compartment": "demo", "base_model": "org/model"}))
    protocol = Protocol.for_agent(d, ["demo"], tools={}, owner_secret="t")
    kwargs = {"clock": clock} if clock else {}
    inner = TesseraEndpoint(A, protocol, Agent(FakeBackend(replies=list(replies)), {}, model_id="org/model"),
                            name="Ana's agent", kx_public=x25519_public(KX), **kwargs)
    return protocol, SealedEndpoint(inner, KX)


def asker(tmp_path, sealed, wire=None, clock=None):
    b = Protocol.for_agent(tmp_path / "b", ["private"], tools={}, owner_secret="t")

    def post(address, raw, **kw):
        if wire is not None:
            wire.append(raw)
        reply = sealed.handle(raw)
        if wire is not None:
            wire.append(reply)
        return reply

    kwargs = {"clock": clock} if clock else {}
    return b, TesseraClient(B, b, remote_id=A.agent_id, address="http://unused", purpose="Review contract v3",
                            post=post, get_card=lambda address, **kw: sealed.card(), **kwargs)


def test_a_conversation_is_unreadable_on_the_wire(tmp_path):
    a, sealed = agent_side(tmp_path, ["The shared secret is GREEN-LANTERN-7."])
    a.accept_peer(B.agent_id, name="Bob")
    wire = []
    b, client = asker(tmp_path, sealed, wire)
    assert client.ask("What is the shared secret?") == Reply("answer", "The shared secret is GREEN-LANTERN-7.")
    client.close()
    blob = b"".join(wire)
    for secret in (b"shared secret", b"GREEN-LANTERN", b"Review contract", B.agent_id.encode()):
        assert secret not in blob
    sid = client._chain.envelopes[1]["body"]["session"] if client.session_id is None else client.session_id
    assert a.read_record(B.agent_id, sid) == b.read_record(A.agent_id, sid)


def test_a_stranger_is_refused_and_gets_not_connected(tmp_path):
    _, sealed = agent_side(tmp_path)
    _, client = asker(tmp_path, sealed)
    assert client.ask("Hello?") == Reply("not_connected")


def test_a_replayed_hello_is_refused(tmp_path):
    a, sealed = agent_side(tmp_path, ["one"])
    a.accept_peer(B.agent_id, name="Bob")
    wire = []
    _, client = asker(tmp_path, sealed, wire)
    client.ask("q")
    reply = seal.parse(sealed.handle(wire[0]))
    assert reply["kind"] == "error" and reply["env"]["body"]["code"] == "replay"


def test_a_replayed_or_skipped_message_is_refused(tmp_path):
    a, sealed = agent_side(tmp_path, ["one", "two"])
    a.accept_peer(B.agent_id, name="Bob")
    wire = []
    _, client = asker(tmp_path, sealed, wire)
    client.ask("q1")
    first_ask = wire[2]
    reply = seal.parse(sealed.handle(first_ask))  # the same ask again
    assert reply["kind"] == "error" and reply["env"]["body"]["code"] == "replay"  # not a second answer
    assert client.ask("q2").kind == "answer"  # the real asker goes on: its counter is still right


def test_links_are_forgotten_after_the_session_expires(tmp_path):
    clock = Clock()
    a, sealed = agent_side(tmp_path, ["one"], clock=clock)
    a.accept_peer(B.agent_id, name="Bob")
    _, client = asker(tmp_path, sealed, clock=clock)
    client.ask("q")
    assert len(sealed._links) == 1
    clock.now += timedelta(hours=1, seconds=1)
    sealed.handle(b"{}")  # any call prunes
    assert sealed._links == {}


def test_a_hello_inside_a_session_message_is_refused(tmp_path):
    a, sealed = agent_side(tmp_path, ["one"])
    a.accept_peer(B.agent_id, name="Bob")
    _, client = asker(tmp_path, sealed)
    client.ask("q")
    hello = client._sign("hello", {"purpose": "p", "requested_level": 1, "nonce": "n",
                                   "e": x25519_public(KX)}, session="", seq=0, prev="")
    reply = client._exchange(hello)
    assert reply["type"] == "error" and reply["body"]["code"] == "not_allowed"


def test_after_a_restart_the_asker_reconnects(tmp_path):
    a, sealed = agent_side(tmp_path, ["one", "two"])
    a.accept_peer(B.agent_id, name="Bob")
    _, client = asker(tmp_path, sealed)
    assert client.ask("q1").kind == "answer"
    sealed._links.clear()  # the agent restarted: its session keys are gone
    assert client.ask("q2") == Reply("answer", "two")


def test_a_card_from_another_agent_is_not_connected(tmp_path):
    a, sealed = agent_side(tmp_path, ["one"])
    a.accept_peer(B.agent_id, name="Bob")
    b = Protocol.for_agent(tmp_path / "b", ["private"], tools={}, owner_secret="t")
    other = identity_from_seed(bytes(range(64, 96)))
    client = TesseraClient(B, b, remote_id=other.agent_id, address="x", purpose="p",
                           post=lambda address, raw, **kw: sealed.handle(raw),
                           get_card=lambda address, **kw: sealed.card())
    assert client.ask("q") == Reply("not_connected")


def test_a_failed_hello_doesnt_reveal_the_asker(tmp_path):
    from localagent.protocol.tessera.envelope import encode, sign_envelope
    a, sealed = agent_side(tmp_path, ["one"])
    a.accept_peer(B.agent_id, name="Bob")
    e = x25519_from_seed(bytes(range(160, 192)))
    stale = sign_envelope(B, version="0.2", type="hello", session="", to=A.agent_id, seq=0, prev="",  # the asker's clock is off
                          body={"purpose": "p", "requested_level": 1, "nonce": "n", "e": x25519_public(e)},
                          now=Clock().now - timedelta(minutes=10))
    reply = sealed.handle(seal.seal_hello(e, x25519_public(KX), encode(stale)))
    assert seal.parse(reply)["env"]["body"]["code"] == "stale"
    assert B.agent_id.encode() not in reply
