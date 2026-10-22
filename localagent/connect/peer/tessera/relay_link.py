"""Tessera through a relay: the agent connects out, registers with its key and long-polls the relay. Every envelope
goes to the same TesseraEndpoint as a direct ask, so owner acceptance, the adapter gate and the records are the same.
Runs in a background thread and never raises out of it."""
import base64
import json
import logging
import re
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from localagent.protocol.tessera.envelope import MAX_BYTES
from localagent.protocol.tessera.relay import MAX_WAITING, register_message

log = logging.getLogger(__name__)
REQUEST_ID = re.compile(r"[0-9a-f]{16}")
MAX_RESPONSE = MAX_BYTES * 4 // 3 + 4096  # one base64 envelope in JSON; a relay can't make the agent hold more
REPLACED_SECONDS = 60  # a registration lost sooner than this was taken over by another copy of this agent
STOP_SECONDS = 2  # stop() doesn't wait for a held poll; the daemon thread ends when it returns


class _Unregistered(Exception):
    """The relay doesn't accept this token any more: register again."""


class RelayLink:
    def __init__(self, endpoint, identity, relay_url: str, *, name: str, listed: bool = False, description: str = "",
                 audit=None, poll_wait: float = 25.0, max_backoff: float = 60.0, say=print, pause=None,
                 opener=urlopen):
        self.endpoint, self.identity, self.relay_url = endpoint, identity, relay_url.rstrip("/")
        self.name, self.listed, self.description = name, listed, description
        self.audit, self.poll_wait, self.max_backoff, self.say, self.opener = audit, poll_wait, max_backoff, say, opener
        self._stop = threading.Event()
        self.pause = pause or self._stop.wait
        self._workers = threading.BoundedSemaphore(MAX_WAITING)  # the relay never hands out more than this
        self._thread = None
        self.address = None
        self.connected = threading.Event()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="tessera-relay", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=STOP_SECONDS)
            self._thread = None

    def _run(self) -> None:
        token, delay, lost, replaced, registered_at = None, 1.0, False, 0, 0.0
        while not self._stop.is_set():
            try:
                if token is None:
                    token = self._register()
                    registered_at = time.monotonic()
                    if not replaced:  # announced once, not on every takeover by a twin
                        self._status("connected", f"Tessera via relay: {self.address}  (agent id {self.identity.agent_id})")
                    lost = False
                    self.connected.set()
                self._poll_and_serve(token)
                delay = 1.0
            except _Unregistered:
                token = None
                if time.monotonic() - registered_at >= REPLACED_SECONDS:
                    replaced = 0  # the relay forgot us (restarted): register again at once
                    continue
                self.connected.clear()
                if not replaced:
                    self._status("replaced", "Tessera relay: this agent connected again from somewhere else "
                                             "(another serve with the same identity?); retrying")
                self.pause(min(2.0 ** replaced, self.max_backoff))
                replaced += 1
            except Exception as e:
                token = None
                self.connected.clear()
                if not lost:
                    lost = True
                    self._status("lost", f"Tessera relay {self.relay_url} unreachable ({e}); retrying")
                self.pause(delay)
                delay = min(delay * 2, self.max_backoff)

    def _status(self, state: str, text: str) -> None:
        if state == "connected":
            self.connected.set()
        self.say(text)
        if self.audit is not None:
            try:
                self.audit.log("tessera_relay", state=state, relay=self.relay_url)
            except Exception:
                log.exception("Could not audit the relay link")

    def _http(self, method: str, url: str, body: bytes | None = None, token: str = "", timeout: float = 30):
        request = Request(url, data=body, method=method, headers={"Content-Type": "application/json"})
        if token:
            request.add_header("Authorization", f"Bearer {token}")
        with self.opener(request, timeout=timeout) as response:
            data = response.read(MAX_RESPONSE + 1)
            if len(data) > MAX_RESPONSE:
                raise ValueError(f"the relay sent more than {MAX_RESPONSE} bytes")
            return response.status, data

    def _register(self) -> str:
        agent_id = self.identity.agent_id
        _, raw = self._http("GET", f"{self.relay_url}/relay/challenge")
        nonce = json.loads(raw)["nonce"]
        body = {"agent_id": agent_id, "nonce": nonce, "signature": self.identity.sign(register_message(nonce, agent_id)),
                "listed": self.listed, "name": self.name, "description": self.description}
        _, raw = self._http("POST", f"{self.relay_url}/relay/register", json.dumps(body).encode())
        data = json.loads(raw)
        self.address = str(data["address"])
        return str(data["token"])

    def _poll_and_serve(self, token: str) -> None:
        # Busy with MAX_WAITING requests, poll anyway: a link that stops polling is dropped by the relay.
        slot = self._workers.acquire(timeout=self.poll_wait)
        try:
            try:
                status, raw = self._http("GET", f"{self.relay_url}/a/{self.identity.agent_id}/next", token=token,
                                         timeout=self.poll_wait + 15)
            except HTTPError as e:
                if e.code == 401:
                    raise _Unregistered() from e
                raise
            if status == 204 or self._stop.is_set():
                if slot:
                    self._workers.release()
                return
            job = json.loads(raw)
            request_id, kind = job["request"], job["kind"]
            payload = base64.b64decode(job["payload"], validate=True)
            if not isinstance(request_id, str) or not REQUEST_ID.fullmatch(request_id) or kind not in ("envelope", "card"):
                raise ValueError("the relay sent a malformed request")
        except BaseException:
            if slot:
                self._workers.release()
            raise
        threading.Thread(target=self._serve, args=(token, request_id, kind, payload, slot), daemon=True).start()

    def _serve(self, token: str, request_id: str, kind: str, payload: bytes, slot: bool = True) -> None:
        try:
            reply = self.endpoint.card() if kind == "card" else self.endpoint.handle(payload)
            self._http("POST", f"{self.relay_url}/a/{self.identity.agent_id}/reply/{request_id}", reply, token=token)
        except Exception:
            log.exception("Could not answer a request from the Tessera relay")
        finally:
            if slot:
                self._workers.release()
