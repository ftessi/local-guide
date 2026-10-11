"""The requesting side of Tessera: handshake, one ask at a time, every reply checked and recorded.
Nothing here raises to the caller: a failed record is reported as not_connected or an error reply."""
import secrets
from dataclasses import dataclass
from datetime import datetime

from localagent.connect.peer.tessera.endpoint import utc_now
from localagent.connect.peer.tessera.http import post as http_post
from localagent.protocol.tessera.chain import Chain
from localagent.protocol.tessera.envelope import EnvelopeError, decode, encode, parse_time, sign_envelope


@dataclass
class Reply:
    kind: str  # answer | decline | not_connected | error
    text: str = ""


class TesseraClient:
    def __init__(self, identity, protocol, *, remote_id: str, address: str, purpose: str, post=http_post,
                 clock=utc_now):
        self.identity, self.protocol, self.remote_id = identity, protocol, remote_id
        self.address, self.purpose, self._post, self._clock = address, purpose, post, clock
        self._sid: str | None = None
        self._chain = Chain()
        self._expires: datetime | None = None
        self._asks_left = 0
        self._max_chars = 0

    def _sign(self, type_: str, body: dict, *, session: str, seq: int, prev: str) -> dict:
        return sign_envelope(self.identity, type=type_, session=session, to=self.remote_id, seq=seq, prev=prev,
                             body=body, now=self._clock())

    def _send(self, env: dict) -> dict:
        reply = decode(self._post(self.address, encode(env)), self._clock())
        if reply["from"] != self.remote_id or reply["to"] != self.identity.agent_id:
            raise EnvelopeError("bad_signature", "the reply comes from an unexpected agent")
        return reply

    def _connect(self) -> bool:
        hello = self._sign("hello", {"purpose": self.purpose, "requested_level": 1, "nonce": secrets.token_hex(16)},
                           session="", seq=0, prev="")
        try:
            reply = self._send(hello)
        except (OSError, EnvelopeError):
            return False
        if reply["type"] != "welcome" or reply["body"]["granted_level"] < 1:
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
            reply = self._send(ask)
        except OSError:
            self._sid = None
            return Reply("error", "unreachable")
        except EnvelopeError as e:
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
            self._post(self.address, encode(close))
        except OSError:
            pass
        self._sid = None
