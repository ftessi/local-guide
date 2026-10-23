"""Tessera v0.2 packages: the signed message travels encrypted, after the Noise IK pattern (X25519, HKDF-SHA256,
ChaCha20-Poly1305). Pure functions: every key and one-time key comes from the caller, so test vectors are fixed bytes.

hello:   k = HKDF(X25519(e, S), e‖S, "tessera 0.2 hello")            nonce(0, 0)
welcome: k_a‖k_b = HKDF(X25519(f, e)‖X25519(S, e), SHA-256(hello), "tessera 0.2 session")
         the agent seals with k_b, nonce(1, 0); later messages: asker k_a / nonce(0, n), agent k_b / nonce(1, n)."""
import hashlib
import json
import re
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from localagent.protocol.identity import b64url, b64url_decode, x25519_from_b64, x25519_public
from localagent.protocol.tessera.canonical import canonical
from localagent.protocol.tessera.envelope import MAX_BYTES

VERSION = "0.2"
TO_AGENT, TO_ASKER = 0, 1
HANDLE = re.compile(r"[0-9a-f]{16}")
KINDS = {"hello": {"e", "ct"}, "welcome": {"h", "f", "ct"}, "msg": {"h", "n", "ct"}, "error": {"env"}}
MAX_COUNTER = 2 ** 53 - 1


class SealError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Keys:
    send: bytes
    recv: bytes


def derive(ikm: bytes, salt: bytes, info: str, n: int) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=n, salt=salt, info=info.encode()).derive(ikm)


def _nonce(direction: int, counter: int) -> bytes:
    return direction.to_bytes(4, "big") + counter.to_bytes(8, "big")


def _dh(private: X25519PrivateKey, public_b64: str) -> bytes:
    try:
        return private.exchange(x25519_from_b64(public_b64))
    except ValueError as e:  # not a key, or a point that gives no shared secret
        raise SealError("malformed", "bad public key") from e


def _seal(key: bytes, nonce: bytes, package: dict, inner: bytes) -> bytes:
    ct = ChaCha20Poly1305(key).encrypt(nonce, inner, canonical(package))
    return canonical({**package, "ct": b64url(ct)})


def _open(key: bytes, nonce: bytes, package: dict) -> bytes:
    aad = canonical({k: v for k, v in package.items() if k != "ct"})
    try:
        return ChaCha20Poly1305(key).decrypt(nonce, b64url_decode(package["ct"]), aad)
    except (InvalidTag, ValueError):
        raise SealError("bad_signature", "the package doesn't decrypt") from None


def parse(raw: bytes) -> dict:
    """Bytes to a well-formed package. Nothing is decrypted here."""
    if len(raw) > MAX_BYTES:
        raise SealError("too_large", f"packages are at most {MAX_BYTES} bytes")
    try:
        p = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise SealError("malformed", "not a JSON package") from None
    if (not isinstance(p, dict) or p.get("tessera") != VERSION or p.get("kind") not in KINDS
            or set(p) != KINDS[p["kind"]] | {"tessera", "kind"}):
        raise SealError("malformed", "not a Tessera 0.2 package")
    if any(k in p and not isinstance(p[k], str) for k in ("e", "f", "ct")):
        raise SealError("malformed", "e, f and ct are text")
    if "h" in p and not (isinstance(p["h"], str) and HANDLE.fullmatch(p["h"])):
        raise SealError("malformed", "bad handle")
    if "n" in p and not (type(p["n"]) is int and 1 <= p["n"] <= MAX_COUNTER):
        raise SealError("malformed", "bad counter")
    if "env" in p and not isinstance(p["env"], dict):
        raise SealError("malformed", "an error package carries an envelope")
    return p


def _hello_key(ss1: bytes, e_pub: str, s_pub: str) -> bytes:
    return derive(ss1, b64url_decode(e_pub) + b64url_decode(s_pub), "tessera 0.2 hello", 32)


def _session_keys(ss2: bytes, ss1: bytes, hello_raw: bytes) -> tuple[bytes, bytes]:
    okm = derive(ss2 + ss1, hashlib.sha256(hello_raw).digest(), "tessera 0.2 session", 64)
    return okm[:32], okm[32:]  # asker -> agent, agent -> asker


def seal_hello(e: X25519PrivateKey, agent_kx: str, inner: bytes) -> bytes:
    e_pub = x25519_public(e)
    key = _hello_key(_dh(e, agent_kx), e_pub, agent_kx)
    return _seal(key, _nonce(TO_AGENT, 0), {"tessera": VERSION, "kind": "hello", "e": e_pub}, inner)


def open_hello(kx: X25519PrivateKey, package: dict) -> tuple[str, bytes]:
    if package["kind"] != "hello":
        raise SealError("malformed", "expected a hello")
    key = _hello_key(_dh(kx, package["e"]), package["e"], x25519_public(kx))
    return package["e"], _open(key, _nonce(TO_AGENT, 0), package)


def seal_welcome(kx: X25519PrivateKey, f: X25519PrivateKey, e_pub: str, hello_raw: bytes, handle: str,
                 inner: bytes) -> tuple[bytes, Keys]:
    k_a, k_b = _session_keys(_dh(f, e_pub), _dh(kx, e_pub), hello_raw)
    package = {"tessera": VERSION, "kind": "welcome", "h": handle, "f": x25519_public(f)}
    return _seal(k_b, _nonce(TO_ASKER, 0), package, inner), Keys(send=k_b, recv=k_a)


def open_welcome(e: X25519PrivateKey, agent_kx: str, hello_raw: bytes, package: dict) -> tuple[bytes, Keys, str, str]:
    if package["kind"] != "welcome":
        raise SealError("malformed", "expected a welcome")
    k_a, k_b = _session_keys(_dh(e, package["f"]), _dh(e, agent_kx), hello_raw)
    return _open(k_b, _nonce(TO_ASKER, 0), package), Keys(send=k_a, recv=k_b), package["h"], package["f"]


def seal_msg(keys: Keys, direction: int, n: int, handle: str, inner: bytes) -> bytes:
    return _seal(keys.send, _nonce(direction, n), {"tessera": VERSION, "kind": "msg", "h": handle, "n": n}, inner)


def open_msg(keys: Keys, direction: int, package: dict) -> bytes:
    """`direction` is the sender's: TO_AGENT for what the asker sent."""
    if package["kind"] != "msg":
        raise SealError("malformed", "expected a message")
    return _open(keys.recv, _nonce(direction, package["n"]), package)


def error_package(env_raw: bytes) -> bytes:
    """Only before a session's keys exist: a signed error envelope, in clear."""
    return canonical({"tessera": VERSION, "kind": "error", "env": json.loads(env_raw)})
