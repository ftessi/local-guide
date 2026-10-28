"""Tessera endpoint core: one envelope in, one envelope out (bytes to bytes), independent of the transport.
Checks run in the spec's order; only a valid `ask` in an open session reaches the guard and the model.
Nothing here raises: any failure becomes an `unavailable` error, and a session that may have a gap in its
record is closed. Records are written before memory changes, so memory never gets ahead of the record."""
import logging
import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from localagent.agent.core import is_refusal
from localagent.protocol.guard import AuthError
from localagent.protocol.identity import x25519_public
from localagent.protocol.prompts import REFUSAL
from localagent.protocol.tessera.canonical import canonical
from localagent.protocol.tessera.chain import Chain
from localagent.protocol.tessera.envelope import (EnvelopeError, decode, encode, envelope_hash,
                                                  format_time, sender_of, sign_envelope)

log = logging.getLogger(__name__)
LEVEL_TYPES = {1: frozenset({"ask", "close"})}  # what a requester may send in an open session, per level
MAX_ANSWER_CHARS = 16_000
MAX_ANSWER_BYTES = 44_000  # with the envelope around it, an answer stays well under the 64 KiB limit


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _fit_answer(text: str) -> str:
    """Cuts a model reply to the answer limits. Control characters take six bytes each in canonical JSON, so
    the byte bound is checked on the encoded text, not just the characters."""
    text = text[:MAX_ANSWER_CHARS]
    while len(canonical({"text": text})) > MAX_ANSWER_BYTES:
        text = text[:len(text) // 2]
    return text


@dataclass
class _Session:
    id: str
    peer: str
    level: int
    expires: datetime
    asks_left: int
    chain: Chain
    history: list = field(default_factory=list)
    closed: bool = False
    public: bool = False  # granted by public mode, not by the owner's acceptance
    lock: threading.Lock = field(default_factory=threading.Lock)


class TesseraEndpoint:
    def __init__(self, identity, protocol, agent, *, name: str, kx_public: str, clock=utc_now, session_seconds: int = 3600,
                 max_asks: int = 50, max_ask_chars: int = 1000, public: bool = False):
        self.identity, self.protocol, self.agent, self.name, self.clock = identity, protocol, agent, name, clock
        self.kx_public = kx_public  # the card names it; SealedEndpoint holds the private half
        self.session_seconds, self.max_asks, self.max_ask_chars = session_seconds, max_asks, max_ask_chars
        self.public = public  # strangers get level 1 (only the relay link's endpoint is public)
        self._sessions: dict[str, _Session] = {}
        self._lock = threading.Lock()

    def _sign(self, type_: str, *, to: str, seq: int, prev: str, body: dict, session: str = "") -> dict:
        return sign_envelope(self.identity, type=type_, session=session, to=to, seq=seq, prev=prev, body=body,
                             now=self.clock(), version="0.2")

    def error(self, code: str, to: str = "") -> bytes:
        try:
            self.protocol.audit.log("tessera_error", peer=to, code=code)
        except Exception:
            log.exception("Could not audit a Tessera error")
        try:
            return encode(self._sign("error", to=to, seq=-1, prev="", body={"code": code}))
        except Exception:
            log.exception("Could not sign a Tessera error")
            return b""  # last resort: the transport answers with nothing rather than crash

    def card(self) -> bytes:
        return encode(self._sign("card", to="", seq=0, prev="",
                                 body={"agent_id": self.identity.agent_id, "name": self.name, "versions": ["0.2"],
                                       "kx": self.kx_public}))

    def handle(self, raw: bytes, *, e: str | None = None, f: str | None = None) -> bytes:
        sender = ""
        try:
            try:
                env = decode(raw, self.clock())
            except EnvelopeError as e:
                return self.error(e.code, sender_of(raw))
            sender = env["from"]
            if e is not None and env["type"] != "hello":  # a hello package carries only a hello
                return self.error("malformed", sender)
            if env["to"] != self.identity.agent_id:
                return self.error("not_allowed", sender)
            if env["type"] == "hello":
                return self._hello(env, e, f)
            with self._lock:
                session = self._sessions.get(env["session"])
            if session is None or session.peer != sender:
                return self.error("expired", sender)
            with session.lock:
                return self._in_session(session, env)
        except Exception:
            log.exception("Tessera endpoint failed on an envelope")
            return self.error("unavailable", sender)

    def _hello(self, hello: dict, e: str | None, f: str | None) -> bytes:
        peer, body = hello["from"], hello["body"]
        if hello["session"] or hello["seq"] != 0 or hello["prev"]:
            return self.error("bad_chain", peer)
        if e is not None and body["e"] != e:  # the signed one-time key must be the one the package used
            return self.error("malformed", peer)
        f = f or x25519_public(X25519PrivateKey.generate())
        grant = self.protocol.peer_grant(peer, body["requested_level"])
        public = grant is None and self.public
        if public:
            grant = self.protocol.public_grant(peer)
        if grant is None:  # a public agent still refuses an id its owner rejected, without queueing it
            if not public:
                self.protocol.record_request(peer, body["purpose"], body["requested_level"])
            self.protocol.audit.log("tessera_refused", peer=peer)
            return encode(self._sign("refuse", to=peer, seq=1, prev=envelope_hash(hello), body={"f": f}))
        sid = "s-" + secrets.token_hex(8)
        expires = self.clock() + timedelta(seconds=self.session_seconds)
        welcome = self._sign("welcome", to=peer, seq=1, prev=envelope_hash(hello),
                             body={"session": sid, "granted_level": grant.level, "expires": format_time(expires),
                                   "limits": {"asks": self.max_asks, "ask_chars": self.max_ask_chars}, "f": f})
        # Records first: if either write fails, no session exists and the peer gets `unavailable`.
        self.protocol.record_envelope(peer, sid, hello)
        self.protocol.record_envelope(peer, sid, welcome)
        if public:
            self.protocol.mark_public_session(peer, sid)
            self.protocol.audit.log("tessera_session", peer=peer, session=sid, level=grant.level, public=True)
        else:
            self.protocol.audit.log("tessera_session", peer=peer, session=sid, level=grant.level)
        chain = Chain()
        chain.append(hello)
        chain.append(welcome)
        with self._lock:
            self._sessions[sid] = _Session(sid, peer, grant.level, expires, self.max_asks, chain, public=public)
        return encode(welcome)

    def _in_session(self, s: _Session, env: dict) -> bytes:
        if s.closed or self.clock() >= s.expires:
            return self.error("expired", s.peer)
        try:
            s.chain.check_next(env)
        except EnvelopeError as e:
            return self.error(e.code, s.peer)
        if env["type"] not in LEVEL_TYPES[s.level]:
            return self.error("not_allowed", s.peer)
        try:
            return self._turn(s, env)
        except Exception:
            # Something after the record may have been written but not the other half: this session can't go on.
            log.exception("Tessera session %s failed", s.id)
            s.closed = True
            return self.error("unavailable", s.peer)

    def _turn(self, s: _Session, env: dict) -> bytes:
        if env["type"] == "close":
            self.protocol.record_envelope(s.peer, s.id, env)
            s.chain.append(env)
            s.closed = True
            self.protocol.audit.log("tessera_closed", peer=s.peer, session=s.id)
            return b""
        text = env["body"]["text"]
        if s.asks_left <= 0 or len(text) > self.max_ask_chars:
            return self.error("limit", s.peer)
        try:
            # re-checked every time: removal or rejection applies at once
            peer_session = self.protocol.open_peer_session(s.peer, public=s.public)
        except AuthError:
            s.closed = True
            return self.error("not_allowed", s.peer)
        self.protocol.record_envelope(s.peer, s.id, env)  # record first, then memory
        s.chain.append(env)
        s.asks_left -= 1
        reply_text = self.agent.answer_peer(peer_session, text, s.history)
        if is_refusal(reply_text):
            kind, body, said = "decline", {}, REFUSAL
            self.protocol.audit.log("tessera_decline", peer=s.peer, session=s.id)
        else:
            said = _fit_answer(reply_text)
            kind, body = "answer", {"text": said, "binding": False}
        reply = self._sign(kind, to=s.peer, session=s.id, seq=s.chain.next_seq(), prev=s.chain.last_hash(), body=body)
        encoded = encode(reply)  # fails here, before anything is recorded, if the reply can't be encoded
        self.protocol.record_envelope(s.peer, s.id, reply)
        s.chain.append(reply)
        s.history += [{"role": "user", "content": text}, {"role": "assistant", "content": said}]
        return encoded
