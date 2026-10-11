"""One conversation turn: prompt -> model -> tool calls (checked by the session) -> reply -> memory."""
import json
import logging
import threading
import weakref
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
RECENT_TURNS = 3       # how many more messages the latest tool results stay visible, for follow-up questions
RECENT_CHARS = 1500  # this sits in the system prompt, which the prompt budget never trims
YES = {"yes", "y", "ok", "okay", "allow", "si", "sí"}  # approves tools marked confirm: true


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


def _results_message(outcomes: list[ToolOutcome], include_failed: bool = False) -> str:
    lines = [f"{o.name}.{o.action}: {json.dumps(o.result, ensure_ascii=False, default=str)}" if o.ok
             else f"{o.name}.{o.action}: failed: {o.error}" for o in outcomes if o.ok or include_failed]
    return "Tool results (use them to answer my previous message):\n" + "\n".join(lines)


def _canonical(said: str, calls: list, outcomes: list[ToolOutcome]) -> str:
    """The model's turn as it should have been written: its text plus well-formed tags for the calls that
    ran. Failed calls are left out so the model never learns from its own mistakes in history."""
    tags = [f"<tool>{json.dumps({'name': c.name, 'action': c.action, 'args': c.args}, ensure_ascii=False)}</tool>"
            for c, o in zip(calls, outcomes) if o.ok]
    return "\n".join([said] + tags if said else tags)


def _used(call) -> str:
    """Shown under every tool call that really ran, so a model claiming it did something it didn't is visible."""
    args = ", ".join(f"{k}={json.dumps(v, ensure_ascii=False)[:60]}" for k, v in call.args.items())
    return f"(used {call.name}.{call.action}{': ' + args if args else ''})"


def _report(calls: list, outcomes: list[ToolOutcome]) -> list[list[str]]:
    """Notice lines for calls that ran: first what was used, then what failed."""
    used = [_used(c) for c, o in zip(calls, outcomes) if o.ok]
    failed = [f"(Couldn't run {o.name}.{o.action}: {o.error})" for o in outcomes if not o.ok]
    return [used, failed]


CUT_NOTE = "\n…[cut to fit the prompt budget]"


def _fit(system: dict, history: list[dict], turn: list[dict], budget: int) -> list[dict]:
    """Keeps the prompt within `budget` characters (long prompts run small GPUs out of memory): drops the
    oldest history turns first, then shortens the newest message (usually a big tool result)."""
    def size(msgs):
        return sum(len(m["content"]) for m in msgs)

    history = list(history)
    while history and size([system, *history, *turn]) > budget:
        del history[:2]  # one user + assistant pair
    over = size([system, *history, *turn]) - budget
    if over > 0:
        last = turn[-1]
        keep = max(200, len(last["content"]) - over - len(CUT_NOTE))
        turn = [*turn[:-1], {**last, "content": last["content"][:keep] + CUT_NOTE}]
    return [system, *history, *turn]


