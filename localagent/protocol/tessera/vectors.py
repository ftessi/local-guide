"""Builds Tessera's published test vectors: fixed keys and times, so any implementation can check its bytes."""
from datetime import datetime, timezone

from localagent.protocol.identity import identity_from_seed
from localagent.protocol.tessera.canonical import canonical
from localagent.protocol.tessera.envelope import VERSION, envelope_hash, sign_envelope

SEED_A = bytes(range(32))
SEED_B = bytes(range(32, 64))
TIME = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)
SESSION = "s-0123456789abcdef"
CANONICAL_CASES = [
    {"b": 1, "a": [True, None, -5], "c": "x"},
    {"text": "é\n\u0001\"\/"},
    {"\ufb01": 1, "\U0001F600": 2},
]


def build_vectors() -> dict:
    a, b = identity_from_seed(SEED_A), identity_from_seed(SEED_B)
    items = []

    def add(name: str, identity, **fields) -> dict:
        env = sign_envelope(identity, now=TIME, **fields)
        signed = canonical({k: v for k, v in env.items() if k != "sig"}).decode("utf-8")
        items.append({"name": name, "envelope": env, "signed_bytes": signed, "hash": envelope_hash(env)})
        return env

    hello = add("hello", b, type="hello", session="", to=a.agent_id, seq=0, prev="",
                body={"purpose": "Review contract v3", "requested_level": 1,
                      "nonce": "00112233445566778899aabbccddeeff"})
    welcome = add("welcome", a, type="welcome", session="", to=b.agent_id, seq=1, prev=envelope_hash(hello),
                  body={"session": SESSION, "granted_level": 1, "expires": "2026-10-11T13:00:00Z",
                        "limits": {"asks": 50, "ask_chars": 1000}})
    ask = add("ask", b, type="ask", session=SESSION, to=a.agent_id, seq=2, prev=envelope_hash(welcome),
              body={"text": "What is the shared secret?"})
    add("answer", a, type="answer", session=SESSION, to=b.agent_id, seq=3, prev=envelope_hash(ask),
        body={"text": "The shared secret is GREEN-LANTERN-7.", "binding": False})
    add("refuse", a, type="refuse", session="", to=b.agent_id, seq=1, prev=envelope_hash(hello), body={})
    add("error", a, type="error", session="", to=b.agent_id, seq=-1, prev="", body={"code": "bad_chain"})
    return {"tessera": VERSION,
            "keys": {"A": {"seed_hex": SEED_A.hex(), "agent_id": a.agent_id},
                     "B": {"seed_hex": SEED_B.hex(), "agent_id": b.agent_id}},
            "canonical": [{"value": v, "canonical": canonical(v).decode("utf-8")} for v in CANONICAL_CASES],
            "envelopes": items}
