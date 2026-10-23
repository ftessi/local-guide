import base64
import json
import socket
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from localagent.protocol.identity import identity_from_seed
from localagent.protocol.tessera.envelope import MAX_BYTES
from localagent.relay.core import Relay, register_message
from localagent.relay.http import RelayServer

ANA = identity_from_seed(bytes(range(32)))


@pytest.fixture
def relay_server():
    server = RelayServer(Relay(), "127.0.0.1", 0, poll_wait=0.2, deliver_timeout=2, card_timeout=2)
    server.start()
    yield server
    server.stop()


def call(server, method, path, body=None, token=None):
    request = Request(f"http://127.0.0.1:{server.port}{path}", data=body, method=method)
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urlopen(request, timeout=10) as response:
            return response.status, response.read()
    except HTTPError as e:
        return e.code, e.read()


def register(server, ident=ANA, **extra):
    _, raw = call(server, "GET", "/relay/challenge")
    nonce = json.loads(raw)["nonce"]
    body = {"agent_id": ident.agent_id, "nonce": nonce,
            "signature": ident.sign(register_message(nonce, ident.agent_id)), **extra}
    return call(server, "POST", "/relay/register", json.dumps(body).encode())


def token_of(server, **extra):
    return json.loads(register(server, **extra)[1])["token"]


def next_job(server, token):
    for _ in range(50):  # each poll is held 0.2 s
        status, raw = call(server, "GET", f"/a/{ANA.agent_id}/next", token=token)
        if status == 200:
            return json.loads(raw)
        assert status == 204
    raise AssertionError("no request arrived")


def in_background(fn):
    result = {}
    thread = threading.Thread(target=lambda: result.update(value=fn()))
    thread.start()
    return thread, result


def test_register_returns_a_token_and_the_agents_address(relay_server):
    status, raw = register(relay_server)
    data = json.loads(raw)
    assert status == 200 and data["token"]
    assert data["address"] == f"http://127.0.0.1:{relay_server.port}/a/{ANA.agent_id}"


def test_register_errors(relay_server):
    assert call(relay_server, "POST", "/relay/register", b"not json")[0] == 400
    assert call(relay_server, "POST", "/relay/register", b'{"agent_id": 1}')[0] == 400
    body = json.dumps({"agent_id": ANA.agent_id, "nonce": "x", "signature": "y"}).encode()
    assert call(relay_server, "POST", "/relay/register", body)[0] == 401
    assert call(relay_server, "POST", "/relay/register", b"x" * 5000)[0] == 413


def test_an_ask_goes_to_the_agent_and_its_reply_comes_back(relay_server):
    token = token_of(relay_server)
    thread, result = in_background(lambda: call(relay_server, "POST", f"/a/{ANA.agent_id}/tessera", b'{"env": 1}'))
    job = next_job(relay_server, token)
    assert job["kind"] == "envelope" and base64.b64decode(job["payload"]) == b'{"env": 1}'
    assert call(relay_server, "POST", f"/a/{ANA.agent_id}/reply/{job['request']}", b"reply bytes",
                token=token)[0] == 204
    thread.join(5)
    assert result["value"] == (200, b"reply bytes")


def test_the_card_goes_to_the_agent_too(relay_server):
    token = token_of(relay_server)
    thread, result = in_background(lambda: call(relay_server, "GET", f"/a/{ANA.agent_id}/tessera/card"))
    job = next_job(relay_server, token)
    assert job["kind"] == "card" and job["payload"] == ""
    call(relay_server, "POST", f"/a/{ANA.agent_id}/reply/{job['request']}", b"card bytes", token=token)
    thread.join(5)
    assert result["value"] == (200, b"card bytes")


def test_asking_an_agent_that_isnt_connected_is_503(relay_server):
    assert call(relay_server, "POST", f"/a/{ANA.agent_id}/tessera", b"{}")[0] == 503


