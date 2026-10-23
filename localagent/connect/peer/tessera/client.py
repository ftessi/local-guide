"""The requesting side of Tessera: handshake, one ask at a time, every reply checked and recorded.
Nothing here raises to the caller: a failed record is reported as not_connected or an error reply."""
import secrets
from dataclasses import dataclass
from datetime import datetime
from http.client import HTTPException

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from localagent.connect.peer.tessera.endpoint import utc_now
from localagent.connect.peer.tessera.http import get_card as http_get_card
from localagent.connect.peer.tessera.http import post as http_post
from localagent.protocol.identity import x25519_public
from localagent.protocol.tessera import seal
from localagent.protocol.tessera.canonical import canonical
from localagent.protocol.tessera.chain import Chain
from localagent.protocol.tessera.envelope import EnvelopeError, decode, encode, parse_time, sign_envelope


REQUESTED_LEVEL = 1  # Ask
CLOSE_TIMEOUT = 5    # seconds; closing is a courtesy and must not hold up the owner's exit


@dataclass
class Reply:
    kind: str  # answer | decline | not_connected | error
    text: str = ""


class TesseraClient:
    def __init__(self, identity, protocol, *, remote_id: str, address: str, purpose: str, post=http_post,
                 get_card=http_get_card,
                 clock=utc_now, new_key=X25519PrivateKey.generate):
        self.identity, self.protocol, self.remote_id = identity, protocol, remote_id
        self.address, self.purpose, self._post, self._clock = address, purpose, post, clock
        self._new_key, self._get_card = new_key, get_card
        self._keys, self._handle, self._out, self._in = None, "", 1, 1  # the open session's encryption
        self._e = None  # the one-time key of the last hello
        self._sid: str | None = None
        self._chain = Chain()
        self._expires: datetime | None = None
        self._asks_left = 0
        self._max_chars = 0

    @property
    def session_id(self) -> str | None:
        """The open Tessera session, or None (none yet, or the last one ended with an error)."""
        return self._sid

    def _sign(self, type_: str, body: dict, *, session: str, seq: int, prev: str) -> dict:
        return sign_envelope(self.identity, type=type_, session=session, to=self.remote_id, seq=seq, prev=prev,
                             body=body, now=self._clock())

    def _check(self, env: dict, *, anyone: bool = False) -> dict:
        """A reply must come from the agent we asked and be addressed to us ('' allowed for clear errors)."""
        allowed = (self.identity.agent_id, "") if anyone or env["type"] == "error" else (self.identity.agent_id,)
        if env["from"] != self.remote_id or env["to"] not in allowed:
            raise EnvelopeError("bad_signature", "the reply comes from an unexpected agent")
        return env

    def _agent_kx(self) -> str:
        card = decode(self._get_card(self.address), self._clock())
        if card["type"] != "card" or card["from"] != self.remote_id or card["body"]["agent_id"] != self.remote_id:
            raise EnvelopeError("bad_signature", "the card isn't this agent's")
        return card["body"]["kx"]

    def _exchange(self, env: dict) -> dict:
        """Sends one message of the open session and returns the checked reply (an error envelope included)."""
        raw = seal.seal_msg(self._keys, seal.TO_AGENT, self._out, self._handle, encode(env))
        self._out += 1
        package = seal.parse(self._post(self.address, raw))
        if package["kind"] == "error":
            return self._check(decode(canonical(package["env"]), self._clock()), anyone=True)
        if package["kind"] != "msg" or package["h"] != self._handle or package["n"] != self._in:
            raise seal.SealError("bad_chain", "an unexpected package")
        self._in += 1
        return self._check(decode(seal.open_msg(self._keys, seal.TO_ASKER, package), self._clock()))

    def _connect(self) -> bool:
        try:
            kx = self._agent_kx()
            self._e = self._new_key()
            hello = self._sign("hello", {"purpose": self.purpose, "requested_level": REQUESTED_LEVEL,
                                         "nonce": secrets.token_hex(16), "e": x25519_public(self._e)},
                               session="", seq=0, prev="")
            hello_raw = seal.seal_hello(self._e, kx, encode(hello))
            package = seal.parse(self._post(self.address, hello_raw))
            if package["kind"] != "welcome":
                return False
            inner, keys, handle, f = seal.open_welcome(self._e, kx, hello_raw, package)
            reply = self._check(decode(inner, self._clock()))
        except (OSError, HTTPException, EnvelopeError, seal.SealError):
            return False
        if (reply["type"] != "welcome" or reply["body"]["f"] != f
                or not 1 <= reply["body"]["granted_level"] <= REQUESTED_LEVEL):
            return False
        chain = Chain()
        try:
            chain.append(hello)
            chain.append(reply)
        except EnvelopeError:
            return False
        body = reply["body"]
        # The other side's session id names a record file, so recording can fail: nothing is stored unless it succeeds.
        try:
            self.protocol.record_envelope(self.remote_id, body["session"], hello)
            self.protocol.record_envelope(self.remote_id, body["session"], reply)
        except (ValueError, OSError):
            return False
        self._sid, self._chain, self._expires = body["session"], chain, parse_time(body["expires"])
        self._asks_left, self._max_chars = body["limits"]["asks"], body["limits"]["ask_chars"]
        self._keys, self._handle, self._out, self._in = keys, handle, 1, 1
        return True

    def _ready(self) -> bool:
        if self._sid is not None and self._clock() < self._expires and self._asks_left > 0:
            return True
        self._sid = None
        return self._connect()

    def ask(self, text: str) -> Reply:
        reply = self._ask_once(text)
        if reply == Reply("error", "expired"):  # e.g. the other side restarted: its sessions are gone
            reply = self._ask_once(text)
        return reply

    def _ask_once(self, text: str) -> Reply:
        if not self._ready():
            return Reply("not_connected")
        if len(text) > self._max_chars:
            return Reply("error", f"question too long (max {self._max_chars} characters)")
        ask = self._sign("ask", {"text": text}, session=self._sid, seq=self._chain.next_seq(),
                         prev=self._chain.last_hash())
        try:
            self.protocol.record_envelope(self.remote_id, self._sid, ask)  # recorded first: nothing is sent unrecorded
        except (ValueError, OSError):
            self._sid = None
            return Reply("error", "could not record locally")
        self._chain.append(ask)
        self._asks_left -= 1
        try:
            reply = self._exchange(ask)
        except (OSError, HTTPException):
            self._sid = None
            return Reply("error", "unreachable")
        except (EnvelopeError, seal.SealError) as e:
            self._sid = None
            return Reply("error", f"invalid reply ({e.code})")
        if reply["type"] == "error":
            self._sid = None
            return Reply("error", reply["body"]["code"])
        try:
            if reply["session"] != self._sid:
                raise EnvelopeError("bad_chain", "reply for another session")
            self._chain.check_next(reply)
            self.protocol.record_envelope(self.remote_id, self._sid, reply)  # recorded before it is appended
        except EnvelopeError:
            self._sid = None
            return Reply("error", "bad_chain")
        except (ValueError, OSError):
            self._sid = None
            return Reply("error", "could not record locally")
        self._chain.append(reply)
        if reply["type"] == "answer":
            return Reply("answer", reply["body"]["text"])
        if reply["type"] == "decline":
            return Reply("decline")
        self._sid = None
        return Reply("error", "not_allowed")

    def close(self) -> None:
        if self._sid is None:
            return
        close = self._sign("close", {}, session=self._sid, seq=self._chain.next_seq(), prev=self._chain.last_hash())
        try:
            self.protocol.record_envelope(self.remote_id, self._sid, close)
        except (ValueError, OSError):
            self._sid = None
            return
        self._chain.append(close)
        try:
            self._post(self.address, seal.seal_msg(self._keys, seal.TO_AGENT, self._out, self._handle, encode(close)),
                       timeout=CLOSE_TIMEOUT)
            self._out += 1
        except (OSError, HTTPException):
            pass
        self._sid = None
