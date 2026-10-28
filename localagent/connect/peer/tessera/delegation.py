"""Delegation (v0.3): a lead asks its owner's remotes on behalf of whoever asked it, and reports every call.
Each call carries the mandate chain, so every callee checks the person and each agent on the way. Clients are
kept per (origin, remote), so a callee's session never mixes two people. Nothing here raises to the model."""
import logging
import threading
from collections import OrderedDict

from localagent.connect.peer.tessera.client import TesseraClient
from localagent.connect.peer.tessera.endpoint import utc_now
from localagent.connect.peer.tessera.http import get_card as http_get_card
from localagent.connect.peer.tessera.http import post as http_post
from localagent.connect.peer.tessera.remotes import RemotesError, load
from localagent.protocol.tessera.canonical import canonical
from localagent.protocol.tessera.mandate import MAX_CHAIN

log = logging.getLogger(__name__)
MAX_CALLS = 3
CALL_SECONDS = 80          # 3 calls and the lead's own answer fit the relay's 300 s delivery window
ASK_RESERVE = 4096         # bytes kept for a reported ask (its mandate chain and question)
MIN_DELEGATE_BYTES = 16384  # below this, the reports wouldn't leave room for anything useful
QUESTION_CHARS = 1000
MAX_CLIENTS = 256          # open callee sessions kept across questions; the oldest is closed first


def call_bytes(budget: int) -> int:
    """What each callee's whole answer may take, so all reported calls and the lead's answer fit the budget."""
    return (budget - ASK_RESERVE) // (MAX_CALLS + 1) - ASK_RESERVE


class Delegator:
    def __init__(self, identity, protocol, agent_dir, *, post=http_post, get_card=http_get_card, clock=utc_now):
        self.identity, self.protocol, self.agent_dir, self.clock = identity, protocol, agent_dir, clock
        self._post = lambda address, raw, timeout=CALL_SECONDS, **kw: post(address, raw,
                                                                           timeout=min(timeout, CALL_SECONDS))
        self._get_card = lambda address, **kw: get_card(address, timeout=min(kw.get("timeout", 30), CALL_SECONDS))
        self._clients: OrderedDict = OrderedDict()  # (origin, remote name) -> (client, lock)
        self._lock = threading.Lock()

    def start(self, chain: list, origin: str, budget: int):
        """A Delegation for one question, or None when there is nothing to delegate within the limits."""
        if budget < MIN_DELEGATE_BYTES or len(chain) >= MAX_CHAIN:
            return None
        try:
            remotes = {n: r for n, r in load(self.agent_dir).items() if r.delegate}
        except RemotesError as e:
            log.warning("No delegation: %s", e)
            return None
        return Delegation(self, chain, origin, budget, remotes) if remotes else None

    def client(self, origin: str, remote):
        key = (origin, remote.name)
        with self._lock:
            entry = self._clients.get(key)
            if entry is None or entry[0].remote_id != remote.id or entry[0].address != remote.address:
                entry = (TesseraClient(self.identity, self.protocol, remote_id=remote.id, address=remote.address,
                                       purpose=f"Asked on behalf of {origin}"[:200], post=self._post,
                                       get_card=self._get_card, clock=self.clock), threading.Lock())
                self._clients[key] = entry
            self._clients.move_to_end(key)
            old = self._clients.popitem(last=False)[1] if len(self._clients) > MAX_CLIENTS else None
        if old is not None:
            try:
                old[0].close()
            except Exception:
                log.exception("Could not close a delegated session")
        return entry


class Delegation:
    def __init__(self, delegator: Delegator, chain: list, origin: str, budget: int, remotes: dict):
        self._delegator, self._chain, self._origin, self._remotes = delegator, chain, origin, remotes
        self._reply_bytes = call_bytes(budget)
        self._in_chain = {m["from"] for m in chain} | {delegator.identity.agent_id}
        self._calls: list[dict] = []

    @property
    def agents(self) -> list[tuple[str, str]]:
        return [(name, r.purpose) for name, r in self._remotes.items()]

    def _failed(self, name: str, agent: str, reason: str) -> str:
        self._calls.append({"agent": agent, "name": name, "ask": None, "reply": None, "error": reason})
        return f"({name} could not answer: {reason})"

    def ask(self, name: str, question: str) -> str:
        try:
            return self._ask(name, str(question)[:QUESTION_CHARS])
        except Exception:
            log.exception("A delegated call failed")
            return self._failed(name, "", "unavailable")

    def _ask(self, name: str, question: str) -> str:
        if len(self._calls) >= MAX_CALLS:
            return f"({name} could not answer: only {MAX_CALLS} calls per question)"
        remote = self._remotes.get(name)
        if remote is None:
            return f"({name} could not answer: unknown agent; use one of {', '.join(self._remotes)})"
        if remote.id in self._in_chain:
            return self._failed(name, remote.id, "already in the chain")
        client, lock = self._delegator.client(self._origin, remote)
        with lock:
            reply = client.ask(question, mandates=self._chain, reply_bytes=self._reply_bytes)
        if reply.kind in ("answer", "decline") and reply.ask is not None:
            item = {"agent": remote.id, "name": name, "ask": reply.ask, "reply": reply.reply, "error": ""}
            if len(canonical(item)) > ASK_RESERVE + self._reply_bytes:  # a long question with a long chain
                return self._failed(name, remote.id, "too_large")
            self._calls.append(item)
            return reply.text if reply.kind == "answer" else f"({name} declined to answer)"
        return self._failed(name, remote.id, reply.text or reply.kind)

    def report(self) -> list[dict]:
        return list(self._calls)