def test_an_agent_that_doesnt_answer_is_504(relay_server):
    register(relay_server)
    assert call(relay_server, "POST", f"/a/{ANA.agent_id}/tessera", b"{}")[0] == 504


def test_too_large_is_413(relay_server):
    register(relay_server)
    assert call(relay_server, "POST", f"/a/{ANA.agent_id}/tessera", b"x" * (MAX_BYTES + 1))[0] == 413


def test_a_huge_content_length_is_refused_without_reading_it(relay_server):
    with socket.create_connection(("127.0.0.1", relay_server.port), timeout=5) as s:
        s.sendall(f"POST /a/{ANA.agent_id}/tessera HTTP/1.0\r\nContent-Length: 1000000000000\r\n\r\n".encode())
        assert s.recv(100).startswith(b"HTTP/1.0 413")


def test_unknown_routes_and_bad_tokens(relay_server):
    assert call(relay_server, "GET", "/nothing")[0] == 404
    assert call(relay_server, "GET", "/a/short/next")[0] == 404
    assert call(relay_server, "GET", f"/a/{ANA.agent_id}/next", token="wrong")[0] == 401
    register(relay_server)
    assert call(relay_server, "GET", f"/a/{ANA.agent_id}/next", token="wrong")[0] == 401
    assert call(relay_server, "GET", f"/a/{ANA.agent_id}/next")[0] == 401
    assert call(relay_server, "POST", f"/a/{ANA.agent_id}/reply/0123456789abcdef", b"x", token="wrong")[0] == 401


def test_an_empty_poll_is_204(relay_server):
    token = token_of(relay_server)
    assert call(relay_server, "GET", f"/a/{ANA.agent_id}/next", token=token) == (204, b"")


def test_directory_route(relay_server):
    register(relay_server, listed=True, name="Ana", description="Demo answers")
    status, raw = call(relay_server, "GET", "/agents")
    assert status == 200
    assert json.loads(raw) == [{"id": ANA.agent_id, "name": "Ana", "description": "Demo answers",
                                "address": f"http://127.0.0.1:{relay_server.port}/a/{ANA.agent_id}",
                                "public": False}]


def test_public_url_is_used_for_addresses():
    server = RelayServer(Relay(), "127.0.0.1", 0, public_url="https://relay.example.com/")
    server.start()
    try:
        assert json.loads(register(server)[1])["address"] == f"https://relay.example.com/a/{ANA.agent_id}"
    finally:
        server.stop()


def test_the_sweeper_drops_silent_agents():
    class Clock:
        now = 1000.0

        def __call__(self):
            return self.now

    clock = Clock()
    server = RelayServer(Relay(clock=clock), "127.0.0.1", 0, sweep_seconds=0.05, deliver_timeout=30)
    server.start()
    try:
        register(server)
        thread, result = in_background(lambda: call(server, "POST", f"/a/{ANA.agent_id}/tessera", b"{}"))
        deadline = time.monotonic() + 5
        while server.relay.pending(ANA.agent_id) == 0:
            assert time.monotonic() < deadline
            time.sleep(0.01)
        clock.now += 61  # nobody touches the relay: only the sweeper can notice
        thread.join(5)
        assert result["value"][0] == 503
    finally:
        server.stop()


