"""The relay's HTTP routes. Askers use the same POST /tessera as with a direct agent, under /a/<agent id>; agents
connect out, register with their key and long-poll for requests. Standard library only."""
import base64
import json
import logging
import os
import re
import secrets
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from time import sleep
from pathlib import Path
from urllib.parse import urlsplit

from localagent.protocol.tessera.envelope import MAX_BYTES
from localagent.protocol.tessera.inspection import MAX_UPLOAD
from localagent.relay.core import BadToken, Busy, Full, Offline, Refused, Relay, TimedOut
from localagent.relay.limits import RateLimiter
from localagent.relay.log import RelayLog

log = logging.getLogger(__name__)
MAX_REGISTER_BYTES = 4096
DISCARD_BYTES = 1 << 20  # a too-large body up to this size is read and dropped, so the client sees the 413
AGENT_ROUTE = re.compile(r"/a/([A-Za-z0-9_-]{43})/(tessera|tessera/card|next|reply/([0-9a-f]{16}))")
STATUS = {Offline: 503, Busy: 503, Full: 503, TimedOut: 504, BadToken: 401, Refused: 401}


class _BadRequest(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _handler(server):
    class Handler(BaseHTTPRequestHandler):
        timeout = 30  # seconds; a client that stops sending doesn't hold a thread forever

        def do_GET(self):
            self._route("GET")

        def do_POST(self):
            self._route("POST")

        def _route(self, method: str):
            path = urlsplit(self.path).path
            relay = server.relay
            try:
                if method == "GET" and path == "/relay/challenge":
                    return self._json(200, {"nonce": relay.challenge()})
                if method == "POST" and path == "/relay/register":
                    return self._register()
                if method == "POST" and path == "/relay/inspection":
                    return self._inspection()
                if method == "GET" and path == "/agents":
                    return self._json(200, relay.directory(self._base()))
                match = AGENT_ROUTE.fullmatch(path)
                if not match:
                    return self._send(404)
                agent_id, what, request_id = match.groups()
                if method == "POST" and what == "tessera":
                    if not server.chat_limit.allow(self._client_ip()):
                        server.log_event("deliver", agent=agent_id, kind="envelope", bytes_in=0, bytes_out=0, ms=0,
                                         outcome="rate_limited")
                        return self._json(429, {"error": "too many messages; slow down"})
                    return self._deliver(agent_id, "envelope", lambda: self._body(MAX_BYTES), server.deliver_timeout)
                if method == "GET" and what == "tessera/card":
                    return self._deliver(agent_id, "card", lambda: b"", server.card_timeout)
                if method == "GET" and what == "next":
                    request = relay.next_request(agent_id, self._token(), server.poll_wait)
                    if request is None:
                        return self._send(204)
                    return self._json(200, {"request": request.id, "kind": request.kind,
                                            "payload": base64.b64encode(request.payload).decode()})
                if method == "POST" and request_id:
                    relay.reply(agent_id, self._token(), request_id, self._body(MAX_BYTES + 1))
                    return self._send(204)
                return self._send(404)
            except _BadRequest as e:
                self._json(e.status, {"error": str(e)})
            except tuple(STATUS) as e:
                self._json(STATUS[type(e)], {"error": str(e)})
            except Exception:
                log.exception("Relay failed on %s %s", method, path)
                try:
                    self._json(500, {"error": "relay error"})
                except Exception:
                    pass

        def _deliver(self, agent_id: str, kind: str, read_body, timeout: float):
            start, body, reply, outcome = time.monotonic(), b"", b"", "error"
            try:
                body = read_body()
                reply = server.relay.deliver(agent_id, kind, body, timeout)
                outcome = "answered"
                return self._send(200, reply)
            except _BadRequest as e:
                outcome = "too_large" if e.status == 413 else "malformed"
                raise
            except (Offline, Busy, TimedOut) as e:
                outcome = {Offline: "offline", Busy: "busy", TimedOut: "timeout"}[type(e)]
                raise
            finally:
                server.log_event("deliver", agent=agent_id, kind=kind, bytes_in=len(body), bytes_out=len(reply),
                                 ms=int((time.monotonic() - start) * 1000), outcome=outcome)

        def _inspection(self):
            if server.inbox is None:
                return self._send(404)
            if not server.upload_limit.allow(self._client_ip()):
                server.log_event("inspection", bytes=0, outcome="rate_limited")
                return self._json(429, {"error": "too many uploads; slow down"})
            try:
                body = self._body(MAX_UPLOAD)
            except _BadRequest:
                server.log_event("inspection", bytes=0, outcome="too_large")
                raise
            if not server.store_upload(body):
                server.log_event("inspection", bytes=len(body), outcome="full")
                return self._json(503, {"error": "the inspection inbox is full; try later"})
            server.log_event("inspection", bytes=len(body), outcome="stored")
            return self._send(204)

        def _register(self):
            try:
                data = json.loads(self._body(MAX_REGISTER_BYTES))
            except ValueError as e:
                raise _BadRequest(400, "the registration must be JSON") from e
            fields_ok = (isinstance(data, dict)
                         and all(isinstance(data.get(k), str) for k in ("agent_id", "nonce", "signature"))
                         and isinstance(data.get("listed", False), bool) and isinstance(data.get("public", False), bool)
                         and all(isinstance(data.get(k, ""), str) for k in ("name", "description")))
            if not fields_ok:
                raise _BadRequest(400, "agent_id, nonce and signature are required texts")
            token = server.relay.register(data["agent_id"], data["nonce"], data["signature"],
                                          listed=data.get("listed", False), name=data.get("name", ""),
                                          description=data.get("description", ""), public=data.get("public", False))
            return self._json(200, {"token": token, "address": f"{self._base()}/a/{data['agent_id']}"})

        def _body(self, limit: int) -> bytes:
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError as e:
                raise _BadRequest(400, "bad Content-Length") from e
            if length < 0:
                raise _BadRequest(400, "bad Content-Length")
            if length > limit:
                if length <= DISCARD_BYTES:
                    self.rfile.read(length)
                raise _BadRequest(413, f"larger than {limit} bytes")
            return self.rfile.read(length)

        def _client_ip(self) -> str:
            """The visitor's address. Behind the operator's own proxy (--trusted-proxy), the last X-Forwarded-For
            entry: the one that proxy added; earlier entries are whatever the visitor sent."""
            ip = self.client_address[0]
            forwarded = self.headers.get("X-Forwarded-For") or ""
            if server.trusted_proxy and ip == server.trusted_proxy and forwarded.strip():
                return forwarded.split(",")[-1].strip()
            return ip

        def _token(self) -> str:
            value = self.headers.get("Authorization") or ""
            return value[len("Bearer "):] if value.startswith("Bearer ") else ""

        def _base(self) -> str:
            return server.public_url or f"http://{self.headers.get('Host') or f'{server.host}:{server.port}'}"

        def _json(self, status: int, data) -> None:
            self._send(status, json.dumps(data).encode())

        def _send(self, status: int, data: bytes = b"") -> None:
            self.send_response(status)
            if status != 204:
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if status != 204:
                self.wfile.write(data)

        def log_message(self, *args):  # no request lines on the console
            pass

    return Handler


class RelayServer:
    def __init__(self, relay: Relay, host: str = "127.0.0.1", port: int = 8200, *, public_url: str | None = None,
                 deliver_timeout: float = 300.0, card_timeout: float = 30.0, poll_wait: float = 25.0,
                 sweep_seconds: float = 5.0, log: RelayLog | None = None, inbox: Path | None = None,
                 inbox_bytes: int = 1 << 30, trusted_proxy: str | None = None, chat_per_minute: int = 30,
                 uploads_per_minute: int = 10):
        self.relay = relay
        self.public_url = (public_url or "").rstrip("/") or None
        self.deliver_timeout, self.card_timeout, self.poll_wait = deliver_timeout, card_timeout, poll_wait
        self.sweep_seconds = sweep_seconds
        self.log, self.inbox, self.inbox_bytes = log, (Path(inbox) if inbox else None), inbox_bytes
        self._inbox_lock = threading.Lock()
        self.trusted_proxy = trusted_proxy
        self.chat_limit, self.upload_limit = RateLimiter(chat_per_minute), RateLimiter(uploads_per_minute)
        if log is not None:
            relay.on_event = self.log_event
        if self.inbox is not None:
            self.inbox.mkdir(parents=True, exist_ok=True)
        self._httpd = ThreadingHTTPServer((host, port), _handler(self))
        self._httpd.daemon_threads = True
        self.host, self.port = host, self._httpd.server_address[1]
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    def log_event(self, event: str, **fields) -> None:
        if self.log is not None:
            try:
                self.log.write(event, **fields)
            except OSError:
                log.exception("Could not write the relay's connection log")

    def store_upload(self, body: bytes) -> bool:
        """Writes an inspection upload to the inbox; False when the inbox is full."""
        with self._inbox_lock:
            used = sum(entry.stat().st_size for entry in os.scandir(self.inbox) if entry.is_file())
            if used + len(body) > self.inbox_bytes:
                return False
            name = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{secrets.token_hex(8)}.sealed"
            (Path(self.inbox) / name).write_bytes(body)
            return True

    def start(self) -> None:
        for target, name in ((self._httpd.serve_forever, "relay-http"), (self._sweep_loop, "relay-sweep")):
            thread = threading.Thread(target=target, name=name, daemon=True)
            thread.start()
            self._threads.append(thread)

    def _sweep_loop(self) -> None:
        while not self._stop.wait(self.sweep_seconds):
            self.relay.sweep()

    def stop(self) -> None:
        self._stop.set()
        if self._threads:  # shutdown() blocks until serve_forever() has returned, so only if it ran
            self._httpd.shutdown()
            self._threads = []
        self._httpd.server_close()


def run_relay(host: str, port: int, max_agents: int, public_url: str | None = None, data_dir: str = "relay-data",
              log_days: int = 90, inbox_mb: int = 1024, trusted_proxy: str | None = None) -> int:
    data = Path(data_dir)
    try:
        server = RelayServer(Relay(max_agents=max_agents), host, port, public_url=public_url,
                             log=RelayLog(data / "connections.jsonl", log_days), inbox=data / "inbox",
                             inbox_bytes=inbox_mb * 1024 * 1024, trusted_proxy=trusted_proxy)
    except OSError as e:
        print(f"Error: the relay can't start on {host}:{port} with data in {data} ({e})", file=sys.stderr)
        return 2
    server.start()
    print(f"Tessera relay on http://{server.host}:{server.port}  (data in {data}; agents set `relay:` to its public "
          "address; Ctrl+C stops it)", flush=True)
    try:
        while True:
            sleep(1)  # short sleeps so Ctrl+C works on Windows too
    except KeyboardInterrupt:
        print("\nRelay stopped.")
    finally:
        server.stop()
    return 0
