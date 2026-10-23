"""Tessera v0.2 on the agent's side: opens each package, hands the signed message inside to TesseraEndpoint and
seals its reply. Keeps every session's keys and counters by routing handle, and remembers recent hellos so a
replayed one is refused. Nothing here raises: problems become error packages."""
import json
import logging
import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from localagent.protocol.identity import x25519_public
from localagent.protocol.tessera import seal
from localagent.protocol.tessera.envelope import parse_time

log = logging.getLogger(__name__)
REPLAY_SECONDS = 600  # twice the allowed clock difference
MAX_HELLOS = 100_000


@dataclass(eq=False)
class _Link:
    keys: seal.Keys
    expires: datetime
    next_in: int = 1
    next_out: int = 1
    lock: threading.Lock = field(default_factory=threading.Lock)


class SealedEndpoint:
    def __init__(self, endpoint, kx: X25519PrivateKey, *, clock=None, new_key=X25519PrivateKey.generate):
        self.endpoint, self.kx, self.new_key = endpoint, kx, new_key
        self.clock = clock or endpoint.clock
        self._links: dict[str, _Link] = {}
        self._hellos: dict[str, datetime] = {}  # one-time key -> when it may be forgotten
        self._lock = threading.Lock()

    def card(self) -> bytes:
        return self.endpoint.card()

    def handle(self, raw: bytes) -> bytes:
        try:
            with self._lock:
                self._prune(self.clock())
            package = seal.parse(raw)
            if package["kind"] == "hello":
                return self._hello(raw, package)
            if package["kind"] == "msg":
                return self._msg(package)
            return self._clear_error("malformed")
        except seal.SealError as e:
            return self._clear_error(e.code)
        except Exception:
            log.exception("Tessera failed on a package")
            return self._clear_error("unavailable")

    def _clear_error(self, code: str) -> bytes:
        env = self.endpoint.error(code)
        return seal.error_package(env) if env else b""

    def _prune(self, now: datetime) -> None:
        self._hellos = {e: until for e, until in self._hellos.items() if until > now}
        self._links = {h: link for h, link in self._links.items() if link.expires > now}

    def _hello(self, raw: bytes, package: dict) -> bytes:
        e_pub, inner = seal.open_hello(self.kx, package)
        with self._lock:
            if e_pub in self._hellos:
                return self._clear_error("replay")
            if len(self._hellos) >= MAX_HELLOS:
                self._hellos.pop(next(iter(self._hellos)))  # forget the oldest
            self._hellos[e_pub] = self.clock() + timedelta(seconds=REPLAY_SECONDS)
        f = self.new_key()
        reply = self.endpoint.handle(inner, e=e_pub, f=x25519_public(f))
        env = json.loads(reply)  # our own signed message
        if env["type"] == "error":  # a stale or badly signed hello: no session, no keys, and not who asked
            return self._clear_error(env["body"]["code"])
        handle = secrets.token_hex(8)
        sealed, keys = seal.seal_welcome(self.kx, f, e_pub, raw, handle, reply)
        if env["type"] == "welcome":
            with self._lock:
                self._links[handle] = _Link(keys, parse_time(env["body"]["expires"]))
        return sealed

    def _msg(self, package: dict) -> bytes:
        handle = package["h"]
        with self._lock:
            link = self._links.get(handle)
        if link is None:  # unknown, expired, or the agent restarted
            return self._clear_error("expired")
        with link.lock:
            inner = seal.open_msg(link.keys, seal.TO_AGENT, package)
            if package["n"] != link.next_in:  # maybe not even from the asker: answered in clear, no counter spent
                return self._clear_error("replay")
            try:
                is_hello = json.loads(inner).get("type") == "hello"
            except (ValueError, AttributeError):
                is_hello = False  # the inner endpoint reports it as malformed
            if is_hello:  # a session message never opens another session
                link.next_in += 1
                return self._out(link, handle, self.endpoint.error("not_allowed"))
            link.next_in += 1
            reply = self.endpoint.handle(inner)
            if not reply:  # close
                with self._lock:
                    self._links.pop(handle, None)
                return b""
            return self._out(link, handle, reply)

    def _out(self, link: _Link, handle: str, inner: bytes) -> bytes:
        sealed = seal.seal_msg(link.keys, seal.TO_ASKER, link.next_out, handle, inner)
        link.next_out += 1
        return sealed