def test_relay_command(monkeypatch, capsys, tmp_path):
    from localagent.__main__ import main

    def interrupt(seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr("localagent.relay.http.sleep", interrupt)
    assert main(["relay", "--port", "0", "--data-dir", str(tmp_path / "data")]) == 0
    out = capsys.readouterr().out
    assert "Tessera relay on http://127.0.0.1:" in out and "Relay stopped." in out
    assert (tmp_path / "data" / "inbox").is_dir()


def test_the_relay_logs_metadata_and_never_content(tmp_path):
    from localagent.relay.log import RelayLog
    server = RelayServer(Relay(), "127.0.0.1", 0, poll_wait=0.2, deliver_timeout=2,
                         log=RelayLog(tmp_path / "connections.jsonl"))
    server.start()
    try:
        token = token_of(server)
        thread, result = in_background(lambda: call(server, "POST", f"/a/{ANA.agent_id}/tessera", b"SECRET-CONTENT"))
        job = next_job(server, token)
        call(server, "POST", f"/a/{ANA.agent_id}/reply/{job['request']}", b"SECRET-REPLY", token=token)
        thread.join(5)
        call(server, "POST", f"/a/{'B' * 43}/tessera", b"x")
    finally:
        server.stop()
    text = (tmp_path / "connections.jsonl").read_text(encoding="utf-8")
    assert "SECRET" not in text
    events = [json.loads(line) for line in text.splitlines()]
    assert events[0]["event"] == "register" and events[0]["agent"] == ANA.agent_id
    deliver = [e for e in events if e["event"] == "deliver"]
    assert deliver[0]["outcome"] == "answered" and deliver[0]["bytes_in"] == 14 and deliver[0]["bytes_out"] == 12
    assert deliver[1]["outcome"] == "offline"


def test_inspection_inbox(tmp_path):
    server = RelayServer(Relay(), "127.0.0.1", 0, inbox=tmp_path / "inbox", inbox_bytes=10)
    server.start()
    try:
        assert call(server, "POST", "/relay/inspection", b"sealed")[0] == 204
        assert [f.read_bytes() for f in (tmp_path / "inbox").iterdir()] == [b"sealed"]
        assert call(server, "POST", "/relay/inspection", b"too much")[0] == 503  # over the cap
    finally:
        server.stop()


def test_without_an_inbox_inspection_is_404(relay_server):
    assert call(relay_server, "POST", "/relay/inspection", b"x")[0] == 404


def test_register_public_over_http(relay_server):
    assert register(relay_server, listed=True, public=True)[0] == 200
    assert json.loads(call(relay_server, "GET", "/agents")[1])[0]["public"] is True
    assert register(relay_server, public="yes")[0] == 400


def limited_server(tmp_path, **kw):
    server = RelayServer(Relay(), "127.0.0.1", 0, poll_wait=0.2, deliver_timeout=0.5, card_timeout=0.5,
                         inbox=tmp_path / "inbox", **kw)
    server.start()
    return server


def call_from(server, method, path, body=None, forwarded=None):
    request = Request(f"http://127.0.0.1:{server.port}{path}", data=body, method=method)
    if forwarded:
        request.add_header("X-Forwarded-For", forwarded)
    try:
        with urlopen(request, timeout=10) as response:
            return response.status
    except HTTPError as e:
        return e.code


def test_chat_posts_rate_limited_per_ip(tmp_path):
    server = limited_server(tmp_path, chat_per_minute=2)
    try:
        path = f"/a/{ANA.agent_id}/tessera"
        assert [call_from(server, "POST", path, b"x") for _ in range(3)] == [503, 503, 429]
        assert call_from(server, "GET", f"{path}/card") == 503  # cards aren't counted
    finally:
        server.stop()


def test_uploads_rate_limited(tmp_path):
    server = limited_server(tmp_path, uploads_per_minute=1)
    try:
        assert [call_from(server, "POST", "/relay/inspection", b"sealed") for _ in range(2)] == [204, 429]
    finally:
        server.stop()


def test_forwarded_for_ignored_without_trusted_proxy(tmp_path):
    server = limited_server(tmp_path, uploads_per_minute=1)
    try:
        assert [call_from(server, "POST", "/relay/inspection", b"s", forwarded=ip)
                for ip in ("1.1.1.1", "2.2.2.2")] == [204, 429]
    finally:
        server.stop()


def test_forwarded_for_used_from_trusted_proxy(tmp_path):
    server = limited_server(tmp_path, uploads_per_minute=1, trusted_proxy="127.0.0.1")
    try:
        assert [call_from(server, "POST", "/relay/inspection", b"s", forwarded=ip)
                for ip in ("1.1.1.1", "evil, 2.2.2.2", "2.2.2.2")] == [204, 204, 429]
    finally:
        server.stop()
