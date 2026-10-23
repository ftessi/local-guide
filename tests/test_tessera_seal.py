import json

import pytest

from localagent.protocol.identity import x25519_from_seed, x25519_public
from localagent.protocol.tessera import seal
from localagent.protocol.tessera.canonical import canonical

KX = x25519_from_seed(bytes(range(96, 128)))      # the agent's static key
E = x25519_from_seed(bytes(range(128, 160)))      # the asker's one-time key
F = x25519_from_seed(bytes(range(160, 192)))      # the agent's one-time key
HANDLE = "0123456789abcdef"


def handshake(inner_hello=b'{"hello":1}', inner_welcome=b'{"welcome":1}'):
    hello_raw = seal.seal_hello(E, x25519_public(KX), inner_hello)
    e_pub, opened = seal.open_hello(KX, seal.parse(hello_raw))
    welcome_raw, agent_keys = seal.seal_welcome(KX, F, e_pub, hello_raw, HANDLE, inner_welcome)
    inner, asker_keys, handle, f = seal.open_welcome(E, x25519_public(KX), hello_raw, seal.parse(welcome_raw))
    return hello_raw, opened, welcome_raw, inner, agent_keys, asker_keys, handle, f


def test_handshake_round_trip():
    hello_raw, opened, welcome_raw, inner, agent_keys, asker_keys, handle, f = handshake()
    assert opened == b'{"hello":1}' and inner == b'{"welcome":1}'
    assert (handle, f) == (HANDLE, x25519_public(F))
    assert asker_keys.send == agent_keys.recv and asker_keys.recv == agent_keys.send
    assert asker_keys.send != asker_keys.recv
    for raw in (hello_raw, welcome_raw):
        assert b"hello\":1" not in raw and b"welcome\":1" not in raw


def test_messages_both_ways():
    *_, agent_keys, asker_keys, handle, _ = handshake()
    ask = seal.seal_msg(asker_keys, seal.TO_AGENT, 1, handle, b"question")
    assert seal.open_msg(agent_keys, seal.TO_AGENT, seal.parse(ask)) == b"question"
    answer = seal.seal_msg(agent_keys, seal.TO_ASKER, 1, handle, b"answer")
    assert seal.open_msg(asker_keys, seal.TO_ASKER, seal.parse(answer)) == b"answer"
    assert b"question" not in ask and b"answer" not in answer


def code_of(fn, *args):
    with pytest.raises(seal.SealError) as e:
        fn(*args)
    return e.value.code


def test_tampering_wrong_keys_and_wrong_direction_are_refused():
    *_, agent_keys, asker_keys, handle, _ = handshake()
    ask = json.loads(seal.seal_msg(asker_keys, seal.TO_AGENT, 1, handle, b"question"))
    assert code_of(seal.open_msg, asker_keys, seal.TO_AGENT, ask) == "bad_signature"   # asker can't open its own
    assert code_of(seal.open_msg, agent_keys, seal.TO_ASKER, ask) == "bad_signature"   # wrong direction
    moved = dict(ask, n=2)
    assert code_of(seal.open_msg, agent_keys, seal.TO_AGENT, moved) == "bad_signature" # counter is authenticated
    flipped = dict(ask, ct=ask["ct"][:-2] + ("A" if ask["ct"][-2] != "A" else "B") + ask["ct"][-1])
    assert code_of(seal.open_msg, agent_keys, seal.TO_AGENT, flipped) in ("bad_signature", "malformed")
    other = x25519_from_seed(bytes(range(192, 224)))
    hello = seal.parse(seal.seal_hello(E, x25519_public(KX), b"x"))
    assert code_of(seal.open_hello, other, hello) == "bad_signature"                    # not for this agent


def test_parse_refuses_anything_but_a_well_formed_package():
    good = seal.seal_hello(E, x25519_public(KX), b"x")
    assert seal.parse(good)["kind"] == "hello"
    bad = [b"not json", b"[]", canonical({"tessera": "0.1", "kind": "hello", "e": "x", "ct": "y"}),
           canonical({"tessera": "0.2", "kind": "hello", "e": "x"}),
           canonical({"tessera": "0.2", "kind": "msg", "h": "XYZ", "n": 1, "ct": "y"}),
           canonical({"tessera": "0.2", "kind": "msg", "h": HANDLE, "n": 0, "ct": "y"}),
           canonical({"tessera": "0.2", "kind": "msg", "h": HANDLE, "n": True, "ct": "y"}),
           canonical({"tessera": "0.2", "kind": "other"})]
    for raw in bad:
        assert code_of(seal.parse, raw) == "malformed"
    assert code_of(seal.parse, b"x" * (64 * 1024 + 1)) == "too_large"


def test_a_refuse_and_a_welcome_look_the_same_from_outside():
    *_, = handshake()
    hello_raw = seal.seal_hello(E, x25519_public(KX), b"h")
    e_pub, _ = seal.open_hello(KX, seal.parse(hello_raw))
    welcome, _ = seal.seal_welcome(KX, F, e_pub, hello_raw, HANDLE, b'{"type":"welcome"}')
    refuse, _ = seal.seal_welcome(KX, F, e_pub, hello_raw, HANDLE, b'{"type":"refuse!"}')
    assert set(json.loads(welcome)) == set(json.loads(refuse)) and len(welcome) == len(refuse)


def test_error_package_carries_a_signed_envelope_in_clear():
    raw = seal.error_package(b'{"type":"error"}')
    assert seal.parse(raw) == {"tessera": "0.2", "kind": "error", "env": {"type": "error"}}


def test_a_bad_public_key_is_malformed():
    hello = json.loads(seal.seal_hello(E, x25519_public(KX), b"x"))
    hello["e"] = "A" * 43  # the all-zero point: no shared secret
    assert code_of(seal.open_hello, KX, hello) == "malformed"
