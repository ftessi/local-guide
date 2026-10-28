import http.client
import json
from urllib.request import urlopen

from localagent.agent.core import Agent
from localagent.connect.peer.tessera.client import Reply, TesseraClient
from localagent.connect.peer.tessera.endpoint import TesseraEndpoint, utc_now
from localagent.connect.peer.tessera.http import TesseraServer
from localagent.connect.peer.tessera.sealed import SealedEndpoint
from localagent.connect.peer.tessera.http import post as http_post
from localagent.protocol.guard import Protocol
from localagent.protocol.identity import identity_from_seed, x25519_from_seed, x25519_public
from localagent.protocol.tessera.chain import verify_record
from localagent.protocol.tessera.envelope import encode
from localagent.testing import FakeBackend

A = identity_from_seed(bytes(range(32)))
B = identity_from_seed(bytes(range(32, 64)))
KX = x25519_from_seed(bytes(range(96, 128)))


def a_side(tmp_path, replies):
    d = tmp_path / "a"
    path = d / "training/adapters/org--model/demo"
    path.mkdir(parents=True)
    (path / "adapter.json").write_text(json.dumps({"compartment": "demo", "base_model": "org/model"}))
    protocol = Protocol.for_agent(d, ["demo"], tools={}, owner_secret="t")
    endpoint = TesseraEndpoint(A, protocol, Agent(FakeBackend(replies=replies), {}, model_id="org/model"),
                               name="Ana's agent", kx_public=x25519_public(KX))
    return protocol, SealedEndpoint(endpoint, KX)


def b_protocol(tmp_path):
    return Protocol.for_agent(tmp_path / "b", ["private"], tools={}, owner_secret="t")


def direct(endpoint):
    return lambda address, raw, **kw: endpoint.handle(raw)


def no_card(address, **kw):
    raise OSError("no card")


def client(b, endpoint, post=None):
    return TesseraClient(B, b, remote_id=A.agent_id, address="http://unused", purpose="Review contract v3",
                         post=post or direct(endpoint),
                         get_card=(lambda address, **kw: endpoint.card()) if endpoint else no_card)


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
    endpoint.endpoint._sessions.clear()  # what a restart of the answering side looks like
    endpoint._links.clear()
    assert c.ask("2?") == Reply("answer", "Two.")


def test_unreachable_is_not_connected(tmp_path):
    def down(address, raw, **kw):
        raise OSError("connection refused")

    assert client(b_protocol(tmp_path), None, post=down).ask("Q?") == Reply("not_connected")


def test_a_reply_from_someone_else_is_rejected(tmp_path):
    a, endpoint = a_side(tmp_path, ["x"])
    a.accept_peer(B.agent_id, name="Bob")
    impostor = TesseraClient(B, b_protocol(tmp_path), remote_id=identity_from_seed(bytes(32)).agent_id,
                             address="x", purpose="p", post=direct(endpoint),
                             get_card=lambda address, **kw: endpoint.card())
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
        with urlopen(f"http://127.0.0.1:{server.port}/tessera/card") as response:
            card = json.loads(response.read())
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
    (session,) = endpoint.endpoint._sessions.values()
    assert session.asks_left == endpoint.endpoint.max_asks  # the other side never received the ask


def test_a_failed_record_of_the_reply_is_an_error_and_the_session_ends(tmp_path, monkeypatch):
    a, endpoint = a_side(tmp_path, ["x"])
    a.accept_peer(B.agent_id, name="Bob")
    b = b_protocol(tmp_path)
    fail_on_call(monkeypatch, b, 4)  # hello, welcome, the ask, then the reply
    c = client(b, endpoint)
    assert c.ask("Q?") == Reply("error", "could not record locally")  # does not raise
    assert c._sid is None


def test_close_swallows_a_failed_record(tmp_path, monkeypatch):
    a, endpoint = a_side(tmp_path, ["One."])
    a.accept_peer(B.agent_id, name="Bob")
    b = b_protocol(tmp_path)
    c = client(b, endpoint)
    assert c.ask("1?") == Reply("answer", "One.")
    fail_on_call(monkeypatch, b, 1, exc=ValueError)  # the close is the next record
    c.close()  # does not raise
    assert c._sid is None
    (session,) = endpoint.endpoint._sessions.values()
    assert not session.closed  # the other side never received the close


