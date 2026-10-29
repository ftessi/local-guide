import io
import json
import threading
import time
from urllib.error import URLError
from urllib.request import urlopen

import pytest

from localagent.connect.peer.tessera.http import post
from localagent.connect.peer.tessera.relay_link import RelayLink
from localagent.protocol.identity import identity_from_seed
from localagent.relay.core import Relay, register_message
from localagent.relay.http import RelayServer

ANA = identity_from_seed(bytes(range(32)))


class FakeEndpoint:
    def __init__(self, delay=0.0):
        self.delay, self.lock, self.active, self.most = delay, threading.Lock(), 0, 0

    def handle(self, raw):
        with self.lock:
            self.active += 1
            self.most = max(self.most, self.active)
        time.sleep(self.delay)
        with self.lock:
            self.active -= 1
        return b"reply to " + raw

    def card(self):
        return b"card"


def wait_for(condition, seconds=5.0):
    deadline = time.monotonic() + seconds
    while not condition():
        assert time.monotonic() < deadline, "timed out waiting"
        time.sleep(0.01)


@pytest.fixture
def relay_server():
    server = RelayServer(Relay(), "127.0.0.1", 0, poll_wait=0.2, deliver_timeout=10, card_timeout=10)
    server.start()
    yield server
    server.stop()


def link_for(server, endpoint, lines=None):
    link = RelayLink(endpoint, ANA, f"http://127.0.0.1:{server.port}", name="tessera-demo", poll_wait=0.2,
                     say=(lines.append if lines is not None else (lambda text: None)))
    link.start()
    assert link.connected.wait(5)
    return link


def test_the_link_registers_and_answers_through_the_relay(relay_server):
    lines = []
    link = link_for(relay_server, FakeEndpoint(), lines)
    try:
        address = f"http://127.0.0.1:{relay_server.port}/a/{ANA.agent_id}"
        assert link.address == address
        assert lines == [f"Tessera via relay: {address}  (agent id {ANA.agent_id})"]
        assert post(address, b"hello") == b"reply to hello"
        with urlopen(f"{address}/tessera/card", timeout=10) as response:
            assert response.read() == b"card"
    finally:
        link.stop()


