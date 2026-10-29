"""Builds Tessera's published test vectors: fixed keys, one-time keys and times, so any implementation can check its
bytes, from the canonical JSON to the sealed packages."""
from datetime import datetime, timezone

from localagent.protocol.identity import identity_from_seed, x25519_from_seed, x25519_public
from localagent.protocol.tessera import seal
from localagent.protocol.tessera.canonical import canonical
from localagent.protocol.tessera.envelope import encode, envelope_hash, sign_envelope

SEED_A = bytes(range(32))
SEED_B = bytes(range(32, 64))
SEED_KX_A, SEED_E_B, SEED_F_A = bytes(range(96, 128)), bytes(range(128, 160)), bytes(range(160, 192))
TIME = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)
SESSION = "s-0123456789abcdef"
HANDLE = "0123456789abcdef"
CANONICAL_CASES = [
    {"b": 1, "a": [True, None, -5], "c": "x"},
    {"text": "é\n\u0001\"\\/"},
    {"\ufb01": 1, "\U0001F600": 2},
]


def build_vectors() -> dict:
    a, b = identity_from_seed(SEED_A), identity_from_seed(SEED_B)
    kx_a, e_b, f_a = (x25519_from_seed(s) for s in (SEED_KX_A, SEED_E_B, SEED_F_A))
    items, envs = [], {}

    def add(name: str, identity, **fields) -> dict:
        env = sign_envelope(identity, now=TIME, version="0.2", **fields)
        signed = canonical({k: v for k, v in env.items() if k != "sig"}).decode("utf-8")
        items.append({"name": name, "envelope": env, "signed_bytes": signed, "hash": envelope_hash(env),
                      "canonical": encode(env).decode("utf-8")})
        envs[name] = env
        return env

    add("card", a, type="card", session="", to="", seq=0, prev="",
        body={"agent_id": a.agent_id, "name": "Ana's agent", "versions": ["0.2"], "kx": x25519_public(kx_a)})
    hello = add("hello", b, type="hello", session="", to=a.agent_id, seq=0, prev="",
                body={"purpose": "Review contract v3", "requested_level": 1,
                      "nonce": "00112233445566778899aabbccddeeff", "e": x25519_public(e_b)})
    welcome = add("welcome", a, type="welcome", session="", to=b.agent_id, seq=1, prev=envelope_hash(hello),
                  body={"session": SESSION, "granted_level": 1, "expires": "2026-10-11T13:00:00Z",
                        "limits": {"asks": 50, "ask_chars": 1000}, "f": x25519_public(f_a)})
    ask = add("ask", b, type="ask", session=SESSION, to=a.agent_id, seq=2, prev=envelope_hash(welcome),
              body={"text": "What is the shared secret?"})
    answer = add("answer", a, type="answer", session=SESSION, to=b.agent_id, seq=3, prev=envelope_hash(ask),
                 body={"text": "The shared secret is GREEN-LANTERN-7.", "binding": False})
    # refuse and error are standalone examples, not part of the hello -> answer chain.
    add("refuse", a, type="refuse", session="", to=b.agent_id, seq=1, prev=envelope_hash(hello),
        body={"f": x25519_public(f_a)})
    add("error", a, type="error", session="", to=b.agent_id, seq=-1, prev="", body={"code": "bad_chain"})

    hello_raw = seal.seal_hello(e_b, x25519_public(kx_a), encode(hello))
    welcome_raw, agent_keys = seal.seal_welcome(kx_a, f_a, x25519_public(e_b), hello_raw, HANDLE, encode(welcome))
    asker_keys = seal.Keys(send=agent_keys.recv, recv=agent_keys.send)
    packages = [("hello", hello_raw), ("welcome", welcome_raw),
                ("ask", seal.seal_msg(asker_keys, seal.TO_AGENT, 1, HANDLE, encode(ask))),
                ("answer", seal.seal_msg(agent_keys, seal.TO_ASKER, 1, HANDLE, encode(answer)))]
    return {"tessera": "0.2",
            "keys": {"A": {"seed_hex": SEED_A.hex(), "agent_id": a.agent_id},
                     "B": {"seed_hex": SEED_B.hex(), "agent_id": b.agent_id}},
            "x25519": {name: {"seed_hex": seed.hex(), "public": x25519_public(x25519_from_seed(seed))}
                       for name, seed in (("kx_A", SEED_KX_A), ("e_B", SEED_E_B), ("f_A", SEED_F_A))},
            "handle": HANDLE,
            "session_keys": {"asker_to_agent": asker_keys.send.hex(), "agent_to_asker": asker_keys.recv.hex()},
            "canonical": [{"value": v, "canonical": canonical(v).decode("utf-8")} for v in CANONICAL_CASES],
            "envelopes": items,
            "packages": [{"name": n, "package": raw.decode("utf-8")} for n, raw in packages]}


SEED_C = bytes(range(64, 96))
SESSION_C = "s-fedcba9876543210"
DELEGATED_REPLY_BYTES = 6656


def build_vectors_v03() -> dict:
    """v0.3 additions: a person (B) asks a lead (A) with a mandate; A asks C on B's behalf and reports the call."""
    from localagent.protocol.tessera.mandate import sign_mandate
    a, b, c = identity_from_seed(SEED_A), identity_from_seed(SEED_B), identity_from_seed(SEED_C)
    items = []

    def add(name: str, env: dict) -> dict:
        signed = canonical({k: v for k, v in env.items() if k != "sig"}).decode("utf-8")
        items.append({"name": name, "envelope": env, "signed_bytes": signed, "hash": envelope_hash(env),
                      "canonical": encode(env).decode("utf-8")})
        return env

    def sign(identity, **fields) -> dict:
        return sign_envelope(identity, now=TIME, version="0.3", **fields)

    b_a = add("mandate_b_a", sign_mandate(b, to=a.agent_id, before=None, now=TIME))
    a_c = add("mandate_a_c", sign_mandate(a, to=c.agent_id, before=b_a, now=TIME))
    ask = add("ask_with_mandate", sign(b, type="ask", session=SESSION, to=a.agent_id, seq=2, prev="",
                                       body={"text": "What does the pricing agent charge?", "mandates": [b_a],
                                             "reply_bytes": 0}))
    delegated = add("delegated_ask", sign(a, type="ask", session=SESSION_C, to=c.agent_id, seq=2, prev="",
                                          body={"text": "What do you charge?", "mandates": [b_a, a_c],
                                                "reply_bytes": DELEGATED_REPLY_BYTES}))
    reply = add("delegated_answer", sign(c, type="answer", session=SESSION_C, to=a.agent_id, seq=3,
                                         prev=envelope_hash(delegated),
                                         body={"text": "49 euros a month.", "binding": False, "calls": []}))
    add("answer_with_calls", sign(a, type="answer", session=SESSION, to=b.agent_id, seq=3, prev=envelope_hash(ask),
                                  body={"text": "The pricing agent charges 49 euros a month.", "binding": False,
                                        "calls": [{"agent": c.agent_id, "name": "Carla's pricing agent",
                                                   "ask": delegated, "reply": reply, "error": ""}]}))
    return {"tessera": "0.3",
            "keys": {name: {"seed_hex": seed.hex(), "agent_id": identity_from_seed(seed).agent_id}
                     for name, seed in (("A", SEED_A), ("B", SEED_B), ("C", SEED_C))},
            "envelopes": items}