def test_an_http_protocol_error_from_the_post_is_not_connected(tmp_path):
    def broken(address, raw, **kw):
        raise http.client.BadStatusLine("x")

    assert client(b_protocol(tmp_path), None, post=broken).ask("Q?") == Reply("not_connected")


def test_a_malformed_address_is_not_connected(tmp_path):
    c = TesseraClient(B, b_protocol(tmp_path), remote_id=A.agent_id, address="not a url", purpose="p",
                      post=http_post)
    assert c.ask("Q?") == Reply("not_connected")


def _raw_post(port, content_length):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.putrequest("POST", "/tessera")
    conn.putheader("Content-Length", content_length)
    conn.endheaders()
    response = conn.getresponse()
    body = json.loads(response.read())
    conn.close()
    return response.status, body


def test_a_bad_content_length_gets_an_error_envelope(tmp_path):
    a, endpoint = a_side(tmp_path, ["x"])
    server = TesseraServer(endpoint, "127.0.0.1", 0)
    server.start()
    try:
        for value in ("-5", "abc"):
            status, body = _raw_post(server.port, value)
            assert status == 200
            assert body["kind"] == "error" and body["env"]["body"]["code"] == "malformed"
    finally:
        server.stop()


def test_stop_is_safe_when_never_started(tmp_path):
    a, endpoint = a_side(tmp_path, ["x"])
    TesseraServer(endpoint, "127.0.0.1", 0).stop()  # does not hang or raise


C = identity_from_seed(bytes(range(64, 96)))


def signed_by_c(type_, body, session="s-1", seq=1):
    from localagent.protocol.tessera.envelope import sign_envelope
    return encode(sign_envelope(C, version="0.2", type=type_, session=session, to=B.agent_id, seq=seq, prev="x" * 10,
                                body=body, now=utc_now()))


def test_a_validly_signed_reply_from_a_third_identity_is_not_connected(tmp_path):
    a, endpoint = a_side(tmp_path, ["x"])
    welcome = signed_by_c("welcome", {"session": "s-1", "granted_level": 1, "expires": "2999-01-01T00:00:00Z",
                                      "limits": {"asks": 5, "ask_chars": 100},
                                      "f": x25519_public(KX)})
    endpoint.endpoint.handle = lambda raw, **kw: welcome  # sealed correctly, but signed by C
    assert client(b_protocol(tmp_path), endpoint).ask("Q?") == Reply("not_connected")


def test_a_validly_signed_answer_from_a_third_identity_is_an_error(tmp_path):
    a, endpoint = a_side(tmp_path, ["x"])
    a.accept_peer(B.agent_id, name="Bob")
    real, sessions = endpoint.endpoint.handle, []

    def handle(raw, **kw):
        if not sessions:
            reply = real(raw, **kw)
            sessions.append(json.loads(reply)["body"]["session"])
            return reply
        return signed_by_c("answer", {"text": "from the wrong agent"}, session=sessions[0], seq=3)

    endpoint.endpoint.handle = handle
    reply = client(b_protocol(tmp_path), endpoint).ask("Q?")
    assert reply.kind == "error" and "from the wrong agent" not in reply.text


def test_a_welcome_granting_more_than_requested_is_not_connected(tmp_path):
    a, endpoint = a_side(tmp_path, ["x"])
    a.accept_peer(B.agent_id, name="Bob")

    real = endpoint.endpoint.handle

    def handle(raw, **kw):
        env = json.loads(real(raw, **kw))
        from localagent.protocol.tessera.envelope import sign_envelope
        env["body"]["granted_level"] = 2
        return encode(sign_envelope(A, version="0.2", type="welcome", session=env["session"], to=env["to"], seq=env["seq"],
                                    prev=env["prev"], body=env["body"], now=utc_now()))

    endpoint.endpoint.handle = handle
    assert client(b_protocol(tmp_path), endpoint).ask("Q?") == Reply("not_connected")


def test_close_uses_a_short_timeout(tmp_path):
    a, endpoint = a_side(tmp_path, ["One."])
    a.accept_peer(B.agent_id, name="Bob")
    timeouts = []

    def post(address, raw, timeout=300):
        timeouts.append(timeout)
        return endpoint.handle(raw)

    c = client(b_protocol(tmp_path), endpoint, post=post)
    assert c.ask("1?").kind == "answer"
    c.close()
    assert timeouts[-1] <= 5 < timeouts[0]