def test_several_askers_are_served_at_once(relay_server):
    endpoint = FakeEndpoint(delay=0.5)
    link = link_for(relay_server, endpoint)
    try:
        replies = []
        threads = [threading.Thread(target=lambda i=i: replies.append(post(link.address, b"q%d" % i)))
                   for i in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
        assert sorted(replies) == sorted(b"reply to q%d" % i for i in range(4))
        assert endpoint.most > 1
    finally:
        link.stop()


def test_the_link_registers_again_when_its_token_stops_working(relay_server):
    lines = []
    link = link_for(relay_server, FakeEndpoint(), lines)
    try:
        nonce = relay_server.relay.challenge()  # the same agent registers again elsewhere
        relay_server.relay.register(ANA.agent_id, nonce, ANA.sign(register_message(nonce, ANA.agent_id)))
        wait_for(lambda: len(lines) == 2)
        assert "connected again from somewhere else" in lines[1]
        wait_for(link.connected.is_set)  # takes the relay back after a pause
        assert post(link.address, b"again") == b"reply to again"
    finally:
        link.stop()


def test_the_link_backs_off_while_the_relay_is_unreachable():
    lines, pauses = [], []

    def down(*args, **kwargs):
        raise URLError("down")

    link = RelayLink(FakeEndpoint(), ANA, "http://relay.invalid", name="x", say=lines.append, max_backoff=4,
                     pause=pauses.append, opener=down)
    link.start()
    wait_for(lambda: len(pauses) >= 5)
    link.stop()
    assert pauses[:5] == [1, 2, 4, 4, 4]
    assert len([line for line in lines if "unreachable" in line]) == 1
    assert not link.connected.is_set()


class FakeResponse(io.BytesIO):
    def __init__(self, data, status=200):
        super().__init__(data)
        self.status = status


def test_a_relay_that_sends_garbage_does_not_stop_the_link():
    lines, pauses = [], []
    answers = iter([FakeResponse(json.dumps({"nonce": "n"}).encode()),
                    FakeResponse(json.dumps({"token": "t", "address": "http://r/a/x"}).encode()),
                    FakeResponse(b"garbage")])

    def opener(request, timeout=None):
        try:
            return next(answers)
        except StopIteration:
            raise URLError("down") from None

    link = RelayLink(FakeEndpoint(), ANA, "http://r", name="x", say=lines.append, pause=pauses.append, opener=opener)
    link.start()
    wait_for(lambda: len(pauses) >= 2)
    alive = link._thread.is_alive()
    link.stop()
    assert alive
    assert lines[0].startswith("Tessera via relay: http://r/a/x") and "unreachable" in lines[1]


def test_stop_returns_within_a_poll(relay_server):
    link = link_for(relay_server, FakeEndpoint())
    start = time.monotonic()
    link.stop()
    assert time.monotonic() - start < 3


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class BlockingEndpoint(FakeEndpoint):
    def __init__(self):
        super().__init__()
        self.release = threading.Event()

    def handle(self, raw):
        with self.lock:
            self.active += 1
        self.release.wait(10)
        return b"reply to " + raw


def test_a_link_with_every_worker_busy_keeps_polling_so_the_relay_keeps_it():
    clock = Clock()
    server = RelayServer(Relay(clock=clock), "127.0.0.1", 0, poll_wait=0.2, deliver_timeout=20, sweep_seconds=3600)
    server.start()
    endpoint = BlockingEndpoint()
    link = link_for(server, endpoint)
    try:
        replies = []
        threads = [threading.Thread(target=lambda i=i: replies.append(post(link.address, b"q%d" % i)))
                   for i in range(8)]
        for thread in threads:
            thread.start()
        wait_for(lambda: endpoint.active == 8)
        clock.now += 61  # a minute of slow model calls
        time.sleep(1)  # a link that still polls has been seen since
        server.relay.sweep()
        endpoint.release.set()
        for thread in threads:
            thread.join(10)
        assert sorted(replies) == sorted(b"reply to q%d" % i for i in range(8))
    finally:
        link.stop()
        server.stop()


def test_two_copies_of_one_agent_do_not_take_over_from_each_other_in_a_loop(relay_server):
    lines_a, lines_b = [], []
    a = link_for(relay_server, FakeEndpoint(), lines_a)
    b = link_for(relay_server, FakeEndpoint(), lines_b)
    try:
        time.sleep(3)
    finally:
        a.stop()
        b.stop()
    assert len(lines_a) <= 4 and len(lines_b) <= 4, (len(lines_a), len(lines_b))


def test_stop_does_not_wait_for_a_long_poll(relay_server):
    link = RelayLink(FakeEndpoint(), ANA, f"http://127.0.0.1:{relay_server.port}", name="x", poll_wait=10,
                     say=lambda text: None)
    relay_server.poll_wait = 10
    link.start()
    assert link.connected.wait(5)
    time.sleep(0.3)  # the poll is now held by the relay
    start = time.monotonic()
    link.stop()
    assert time.monotonic() - start < 2.5


def test_the_link_refuses_a_huge_answer_from_the_relay():
    endpoint, pauses = FakeEndpoint(), []
    calls = []
    endpoint.handle = lambda raw: calls.append(raw) or b"r"
    huge = json.dumps({"request": "0123456789abcdef", "kind": "envelope", "payload": "QUFB" * 2_000_000}).encode()
    answers = iter([FakeResponse(json.dumps({"nonce": "n"}).encode()),
                    FakeResponse(json.dumps({"token": "t", "address": "http://r/a/x"}).encode()),
                    FakeResponse(huge)])

    def opener(request, timeout=None):
        try:
            return next(answers)
        except StopIteration:
            raise URLError("down") from None

    link = RelayLink(endpoint, ANA, "http://r", name="x", say=lambda text: None, pause=pauses.append, opener=opener)
    link.start()
    wait_for(lambda: len(pauses) >= 1)
    link.stop()
    assert calls == []


def test_relay_link_registers_public_flag():
    bodies = []
    answers = iter([FakeResponse(json.dumps({"nonce": "n"}).encode()),
                    FakeResponse(json.dumps({"token": "t", "address": "http://r/a/x"}).encode())])

    def opener(request, timeout=None):
        if request.data:
            bodies.append(json.loads(request.data))
        try:
            return next(answers)
        except StopIteration:
            raise URLError("down") from None

    link = RelayLink(FakeEndpoint(), ANA, "http://r", name="x", public=True, say=lambda t: None,
                     pause=lambda s: None, opener=opener)
    link.start()
    wait_for(lambda: bodies)
    link.stop()
    assert bodies[0]["public"] is True and bodies[0]["listed"] is False
