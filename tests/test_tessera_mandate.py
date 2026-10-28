from datetime import datetime, timedelta, timezone

import pytest

from localagent.protocol.identity import identity_from_seed
from localagent.protocol.tessera.canonical import canonical
from localagent.protocol.tessera.envelope import EnvelopeError, sign_envelope
from localagent.protocol.tessera.mandate import MANDATE_SECONDS, MAX_CHAIN, check_chain, sign_mandate

P, L, B, C, X = (identity_from_seed(bytes([n]) * 32) for n in range(1, 6))
NOW = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)


def chain(*ids, now=NOW):
    out = []
    for frm, to in zip(ids, ids[1:]):
        out.append(sign_mandate(frm, to=to.agent_id, before=out[-1] if out else None, now=now))
    return out


def refused(mandates, *, caller, me, now=NOW):
    with pytest.raises(EnvelopeError) as e:
        check_chain(mandates, caller=caller.agent_id, me=me.agent_id, now=now)
    return e.value.code == "not_allowed"


def test_one_link_chain():
    assert check_chain(chain(P, L), caller=P.agent_id, me=L.agent_id, now=NOW) == [P.agent_id]


def test_three_links():
    ids = check_chain(chain(P, L, B, C), caller=B.agent_id, me=C.agent_id, now=NOW)
    assert ids == [P.agent_id, L.agent_id, B.agent_id]


def test_last_link_must_be_caller_to_me():
    c = chain(P, L, B)
    assert refused(c, caller=P, me=B)
    assert refused(c, caller=L, me=C)


def test_spliced_chain_rejected():
    first = chain(P, L)
    other = sign_mandate(X, to=X.agent_id, before=None, now=NOW)
    spliced = sign_mandate(L, to=B.agent_id, before=other, now=NOW)  # prev hashes someone else's mandate
    assert refused([first[0], spliced], caller=L, me=B)
    wrong_from = sign_mandate(X, to=B.agent_id, before=first[0], now=NOW)  # P→L then X→B
    assert refused([first[0], wrong_from], caller=X, me=B)


def test_expired_link_rejected():
    c = chain(P, L, B)
    assert refused(c, caller=L, me=B, now=NOW + timedelta(seconds=MANDATE_SECONDS + 1))


def test_expiry_never_grows():
    first = sign_mandate(P, to=L.agent_id, before=None, now=NOW)
    later = NOW + timedelta(seconds=MANDATE_SECONDS - 60)
    second = sign_mandate(L, to=B.agent_id, before=first, now=later)
    assert second["body"]["expires"] == first["body"]["expires"]
    assert check_chain([first, second], caller=L.agent_id, me=B.agent_id, now=later) == [P.agent_id, L.agent_id]


def test_self_granted_long_expiry_rejected():
    env = sign_envelope(P, type="mandate", session="", to=L.agent_id, seq=0, prev="",
                        body={"expires": "2026-10-29T12:00:00Z"}, now=NOW)
    assert refused([env], caller=P, me=L)


def test_loop_rejected():
    assert refused(chain(P, L, P, B), caller=P, me=B)
    assert refused(chain(P, L, B, L), caller=B, me=L)


def test_too_long():
    assert MAX_CHAIN == 4
    five = chain(P, L, B, C, X, identity_from_seed(bytes([9]) * 32))
    assert len(five) == 5
    assert refused(five, caller=X, me=identity_from_seed(bytes([9]) * 32))
    assert refused([], caller=P, me=L)


def test_bad_signature_and_wrong_type():
    c = chain(P, L)
    tampered = {**c[0], "to": B.agent_id}
    assert refused([tampered], caller=P, me=B)
    an_ask = sign_envelope(P, type="ask", session="", to=L.agent_id, seq=0, prev="",
                           body={"text": "x", "mandates": [], "reply_bytes": 0}, now=NOW)
    assert refused([an_ask], caller=P, me=L)
    assert refused(["not an envelope"], caller=P, me=L)
    old = {k: v for k, v in c[0].items() if k != "sig"}
    old["tessera"] = "0.2"
    old["sig"] = P.sign(canonical(old))
    assert refused([old], caller=P, me=L)
