"""One conversation turn: prompt -> model -> tool calls (checked by the session) -> reply -> memory."""
import json
import logging
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Generator, Iterator

from localagent.agent.prompt import build_system_prompt
from localagent.agent.toolcalls import VisibleText, parse_tool_calls, strip_tool_tags
from localagent.agent.tools.base import ToolArgsError, validate_args
from localagent.protocol.session import WITHHELD, ScopeError, Session, UnknownToolError
from localagent.runtime.base import Backend

log = logging.getLogger(__name__)
MAX_ROUNDS = 2


@dataclass
class ToolOutcome:
    name: str
    action: str
    ok: bool
    result: object = None
    error: str = ""
    error_type: str = ""  # unknown | denied | bad_args | failed | withheld
    kind: str = ""

    def as_record(self) -> dict:
        return {"name": self.name, "action": self.action, "ok": self.ok, "error": self.error}


def _results_message(outcomes: list[ToolOutcome]) -> str:
    lines = [f"{o.name}.{o.action}: {json.dumps(o.result, ensure_ascii=False, default=str)}" for o in outcomes]
    return "Tool results (use them to answer my previous message):\n" + "\n".join(lines)


def _canonical(said: str, calls: list, outcomes: list[ToolOutcome]) -> str:
    """The model's turn as it should have been written: its text plus well-formed tags for the calls that
    ran. Failed calls are left out so the model never learns from its own mistakes in history."""
    tags = [f"<tool>{json.dumps({'name': c.name, 'action': c.action, 'args': c.args}, ensure_ascii=False)}</tool>"
            for c, o in zip(calls, outcomes) if o.ok]
    return "\n".join([said] + tags if said else tags)


class Agent:
    def __init__(self, backend: Backend, tools: dict, *, model_id: str, max_new_tokens: int = 256,
                 history_turns: int = 20, clock=datetime.now):
        self.backend = backend
        self.tools = tools
        self.model_id = model_id
        self.max_new_tokens = max_new_tokens
        self.history_turns = history_turns
        self._clock = clock
        self._lock = threading.Lock()  # one model: one turn at a time

    def run_tool(self, session: Session, name: str, action: str, args: dict) -> ToolOutcome:
        try:
            session.check_tool_call(name, action)
        except UnknownToolError as e:
            return ToolOutcome(name, action, False, error=str(e), error_type="unknown")
        except ScopeError as e:
            return ToolOutcome(name, action, False, error=str(e), error_type="denied")
        tool = self.tools.get(name)
        if tool is None:
            return ToolOutcome(name, action, False, error=f"Tool '{name}' is not loaded", error_type="unknown")
        spec = tool.actions[action]
        try:
            clean = validate_args(spec, args)
        except ToolArgsError as e:
            return ToolOutcome(name, action, False, error=str(e), error_type="bad_args", kind=spec.kind)
        try:
            result = tool.run(action, clean)
        except Exception as e:
            log.exception("Tool %s.%s failed", name, action)
            return ToolOutcome(name, action, False, error=str(e), error_type="failed", kind=spec.kind)
        result = session.filter_tool_result(name, result)
        if result is WITHHELD:
            return ToolOutcome(name, action, False, error=WITHHELD["withheld"], error_type="withheld",
                               kind=spec.kind)
        return ToolOutcome(name, action, True, result=result, kind=spec.kind)

    def _turn(self, session: Session, user_message: str) -> Generator[str, None, str]:
        """Yields visible text as it is generated; returns the reply that was recorded to memory."""
        with self._lock:
            self.backend.set_adapters(session.adapters(self.model_id))
            system = build_system_prompt(session.context(), session.tools(), self._clock())
            messages = ([{"role": "system", "content": system}]
                        + session.history(self.history_turns)
                        + [{"role": "user", "content": user_message}])
            # texts: what the user sees. transcript: what the model said and was told, replayed as history.
            texts, transcript, outcomes, shown, spoke = [], [], [], False, False
            for round_no in range(1, MAX_ROUNDS + 1):
                if round_no > 1 and shown:
                    yield "\n\n"
                visible, parts = VisibleText(), []
                for chunk in self.backend.generate_stream(messages, self.max_new_tokens):
                    parts.append(chunk)
                    out = visible.feed(chunk)
                    if out:
                        shown = True
                        yield out
                tail = visible.flush()
                if tail:
                    shown = True
                    yield tail
                raw = "".join(parts)
                said = strip_tool_tags(raw)
                spoke = spoke or bool(said)
                texts.append(said)
                calls, errors = parse_tool_calls(raw)
                for error in errors:
                    log.warning("Ignored tool call: %s", error)
                if round_no == MAX_ROUNDS:
                    if calls:
                        log.warning("Ignored %d tool call(s) in the final round", len(calls))
                    transcript.append({"role": "assistant", "content": said})
                    break
                round_outcomes = [self.run_tool(session, c.name, c.action, c.args) for c in calls]
                outcomes += round_outcomes
                transcript.append({"role": "assistant", "content": _canonical(said, calls, round_outcomes)})
                failed = [o for o in round_outcomes if not o.ok]
                if failed:
                    notice = "\n".join(f"(Couldn't run {o.name}.{o.action}: {o.error})" for o in failed)
                    yield ("\n\n" if shown else "") + notice
                    shown = True
                    texts.append(notice)
                reads = [o for o in round_outcomes if o.ok and o.kind == "read"]
                if not reads:
                    break
                results = {"role": "user", "content": _results_message(reads)}
                transcript.append(results)
                messages = messages + [{"role": "assistant", "content": raw}, results]
            if not spoke and any(o.ok and o.kind == "write" for o in outcomes):
                # The model only wrote tags; don't leave the user with a blank (or notice-only) reply.
                yield ("\n\n" if shown else "") + "Done."
                texts.append("Done.")
            reply = "\n\n".join(t for t in texts if t)
            session.record({"user": user_message, "assistant": reply, "transcript": transcript,
                            "tool_calls": [o.as_record() for o in outcomes]})
            return reply

    def respond_stream(self, session: Session, user_message: str) -> Iterator[str]:
        yield from self._turn(session, user_message)

    def respond(self, session: Session, user_message: str) -> str:
        turn = self._turn(session, user_message)
        while True:
            try:
                next(turn)
            except StopIteration as done:
                return done.value
