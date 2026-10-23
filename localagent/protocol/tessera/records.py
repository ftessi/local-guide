"""Tessera records at rest: every line of tessera/*.jsonl is encrypted with the agent's record key and bound to its
file name, so a line can't be read without the key or moved to another file."""
import json
import secrets

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

from localagent.protocol.identity import b64url, b64url_decode
from localagent.protocol.tessera.canonical import canonical


def is_sealed(line) -> bool:
    return isinstance(line, dict) and set(line) == {"v", "n", "ct"} and line["v"] == 1


def seal_line(key: bytes, name: str, record: dict) -> dict:
    nonce = secrets.token_bytes(12)
    return {"v": 1, "n": b64url(nonce), "ct": b64url(ChaCha20Poly1305(key).encrypt(nonce, canonical(record),
                                                                                  name.encode()))}


def open_line(key: bytes, name: str, line) -> dict:
    if not is_sealed(line):
        raise ValueError(f"tessera/{name}.jsonl has a line that isn't encrypted")
    try:
        data = ChaCha20Poly1305(key).decrypt(b64url_decode(line["n"]), b64url_decode(line["ct"]), name.encode())
        return json.loads(data)
    except (InvalidTag, ValueError) as e:
        raise ValueError(f"tessera/{name}.jsonl has a line this agent's record key can't open") from e
