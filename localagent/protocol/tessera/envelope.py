"""Tessera envelopes: one signed JSON object per message, the same shape in both directions."""
import hashlib
import json
from datetime import datetime, timedelta, timezone

from localagent.protocol.identity import AGENT_ID_RE, b64url, verify
from localagent.protocol.tessera.canonical import CanonicalError, canonical

VERSION = "0.3"
WIRE_VERSIONS = ("0.2", "0.3")
CARD_VERSION = "0.2"  # cards stay 0.2 envelopes, so v0.2 clients still read them
MAX_BYTES = 64 * 1024  # a whole package on the wire (seal.py)
INNER_MAX = 46 * 1024  # the signed message inside it: base64 of this still fits a package
CLOCK_SKEW = timedelta(minutes=5)
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
FIELDS = frozenset({"tessera", "type", "session", "from", "to", "seq", "prev", "time", "body", "sig"})
ERROR_CODES = frozenset({"bad_signature", "bad_chain", "stale", "too_large", "expired", "limit", "not_allowed",
                         "malformed", "unavailable", "replay"})
BODIES = {
    "hello": {"purpose": str, "requested_level": int, "nonce": str, "e": str},
    "welcome": {"session": str, "granted_level": int, "expires": str, "limits": dict, "f": str},
    "refuse": {"f": str},
    "ask": {"text": str},
    "answer": {"text": str, "binding": bool},
    "decline": {},
    "close": {},
    "error": {"code": str},
    "card": {"agent_id": str, "name": str, "versions": list, "kx": str},
}
BODIES_V01 = {**BODIES, "hello": {"purpose": str, "requested_level": int, "nonce": str},
              "welcome": {"session": str, "granted_level": int, "expires": str, "limits": dict}, "refuse": {},
              "card": {"agent_id": str, "name": str, "versions": list}}
BODIES_V03 = {**BODIES, "ask": {"text": str, "mandates": list, "reply_bytes": int},
              "answer": {"text": str, "binding": bool, "calls": list}, "mandate": {"expires": str}}
SHAPES = {"0.3": BODIES_V03, "0.2": BODIES, "0.1": BODIES_V01}  # 0.1 only for records written before v0.2
TEXT_LIMITS = {"purpose": 200, "nonce": 64, "session": 64, "expires": 20, "name": 100, "code": 32, "agent_id": 43, "e": 43, "f": 43, "kx": 43}