class Agent:
    def __init__(self, backend: Backend, tools: dict, *, model_id: str, max_new_tokens: int = 256,
                 history_turns: int = 20, clock=datetime.now, max_prompt_chars: int = 8000):
        self.backend = backend
        self.tools = tools
        self.model_id = model_id
        self.max_new_tokens = max_new_tokens
        self.max_prompt_chars = max_prompt_chars
        self.history_turns = history_turns
        self._clock = clock
        self._lock = threading.Lock()  # one model: one turn at a time
        self._pending = weakref.WeakKeyDictionary()  # session -> tool calls waiting for the owner's yes
        self._recent = weakref.WeakKeyDictionary()   # session -> [latest tool results, turns left]

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
            # texts: what the user sees. transcript: what the model said and was told, replayed as history.
            texts, transcript, outcomes, read_outcomes = [], [], [], []
            shown = False

            def notice(lines: list[str]) -> str:
                """A line from the agent itself, never from the model: what ran, what failed, what waits."""
                nonlocal shown
                text = "\n".join(lines)
                out = ("\n\n" if shown else "") + text
                shown = True
                texts.append(text)
                return out

            to_model = user_message
            pending = self._pending.pop(session, None)
            if pending and user_message.strip().lower().rstrip(".!") in YES:
                approved = [self.run_tool(session, c.name, c.action, c.args) for c in pending]
                outcomes += approved
                read_outcomes += [o for o in approved if o.ok]
                to_model = "I allowed it. " + _results_message(approved, include_failed=True)
                yield from (notice(lines) for lines in _report(pending, approved) if lines)
            recent = self._recent.get(session)
            views = session.tools()
            system = build_system_prompt(session.context(), views, self._clock(),
                                         recent=recent[0] if recent else "")
            system_message = {"role": "system", "content": system}
            history = session.history(self.history_turns)
            this_turn = [{"role": "user", "content": to_model}]
            for round_no in range(1, MAX_ROUNDS + 1):
                # A reply that may call a tool is held back until it's finished: small models write guesses
                # before the tool tag ("based on my knowledge, CDU 48%…"). If it calls a tool, that text is
                # dropped and only the answer written from the real results is shown.
                hold_back = round_no < MAX_ROUNDS and bool(views)
                if round_no > 1 and shown:
                    yield "\n\n"
                visible, parts = VisibleText(), []
                messages = _fit(system_message, history, this_turn, self.max_prompt_chars)
                for chunk in self.backend.generate_stream(messages, self.max_new_tokens):
                    parts.append(chunk)
                    out = "" if hold_back else visible.feed(chunk)
                    if out:
                        shown = True
                        yield out
                tail = "" if hold_back else visible.flush()
                if tail:
                    shown = True
                    yield tail
                raw = "".join(parts)
                said = strip_tool_tags(raw)
                calls, errors = parse_tool_calls(raw)
                for error in errors:
                    log.warning("Ignored tool call: %s", error)
                if hold_back:
                    if calls:
                        said = ""
                    elif said:
                        yield ("\n\n" if shown else "") + said
                        shown = True
                texts.append(said)
                if round_no == MAX_ROUNDS:
                    if calls:
                        log.warning("Ignored %d tool call(s) in the final round", len(calls))
                    transcript.append({"role": "assistant", "content": said})
                    break
                held = [c for c in calls if getattr(self.tools.get(c.name), "confirm", False)]
                calls = [c for c in calls if c not in held]
                round_outcomes = [self.run_tool(session, c.name, c.action, c.args) for c in calls]
                outcomes += round_outcomes
                transcript.append({"role": "assistant", "content": _canonical(said, calls, round_outcomes)})
                yield from (notice(lines) for lines in _report(calls, round_outcomes) if lines)
                if held:  # tools marked `confirm: true` wait for the owner's explicit yes, next message
                    self._pending[session] = held
                    yield notice([f"(Waiting for your OK to run {c.name}.{c.action} "
                                  f"{json.dumps(c.args, ensure_ascii=False)}. Reply yes to run it.)" for c in held])
                reads = [o for o in round_outcomes if o.ok and o.kind == "read"]
                read_outcomes += reads
                if not reads:
                    break
                results = {"role": "user", "content": _results_message(reads)}
                transcript.append(results)
                # The model sees its call, not the guesses it wrote around it, next to the real results.
                this_turn = this_turn + [{"role": "assistant", "content": _canonical(said, calls, round_outcomes)},
                                         results]
            self._remember_results(session, read_outcomes)
            reply = "\n\n".join(t for t in texts if t)
            session.record({"user": user_message, "assistant": reply, "transcript": transcript,
                            "tool_calls": [o.as_record() for o in outcomes]})
            return reply

    def _remember_results(self, session: Session, read_outcomes: list[ToolOutcome]) -> None:
        """History never replays tool results (models learn to fake them), so the latest ones are kept in the
        system prompt for a few messages instead: enough for "which page was that?" follow-ups."""
        if read_outcomes:
            text = _results_message(read_outcomes).split("\n", 1)[1]
            self._recent[session] = [text[:RECENT_CHARS], RECENT_TURNS]
        elif session in self._recent:
            self._recent[session][1] -= 1
            if self._recent[session][1] <= 0:
                del self._recent[session]

    def respond_stream(self, session: Session, user_message: str) -> Iterator[str]:
        yield from self._turn(session, user_message)

    def respond(self, session: Session, user_message: str) -> str:
        turn = self._turn(session, user_message)
        while True:
            try:
                next(turn)
            except StopIteration as done:
                return done.value
