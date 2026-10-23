import threading
import time

import pytest

from localagent.protocol.identity import identity_from_seed
from localagent.relay.core import (MAX_WAITING, BadToken, Busy, Full, Offline, Refused, Relay, TimedOut,
                                   register_message)

ANA = identity_from_seed(bytes(range(32)))
BOB = identity_from_seed(bytes(range(32, 64)))


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def join(relay, ident=ANA, **kw):
    nonce = relay.challenge()
    return relay.register(ident.agent_id, nonce, ident.sign(register_message(nonce, ident.agent_id)), **kw)


def ask_in_background(relay, agent_id=ANA.agent_id, payload=b"q", kind="envelope", timeout=5.0):
    result = {}

    def run():
        try:
            result["reply"] = relay.deliver(agent_id, kind, payload, timeout)
        except Exception as e:
            result["error"] = e

    thread = threading.Thread(target=run)
    thread.start()
    return thread, result


def wait_for(condition, seconds=5.0):
    deadline = time.monotonic() + seconds
    while not condition():
        assert time.monotonic() < deadline, "timed out waiting"
        time.sleep(0.01)


def test_register_with_a_good_signature_gives_a_token():
    token = join(Relay())
    assert isinstance(token, str) and len(token) >= 20


def test_register_refuses_bad_signatures_and_bad_challenges():
    clock = Clock()
    relay = Relay(clock=clock)
    nonce = relay.challenge()
    with pytest.raises(Refused):  # signed by someone else
        relay.register(ANA.agent_id, nonce, BOB.sign(register_message(nonce, ANA.agent_id)))
    with pytest.raises(Refused):  # the failed attempt used the challenge up
        relay.register(ANA.agent_id, nonce, ANA.sign(register_message(nonce, ANA.agent_id)))
    with pytest.raises(Refused):  # a challenge the relay never gave
        relay.register(ANA.agent_id, "made-up", ANA.sign(register_message("made-up", ANA.agent_id)))
    nonce = relay.challenge()
    with pytest.raises(Refused):  # a signature made for another agent id
        relay.register(ANA.agent_id, nonce, ANA.sign(register_message(nonce, BOB.agent_id)))
    nonce = relay.challenge()
    clock.now += 61
    with pytest.raises(Refused):  # expired
        relay.register(ANA.agent_id, nonce, ANA.sign(register_message(nonce, ANA.agent_id)))


def test_deliver_next_reply_round_trip():
    relay = Relay()
    token = join(relay)
    thread, result = ask_in_background(relay, payload=b"hello")
    request = relay.next_request(ANA.agent_id, token, wait=5)
    assert (request.kind, request.payload) == ("envelope", b"hello")
    relay.reply(ANA.agent_id, token, request.id, b"answer")
    thread.join(5)
    assert result == {"reply": b"answer"}


def test_an_empty_poll_returns_none_after_the_wait():
    relay = Relay()
    token = join(relay)
    assert relay.next_request(ANA.agent_id, token, wait=0.05) is None


def test_deliver_to_an_agent_that_isnt_connected_is_offline():
    with pytest.raises(Offline):
        Relay().deliver(ANA.agent_id, "envelope", b"q", 1)


def test_deliver_times_out_and_a_late_reply_is_ignored():
    relay = Relay()
    token = join(relay)
    thread, result = ask_in_background(relay, timeout=0.5)
    request = relay.next_request(ANA.agent_id, token, wait=5)
    thread.join(5)
    assert isinstance(result["error"], TimedOut)
    relay.reply(ANA.agent_id, token, request.id, b"late")  # no error, nobody waiting
    assert relay.pending(ANA.agent_id) == 0


def test_the_ninth_waiting_request_is_busy():
    relay = Relay()
    join(relay)
    threads = [ask_in_background(relay, timeout=1)[0] for _ in range(MAX_WAITING)]
    wait_for(lambda: relay.pending(ANA.agent_id) == MAX_WAITING)
    with pytest.raises(Busy):
        relay.deliver(ANA.agent_id, "envelope", b"q", 1)
    for thread in threads:
        thread.join(5)


def test_registering_again_replaces_the_old_registration():
    relay = Relay()
    old = join(relay)
    thread, result = ask_in_background(relay)
    wait_for(lambda: relay.pending(ANA.agent_id) == 1)
    new = join(relay)
    thread.join(5)
    assert isinstance(result["error"], Offline)
    with pytest.raises(BadToken):
        relay.next_request(ANA.agent_id, old, wait=0)
    assert relay.next_request(ANA.agent_id, new, wait=0) is None


def test_a_poll_left_over_from_an_old_registration_gets_bad_token():
    relay = Relay()
    old = join(relay)
    out = {}

    def poll():
        try:
            out["request"] = relay.next_request(ANA.agent_id, old, wait=5)
        except Exception as e:
            out["error"] = e

    poller = threading.Thread(target=poll)
    poller.start()
    time.sleep(0.1)
    new = join(relay)
    thread, result = ask_in_background(relay, payload=b"for the new one")
    poller.join(5)
    assert isinstance(out["error"], BadToken)
    request = relay.next_request(ANA.agent_id, new, wait=5)
    assert request.payload == b"for the new one"
    relay.reply(ANA.agent_id, new, request.id, b"ok")
    thread.join(5)
    assert result == {"reply": b"ok"}


def test_an_agent_that_stops_polling_is_dropped_and_its_askers_told():
    clock = Clock()
    relay = Relay(clock=clock)
    join(relay, listed=True, name="Ana")
    thread, result = ask_in_background(relay)
    wait_for(lambda: relay.pending(ANA.agent_id) == 1)
    clock.now += 61
    relay.sweep()
    thread.join(5)
    assert isinstance(result["error"], Offline)
    assert relay.directory("http://relay") == []
    with pytest.raises(Offline):
        relay.deliver(ANA.agent_id, "envelope", b"q", 1)


def test_an_agent_that_keeps_polling_stays():
    clock = Clock()
    relay = Relay(clock=clock)
    token = join(relay)
    clock.now += 50
    assert relay.next_request(ANA.agent_id, token, wait=0) is None
    clock.now += 50  # 100 s after registering, 50 s after the last poll
    relay.sweep()
    assert relay.next_request(ANA.agent_id, token, wait=0) is None


def test_directory_lists_only_connected_listed_agents_with_clean_text():
    relay = Relay()
    join(relay, ANA, listed=True, name="Ana\x1b[2J", description="x" * 500 + "\n")
    join(relay, BOB)
    assert relay.directory("https://relay.example/") == [
        {"id": ANA.agent_id, "name": "Ana[2J", "description": "x" * 200,
         "address": f"https://relay.example/a/{ANA.agent_id}", "public": False}]


def test_max_agents():
    relay = Relay(max_agents=1)
    join(relay, ANA)
    with pytest.raises(Full):
        join(relay, BOB)
    join(relay, ANA)  # re-registering an agent already there is fine


def test_challenges_are_capped():
    relay = Relay(max_challenges=3)
    for _ in range(3):
        relay.challenge()
    with pytest.raises(Busy):
        relay.challenge()


def test_directory_shows_public_flag():
    relay = Relay()
    join(relay, ANA, listed=True, public=True)
    join(relay, BOB, listed=True)
    assert {a["id"]: a["public"] for a in relay.directory("http://r")} == {ANA.agent_id: True, BOB.agent_id: False}
