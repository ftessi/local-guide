"""Tessera relay core: carries bytes between askers and agents that connect out to the relay. Transport-free: the
HTTP routes (localagent/relay/http.py) are one front end to it; a browser front end could be another.
The relay never signs, answers or changes what it carries; it only checks who may poll for an agent."""
import secrets
import threading
import time
from collections import deque
from dataclasses import dataclass, field

from localagent.protocol.identity import verify
from localagent.protocol.tessera.relay import MAX_WAITING, register_message  # noqa: F401 (part of this module's API)

CHALLENGE_SECONDS = 60
DROP_SECONDS = 60  # an agent that hasn't polled for this long leaves the relay
NAME_CHARS, DESCRIPTION_CHARS = 60, 200


class RelayError(Exception):
    """Everything the relay core raises on purpose."""


class Offline(RelayError):
    """The agent isn't connected, or left while the request waited."""


class Busy(RelayError):
    """Too many requests waiting (for this agent, or registrations in progress)."""


class TimedOut(RelayError):
    """The agent didn't answer in time."""


class BadToken(RelayError):
    """Unknown agent or token, or a registration that was replaced."""


class Refused(RelayError):
    """A registration with a bad signature or challenge."""


class Full(RelayError):
    """The relay already has its maximum number of agents."""


def _clean(text, limit: int) -> str:
    return "".join(c for c in str(text) if c.isprintable())[:limit]


@dataclass(eq=False)
class Request:
    id: str
    kind: str
    payload: bytes
    done: threading.Event = field(default_factory=threading.Event)
    reply: bytes = b""
    failed: bool = False


@dataclass(eq=False)
class _Agent:
    token: str
    listed: bool
    name: str
    description: str
    last_seen: float
    queue: deque = field(default_factory=deque)  # not handed out yet
    open: dict = field(default_factory=dict)  # request id -> Request, every unfinished one
    polls: int = 0


class Relay:
    def __init__(self, *, max_agents: int = 100, max_challenges: int = 10_000, clock=time.monotonic):
        self.max_agents, self.max_challenges, self.clock = max_agents, max_challenges, clock
        self._agents: dict[str, _Agent] = {}
        self._challenges: dict[str, float] = {}  # nonce -> expiry
        self._cond = threading.Condition()

    def challenge(self) -> str:
        with self._cond:
            self._sweep()
            if len(self._challenges) >= self.max_challenges:
                raise Busy("too many registrations in progress")
            nonce = secrets.token_urlsafe(24)
            self._challenges[nonce] = self.clock() + CHALLENGE_SECONDS
            return nonce

    def register(self, agent_id: str, nonce: str, signature: str, *, listed: bool = False, name: str = "",
                 description: str = "") -> str:
        with self._cond:
            self._sweep()
            known = isinstance(nonce, str) and self._challenges.pop(nonce, None) is not None  # used up either way
            if not known or not verify(agent_id, register_message(nonce, agent_id), signature):
                raise Refused("the signature or the challenge isn't valid")
            old = self._agents.pop(agent_id, None)
            if old is not None:
                self._fail(old)
            if len(self._agents) >= self.max_agents:
                raise Full(f"the relay already has {self.max_agents} agents")
            token = secrets.token_urlsafe(24)
            self._agents[agent_id] = _Agent(token, bool(listed), _clean(name, NAME_CHARS),
                                            _clean(description, DESCRIPTION_CHARS), self.clock())
            self._cond.notify_all()
            return token

    def deliver(self, agent_id: str, kind: str, payload: bytes, timeout: float) -> bytes:
        with self._cond:
            self._sweep()
            agent = self._agents.get(agent_id)
            if agent is None:
                raise Offline("this agent isn't connected to the relay")
            if len(agent.open) >= MAX_WAITING:
                raise Busy("too many requests waiting for this agent")
            request = Request(secrets.token_hex(8), kind, payload)
            agent.queue.append(request)
            agent.open[request.id] = request
            self._cond.notify_all()
        if not request.done.wait(timeout):
            with self._cond:
                agent.open.pop(request.id, None)
                if request in agent.queue:
                    agent.queue.remove(request)
                if not request.done.is_set():  # reply() sets it under the same lock, so this is final
                    raise TimedOut("the agent didn't answer in time")
        if request.failed:
            raise Offline("the agent left the relay")
        return request.reply

    def next_request(self, agent_id: str, token: str, wait: float = 25.0) -> Request | None:
        with self._cond:
            agent = self._authorized(agent_id, token)
            agent.polls += 1
            try:
                deadline = time.monotonic() + wait
                while not agent.queue and self._agents.get(agent_id) is agent:
                    left = deadline - time.monotonic()
                    if left <= 0:
                        break
                    self._cond.wait(left)
                if self._agents.get(agent_id) is not agent:
                    raise BadToken("this registration was replaced")
                return agent.queue.popleft() if agent.queue else None
            finally:
                agent.polls -= 1
                agent.last_seen = self.clock()

    def reply(self, agent_id: str, token: str, request_id: str, payload: bytes) -> None:
        with self._cond:
            agent = self._authorized(agent_id, token)
            request = agent.open.pop(request_id, None)
            if request is not None:  # a reply nobody waits for any more is dropped
                request.reply = payload
                request.done.set()

    def pending(self, agent_id: str) -> int:
        with self._cond:
            agent = self._agents.get(agent_id)
            return len(agent.open) if agent else 0

    def directory(self, base: str) -> list[dict]:
        with self._cond:
            self._sweep()
            base = base.rstrip("/")
            return [{"id": agent_id, "name": a.name, "description": a.description, "address": f"{base}/a/{agent_id}"}
                    for agent_id, a in self._agents.items() if a.listed]

    def sweep(self) -> None:
        with self._cond:
            self._sweep()

    def _sweep(self) -> None:
        now = self.clock()
        self._challenges = {n: expiry for n, expiry in self._challenges.items() if expiry > now}
        for agent_id, agent in list(self._agents.items()):
            if not agent.polls and now - agent.last_seen > DROP_SECONDS:
                del self._agents[agent_id]
                self._fail(agent)

    def _fail(self, agent: _Agent) -> None:
        for request in agent.open.values():
            request.failed = True
            request.done.set()
        agent.open.clear()
        agent.queue.clear()
        self._cond.notify_all()

    def _authorized(self, agent_id: str, token) -> _Agent:
        agent = self._agents.get(agent_id)
        if (agent is None or not isinstance(token, str) or not token.isascii()
                or not secrets.compare_digest(agent.token, token)):
            raise BadToken("unknown agent or token")
        return agent
