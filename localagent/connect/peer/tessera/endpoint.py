"""Tessera endpoint core: one envelope in, one envelope out (bytes to bytes), independent of the transport.
Checks run in the spec's order; only a valid `ask` in an open session reaches the guard and the model."""
import logging
import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from localagent.agent.core import is_refusal
from localagent.protocol.guard import AuthError
from localagent.protocol.prompts import REFUSAL
from localagent.protocol.tessera.chain import Chain
from localagent.protocol.tessera.envelope import (VERSION, EnvelopeError, decode, encode, envelope_hash,
                                                  format_time, sender_of, sign_envelope)

log = logging.getLogger(__name__)
LEVEL_TYPES = {1: frozenset({"ask", "close"})}  # what a requester may send in an open session, per level


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


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
    lock: threading.Lock = field(default_factory=threading.Lock)


class TesseraEndpoint:
    def __init__(self, identity, protocol, agent, *, name: str, clock=utc_now, session_seconds: int = 3600,
                 max_asks: int = 50, max_ask_chars: int = 1000):
        self.identity, self.protocol, self.agent, self.name, self.clock = identity, protocol, agent, name, clock
        self.session_seconds, self.max_asks, self.max_ask_chars = session_seconds, max_asks, max_ask_chars
        self._sessions: dict[str, _Session] = {}
        self._lock = threading.Lock()

    def _sign(self, type_: str, *, to: str, seq: int, prev: str, body: dict, session: str = "") -> dict:
        return sign_envelope(self.identity, type=type_, session=session, to=to, seq=seq, prev=prev, body=body,
                             now=self.clock())

    def _error(self, code: str, to: str) -> bytes:
        self.protocol.audit.log("tessera_error", peer=to, code=code)
        return encode(self._sign("error", to=to, seq=-1, prev="", body={"code": code}))

    def card(self) -> bytes:
        return encode(self._sign("card", to="", seq=0, prev="",
                                 body={"agent_id": self.identity.agent_id, "name": self.name, "versions": [VERSION]}))

    def handle(self, raw: bytes) -> bytes:
        try:
            env = decode(raw, self.clock())
        except EnvelopeError as e:
            return self._error(e.code, sender_of(raw))
        if env["to"] != self.identity.agent_id:
            return self._error("not_allowed", env["from"])
        if env["type"] == "hello":
            return self._hello(env)
        with self._lock:
            session = self._sessions.get(env["session"])
        if session is None or session.peer != env["from"]:
            return self._error("expired", env["from"])
        with session.lock:
            return self._in_session(session, env)

    def _hello(self, hello: dict) -> bytes:
        peer, body = hello["from"], hello["body"]
        if hello["session"] or hello["seq"] != 0 or hello["prev"]:
            return self._error("bad_chain", peer)
        grant = self.protocol.peer_grant(peer, body["requested_level"])
        if grant is None:
            self.protocol.record_request(peer, body["purpose"], body["requested_level"])
            self.protocol.audit.log("tessera_refused", peer=peer)
            return encode(self._sign("refuse", to=peer, seq=1, prev=envelope_hash(hello), body={}))
        sid = "s-" + secrets.token_hex(8)
        expires = self.clock() + timedelta(seconds=self.session_seconds)
        welcome = self._sign("welcome", to=peer, seq=1, prev=envelope_hash(hello),
                             body={"session": sid, "granted_level": grant.level, "expires": format_time(expires),
                                   "limits": {"asks": self.max_asks, "ask_chars": self.max_ask_chars}})
        chain = Chain()
        chain.append(hello)
        chain.append(welcome)
        with self._lock:
            self._sessions[sid] = _Session(sid, peer, grant.level, expires, self.max_asks, chain)
        for env in (hello, welcome):
            self.protocol.record_envelope(peer, sid, env)
        self.protocol.audit.log("tessera_session", peer=peer, session=sid, level=grant.level)
        return encode(welcome)

    def _in_session(self, s: _Session, env: dict) -> bytes:
        if s.closed or self.clock() >= s.expires:
            return self._error("expired", s.peer)
        try:
            s.chain.check_next(env)
        except EnvelopeError as e:
            return self._error(e.code, s.peer)
        if env["type"] not in LEVEL_TYPES[s.level]:
            return self._error("not_allowed", s.peer)
        if env["type"] == "close":
            s.chain.append(env)
            self.protocol.record_envelope(s.peer, s.id, env)
            s.closed = True
            self.protocol.audit.log("tessera_closed", peer=s.peer, session=s.id)
            return b""
        text = env["body"]["text"]
        if s.asks_left <= 0 or len(text) > self.max_ask_chars:
            return self._error("limit", s.peer)
        try:
            peer_session = self.protocol.open_peer_session(s.peer)  # re-checked every time: removal applies at once
        except AuthError:
            s.closed = True
            return self._error("not_allowed", s.peer)
        s.chain.append(env)
        self.protocol.record_envelope(s.peer, s.id, env)
        s.asks_left -= 1
        try:
            reply_text = self.agent.answer_peer(peer_session, text, s.history)
        except Exception:
            log.exception("Answering a Tessera ask failed")
            s.closed = True  # the ask is in the record without a reply: this session can't continue
            return self._error("unavailable", s.peer)
        if is_refusal(reply_text):
            kind, body, said = "decline", {}, REFUSAL
            self.protocol.audit.log("tessera_decline", peer=s.peer, session=s.id)
        else:
            kind, body, said = "answer", {"text": reply_text, "binding": False}, reply_text
        reply = self._sign(kind, to=s.peer, session=s.id, seq=s.chain.next_seq(), prev=s.chain.last_hash(), body=body)
        s.chain.append(reply)
        self.protocol.record_envelope(s.peer, s.id, reply)
        s.history += [{"role": "user", "content": text}, {"role": "assistant", "content": said}]
        return encode(reply)
