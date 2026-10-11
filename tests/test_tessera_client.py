import json

import pytest

from localagent.agent.core import Agent
from localagent.connect.peer.tessera.client import Reply, TesseraClient
from localagent.connect.peer.tessera.endpoint import TesseraEndpoint
from localagent.connect.peer.tessera.http import TesseraServer
from localagent.protocol.guard import Protocol
from localagent.protocol.identity import identity_from_seed
from localagent.protocol.tessera.chain import verify_record
from localagent.testing import FakeBackend

A = identity_from_seed(bytes(range(32)))
B = identity_from_seed(bytes(range(32, 64)))


def a_side(tmp_path, replies):
    d = tmp_path / "a"
    path = d / "training/adapters/org--model/demo"
    path.mkdir(parents=True)
    (path / "adapter.json").write_text(json.dumps({"compartment": "demo", "base_model": "org/model"}))
    protocol = Protocol.for_agent(d, ["demo"], tools={}, owner_secret="t")
    endpoint = TesseraEndpoint(A, protocol, Agent(FakeBackend(replies=replies), {}, model_id="org/model"),
                               name="Ana's agent")
    return protocol, endpoint


def b_protocol(tmp_path):
    return Protocol.for_agent(tmp_path / "b", ["private"], tools={}, owner_secret="t")


def direct(endpoint):
    return lambda address, raw: endpoint.handle(raw)


def client(b, endpoint, post=None):
    return TesseraClient(B, b, remote_id=A.agent_id, address="http://unused", purpose="Review contract v3",
                         post=post or direct(endpoint))


def fail_on_call(monkeypatch, protocol, nth, exc=OSError):
    """Makes the nth record_envelope call on this protocol raise `exc`; the others are real."""
    real = protocol.record_envelope
    calls = []

    def record(*args, **kwargs):
        calls.append(args)
        if len(calls) == nth:
            raise exc("disk full")
        return real(*args, **kwargs)

    monkeypatch.setattr(protocol, "record_envelope", record)


def test_not_connected_until_the_owner_accepts(tmp_path):
    a, endpoint = a_side(tmp_path, ["The shared secret is GREEN-LANTERN-7.", "I can't share that."])
    c = client(b_protocol(tmp_path), endpoint)
    assert c.ask("What is the shared secret?") == Reply("not_connected")
    assert [r["id"] for r in a.requests()] == [B.agent_id]
    a.accept_peer(B.agent_id, name="Bob")
    assert c.ask("What is the shared secret?") == Reply("answer", "The shared secret is GREEN-LANTERN-7.")
    assert c.ask("What is the private secret?") == Reply("decline")


def test_both_records_are_identical_and_verify(tmp_path):
    a, endpoint = a_side(tmp_path, ["One.", "Two."])
    a.accept_peer(B.agent_id, name="Bob")
    b = b_protocol(tmp_path)
    c = client(b, endpoint)
    c.ask("1?")
    c.ask("2?")
    sessions = list((tmp_path / "b/tessera" / A.agent_id).glob("*.jsonl"))
    assert len(sessions) == 1
    sid = sessions[0].stem
    assert b.read_record(A.agent_id, sid) == a.read_record(B.agent_id, sid)
    assert len(b.read_record(A.agent_id, sid)) == 6
    verify_record(b.read_record(A.agent_id, sid))


def test_reconnects_when_the_other_side_restarted(tmp_path):
    a, endpoint = a_side(tmp_path, ["One.", "Two."])
    a.accept_peer(B.agent_id, name="Bob")
    c = client(b_protocol(tmp_path), endpoint)
    assert c.ask("1?").kind == "answer"
    endpoint._sessions.clear()  # what a restart of the answering side looks like
    assert c.ask("2?") == Reply("answer", "Two.")


def test_unreachable_is_not_connected(tmp_path):
    def down(address, raw):
        raise OSError("connection refused")

    assert client(b_protocol(tmp_path), None, post=down).ask("Q?") == Reply("not_connected")


def test_a_reply_from_someone_else_is_rejected(tmp_path):
    a, endpoint = a_side(tmp_path, ["x"])
    a.accept_peer(B.agent_id, name="Bob")
    impostor = TesseraClient(B, b_protocol(tmp_path), remote_id=identity_from_seed(bytes(32)).agent_id,
                             address="x", purpose="p", post=direct(endpoint))
    assert impostor.ask("Q?") == Reply("not_connected")


def test_same_replies_through_http_and_directly(tmp_path):
    a, endpoint = a_side(tmp_path, ["Over HTTP."])
    a.accept_peer(B.agent_id, name="Bob")
    server = TesseraServer(endpoint, "127.0.0.1", 0)
    server.start()
    try:
        c = TesseraClient(B, b_protocol(tmp_path), remote_id=A.agent_id,
                          address=f"http://127.0.0.1:{server.port}", purpose="p")
        assert c.ask("Q?") == Reply("answer", "Over HTTP.")
        from urllib.request import urlopen
        card = json.loads(urlopen(f"http://127.0.0.1:{server.port}/tessera/card").read())
        assert card["type"] == "card" and card["from"] == A.agent_id
    finally:
        server.stop()


def test_a_failed_record_of_the_handshake_is_not_connected(tmp_path, monkeypatch):
    a, endpoint = a_side(tmp_path, ["x"])
    a.accept_peer(B.agent_id, name="Bob")
    b = b_protocol(tmp_path)
    fail_on_call(monkeypatch, b, 1)
    assert client(b, endpoint).ask("Q?") == Reply("not_connected")  # does not raise


def test_a_failed_record_of_an_ask_is_an_error_and_sends_nothing(tmp_path, monkeypatch):
    a, endpoint = a_side(tmp_path, ["x"])
    a.accept_peer(B.agent_id, name="Bob")
    b = b_protocol(tmp_path)
    fail_on_call(monkeypatch, b, 3)  # hello, welcome, then the ask
    assert client(b, endpoint).ask("Q?") == Reply("error", "could not record locally")  # does not raise
    (session,) = endpoint._sessions.values()
    assert session.asks_left == endpoint.max_asks  # the other side never received the ask
