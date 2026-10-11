import json
from datetime import datetime, timedelta, timezone

import pytest

from localagent.protocol.identity import identity_from_seed
from localagent.protocol.tessera.canonical import canonical
from localagent.protocol.tessera.chain import Chain, verify_record
from localagent.protocol.tessera.envelope import (MAX_BYTES, EnvelopeError, decode, encode, envelope_hash,
                                                  format_time, parse_time, sender_of, sign_envelope)

A = identity_from_seed(bytes(range(32)))
B = identity_from_seed(bytes(range(32, 64)))
NOW = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)


def hello(**over):
    fields = dict(type="hello", session="", to=A.agent_id, seq=0, prev="",
                  body={"purpose": "Review contract v3", "requested_level": 1, "nonce": "n1"}, now=NOW)
    fields.update(over)
    return sign_envelope(B, **fields)


def code_of(raw, now=NOW):
    with pytest.raises(EnvelopeError) as e:
        decode(raw, now)
    return e.value.code


def resign(env, identity=B):
    env = {k: v for k, v in env.items() if k != "sig"}
    env["sig"] = identity.sign(canonical(env))
    return env


def test_round_trip():
    env = hello()
    assert decode(encode(env), NOW) == env
    assert env["from"] == B.agent_id and env["time"] == "2026-10-11T12:00:00Z"
    assert parse_time(format_time(NOW)) == NOW


def test_signature_covers_everything():
    env = hello()
    for field, value in [("body", {"purpose": "x", "requested_level": 1, "nonce": "n1"}), ("seq", 1),
                         ("to", B.agent_id), ("from", A.agent_id)]:
        assert code_of(encode({**env, field: value})) == "bad_signature"


def test_time_window():
    assert decode(encode(hello()), NOW + timedelta(minutes=5)) is not None
    assert code_of(encode(hello()), NOW + timedelta(minutes=5, seconds=1)) == "stale"


def test_size_limit():
    big = hello(body={"purpose": "x", "requested_level": 1, "nonce": "n"})
    raw = encode(big) + b" " * MAX_BYTES
    assert code_of(raw) == "too_large"


@pytest.mark.parametrize("mutate", [
    lambda e: b"not json",
    lambda e: b'{"a": 1, "a": 2}',
    lambda e: encode({k: v for k, v in e.items() if k != "nonce"} | {"extra": 1}),
    lambda e: encode(resign({**e, "body": {**e["body"], "extra": 1}})),
    lambda e: encode(resign({**e, "tessera": "9.9"})),
    lambda e: encode(resign({**e, "type": "shout"})),
    lambda e: encode(resign({**e, "seq": True})),
    lambda e: encode(resign({**e, "body": {**e["body"], "purpose": "p" * 201}})),
    lambda e: encode(resign({**e, "body": {**e["body"], "requested_level": 7}})),
    lambda e: encode(resign({**e, "to": "someone"})),
    lambda e: encode(resign({**e, "time": "yesterday"})),
    lambda e: json.dumps({**e, "seq": 1.0}).encode(),
    lambda e: b'{"seq": NaN}',
])
def test_malformed(mutate):
    assert code_of(mutate(hello())) == "malformed"


def test_bodies_per_type():
    ok = [("refuse", {}), ("ask", {"text": "Q?"}), ("answer", {"text": "A.", "binding": False}),
          ("decline", {}), ("close", {}), ("error", {"code": "limit"}),
          ("card", {"agent_id": A.agent_id, "name": "A", "versions": ["0.1"]}),
          ("welcome", {"session": "s-1", "granted_level": 1, "expires": "2026-10-11T13:00:00Z",
                       "limits": {"asks": 50, "ask_chars": 1000}})]
    for type_, body in ok:
        env = sign_envelope(A, type=type_, session="", to=B.agent_id, seq=1, prev="", body=body, now=NOW)
        assert decode(encode(env), NOW)["type"] == type_
    bad = [("answer", {"text": "A.", "binding": True}), ("error", {"code": "oops"}),
           ("welcome", {"session": "s-1", "granted_level": 1, "expires": "2026-10-11T13:00:00Z",
                        "limits": {"asks": 50}})]
    for type_, body in bad:
        env = sign_envelope(A, type=type_, session="", to=B.agent_id, seq=1, prev="", body=body, now=NOW)
        assert code_of(encode(env)) == "malformed"


def test_hash_includes_the_signature_and_changes_with_anything():
    env = hello()
    assert len(envelope_hash(env)) == 43
    other = "B" if env["sig"][-1] == "A" else "A"
    assert envelope_hash(env) != envelope_hash({**env, "sig": env["sig"][:-1] + other})
    assert envelope_hash(env) != envelope_hash(hello(body={"purpose": "Other", "requested_level": 1,
                                                           "nonce": "n1"}))


def test_sender_of_is_best_effort():
    assert sender_of(encode(hello())) == B.agent_id
    assert sender_of(b"garbage") == "" and sender_of(b'{"from": "x"}') == ""


def test_chain():
    h = hello()
    w = sign_envelope(A, type="welcome", session="", to=B.agent_id, seq=1, prev=envelope_hash(h),
                      body={"session": "s-1", "granted_level": 1, "expires": "2026-10-11T13:00:00Z",
                            "limits": {"asks": 50, "ask_chars": 1000}}, now=NOW)
    chain = Chain()
    chain.append(h)
    chain.append(w)
    assert chain.next_seq() == 2 and chain.last_hash() == envelope_hash(w)
    late = sign_envelope(B, type="ask", session="s-1", to=A.agent_id, seq=3, prev=envelope_hash(w),
                         body={"text": "Q"}, now=NOW)
    wrong_prev = sign_envelope(B, type="ask", session="s-1", to=A.agent_id, seq=2, prev=envelope_hash(h),
                               body={"text": "Q"}, now=NOW)
    for env in (late, wrong_prev):
        with pytest.raises(EnvelopeError) as e:
            chain.append(env)
        assert e.value.code == "bad_chain"
    verify_record(chain.envelopes)
    tampered = [h, {**w, "body": {**w["body"], "granted_level": 2}}]
    with pytest.raises(EnvelopeError):
        verify_record(tampered)