class EnvelopeError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def format_time(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime(TIME_FORMAT)


def parse_time(text: str) -> datetime:
    parsed = datetime.strptime(text, TIME_FORMAT).replace(tzinfo=timezone.utc)
    if format_time(parsed) != text:
        raise ValueError(f"{text!r} is not the canonical time spelling")
    return parsed


def encode(env: dict) -> bytes:
    return canonical(env)


def envelope_hash(env: dict) -> str:
    return b64url(hashlib.sha256(canonical(env)).digest())


def sign_envelope(identity, *, type: str, session: str, to: str, seq: int, prev: str, body: dict,
                  now: datetime, version: str = VERSION) -> dict:
    env = {"tessera": version, "type": type, "session": session, "from": identity.agent_id, "to": to,
           "seq": seq, "prev": prev, "time": format_time(now), "body": body}
    env["sig"] = identity.sign(canonical(env))
    return env


def _is(value, kind) -> bool:
    return isinstance(value, kind) and not (kind is int and isinstance(value, bool))


def check_shape(env, versions=WIRE_VERSIONS) -> None:
    def bad(why: str):
        raise EnvelopeError("malformed", why)

    if not isinstance(env, dict) or set(env) != FIELDS:
        bad("an envelope has exactly the fields " + ", ".join(sorted(FIELDS)))
    if not isinstance(env["tessera"], str) or env["tessera"] not in versions:
        bad(f"unsupported version {env['tessera']!r}")
    bodies = SHAPES[env["tessera"]]
    if not isinstance(env["type"], str) or env["type"] not in bodies:
        bad(f"unknown type {env['type']!r}")
    for f in ("session", "from", "to", "prev", "time", "sig"):
        if not isinstance(env[f], str):
            bad(f"'{f}' must be text")
    if not _is(env["seq"], int) or env["seq"] < -1:
        bad("'seq' must be an integer ≥ -1")
    if not AGENT_ID_RE.fullmatch(env["from"]) or (env["to"] and not AGENT_ID_RE.fullmatch(env["to"])):
        bad("'from'/'to' must be agent ids")
    if len(env["session"]) > 64 or len(env["prev"]) > 64:
        bad("'session'/'prev' too long")
    try:
        parse_time(env["time"])
    except ValueError:
        bad("'time' must look like 2026-10-11T12:00:00Z")
    body, spec = env["body"], bodies[env["type"]]
    if not isinstance(body, dict) or set(body) != set(spec):
        bad(f"a {env['type']} body has exactly: {', '.join(spec) or 'nothing'}")
    for key, kind in spec.items():
        if not _is(body[key], kind):
            bad(f"'{key}' has the wrong type")
        if kind is str and len(body[key]) > TEXT_LIMITS.get(key, MAX_BYTES):
            bad(f"'{key}' is too long")
    t = env["type"]
    if t in ("hello", "welcome") and not 0 <= body["requested_level" if t == "hello" else "granted_level"] <= 4:
        bad("levels go from 0 to 4")
    if t == "answer" and body["binding"] is not False:
        bad("answers are never binding at levels 1 and 2")
    if t == "error" and body["code"] not in ERROR_CODES:
        bad(f"unknown error code {body['code']!r}")
    if t == "welcome" and (set(body["limits"]) != {"asks", "ask_chars"}
                           or not all(_is(v, int) and v >= 0 for v in body["limits"].values())):
        bad("limits are {asks, ask_chars}, both integers")
    if t == "ask" and "reply_bytes" in body and body["reply_bytes"] < 0:
        bad("'reply_bytes' must be ≥ 0")
    if t in ("welcome", "mandate"):
        try:
            parse_time(body["expires"])
        except ValueError:
            bad("'expires' must look like 2026-10-11T13:00:00Z")
    for key in ("e", "f", "kx"):
        if key in body and not AGENT_ID_RE.fullmatch(body[key]):
            bad(f"'{key}' must be a 43-character base64url key")
    if t == "card":
        if not AGENT_ID_RE.fullmatch(body["agent_id"]):
            bad("'agent_id' must be an agent id")
        if not all(isinstance(v, str) for v in body["versions"]):
            bad("versions are text")


def _no_duplicate_keys(pairs):
    keys = [k for k, _ in pairs]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate key")
    return dict(pairs)


def _no_constants(name):
    raise ValueError(f"{name} is not JSON")


def check_signed(env, versions=WIRE_VERSIONS) -> dict:
    """Shape and signature only, no clock: for envelopes carried inside others (mandates, reported calls)."""
    check_shape(env, versions)
    try:
        signed = canonical({k: v for k, v in env.items() if k != "sig"})
    except CanonicalError as e:
        raise EnvelopeError("malformed", str(e)) from None
    if not verify(env["from"], signed, env["sig"]):
        raise EnvelopeError("bad_signature", "the signature doesn't match the sender")
    return env


def decode(raw: bytes, now: datetime, versions=WIRE_VERSIONS) -> dict:
    """Bytes to a checked envelope: size, JSON, shape, signature, time. Chain and session checks are the caller's."""
    if len(raw) > INNER_MAX:
        raise EnvelopeError("too_large", f"envelopes are at most {INNER_MAX} bytes")
    try:
        env = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicate_keys, parse_constant=_no_constants)
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise EnvelopeError("malformed", "not a JSON object") from None
    check_signed(env, versions)
    if abs(parse_time(env["time"]) - now) > CLOCK_SKEW:
        raise EnvelopeError("stale", "the envelope's time is more than 5 minutes from ours")
    return env


def sender_of(raw: bytes) -> str:
    """Best-effort sender of an envelope that failed its checks, only to address the error reply. Never trusted."""
    try:
        value = json.loads(raw.decode("utf-8")).get("from")
    except (UnicodeDecodeError, ValueError, AttributeError, RecursionError):
        return ""
    return value if isinstance(value, str) and AGENT_ID_RE.fullmatch(value) else ""
