"""One conversation turn: prompt -> model -> tool calls (checked by the session) -> reply -> memory."""
import json
import logging
import re
import threading
import weakref
from dataclasses import dataclass
from datetime import datetime
from typing import Generator, Iterator

from localagent.agent.excerpt import excerpt
from localagent.agent.prompt import build_system_prompt
from localagent.agent.toolcalls import ToolCall, VisibleText, parse_tool_calls, strip_tool_tags, tool_being_called
from localagent.agent.tools.base import ToolArgsError, validate_args
from localagent.protocol.prompts import DELEGATION_PROMPT, PEER_SYSTEM_PROMPT, REFUSAL
from localagent.protocol.session import WITHHELD, ScopeError, Session, UnknownToolError
from localagent.runtime.base import Backend

log = logging.getLogger(__name__)
MAX_ROUNDS = 4  # up to 3 tool calls in a row (e.g. search, then open a page), then the answer
RECENT_TURNS = 3       # how many more messages the latest tool results stay visible, for follow-up questions
RECENT_CHARS = 1500  # this sits in the system prompt, which the prompt budget never trims
RESULT_CHARS = 2500  # longer text in a tool result (a web page) is cut to the parts that match the question
FOLLOW_TRIES = 3     # links tried, in order, when a tool's `follow:` opens the first one that works
LINK = re.compile(r"""https?://[^\s"'<>()\[\]{}\\]+""")  # stops at a backslash: results are JSON-encoded
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


def _shorten(outcome: ToolOutcome, question: str) -> ToolOutcome:
    """Long texts in a result keep only what matches the question, instead of just their start."""
    if outcome.ok and isinstance(outcome.result, dict):
        outcome.result = {k: excerpt(v, question, RESULT_CHARS) if isinstance(v, str) else v
                          for k, v in outcome.result.items()}
    return outcome


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
    oldest history turns first, then shortens this reply's messages, newest first (usually big tool results)."""
    def size(msgs):
        return sum(len(m["content"]) for m in msgs)

    history, turn = list(history), list(turn)
    while history and size([system, *history, *turn]) > budget:
        del history[:2]  # one user + assistant pair
    for i in reversed(range(len(turn))):
        over = size([system, *history, *turn]) - budget
        if over <= 0:
            break
        content = turn[i]["content"]
        keep = max(200, len(content) - over - len(CUT_NOTE))
        if keep < len(content):
            turn[i] = {**turn[i], "content": content[:keep] + CUT_NOTE}
    return [system, *history, *turn]


def _normalized(text: str) -> str:
    return " ".join(text.lower().replace("\u2019", "'").split()).strip(" .!\"'")


def is_refusal(reply: str) -> bool:
    """The model's standard refusal, however it's punctuated. Anything said after it is dropped: a refusal must
    look the same whether the answer is unknown or not allowed."""
    return bool(reply.strip()) and _normalized(reply).startswith(_normalized(REFUSAL))


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

    def answer_peer(self, session: Session, question: str, history: list[dict], delegation=None) -> str:
        """One Tessera `ask`: the connection's adapter, the open peer prompt, this Tessera session's earlier
        questions. Nothing of the owner's: the model here is treated as controlled by the peer. Its only possible
        tool is `agents.ask`, and only when the owner switched `delegate:` on (the endpoint passes a delegation)."""
        if session.principal == "owner":
            raise ValueError("answer_peer is for peer sessions")
        with self._lock:
            adapters = session.adapters(self.model_id)
            if not adapters:  # no connection adapter: the bare base model must never answer a peer
                session.record({"user": question, "assistant": REFUSAL, "tool_calls": []})
                return REFUSAL
            if delegation is None:
                self.backend.set_adapters(adapters)
                system = {"role": "system", "content": PEER_SYSTEM_PROMPT}
                messages = _fit(system, history, [{"role": "user", "content": question}], self.max_prompt_chars)
                reply = self.backend.generate(messages, self.max_new_tokens).strip()
                session.record({"user": question, "assistant": reply, "tool_calls": []})
                return reply
        agents = "\n".join(f"- {name}: {purpose}" for name, purpose in delegation.agents)
        system = {"role": "system", "content": PEER_SYSTEM_PROMPT + "\n\n" + DELEGATION_PROMPT.format(agents=agents)}
        this_turn, records, reply = [{"role": "user", "content": question}], [], ""
        for round_no in range(1, MAX_ROUNDS + 1):
            with self._lock:  # held only while generating: a call to another agent can take minutes
                self.backend.set_adapters(adapters)
                messages = _fit(system, history, this_turn, self.max_prompt_chars)
                raw = self.backend.generate(messages, self.max_new_tokens).strip()
            reply = strip_tool_tags(raw)
            calls, errors = parse_tool_calls(raw)
            for error in errors:
                log.warning("Ignored tool call from a peer turn: %s", error)
            asks = [c for c in calls if (c.name, c.action) == ("agents", "ask")]
            for c in calls:
                if c not in asks:
                    log.warning("Ignored %s.%s in a peer turn: only agents.ask exists there", c.name, c.action)
            if not asks or round_no == MAX_ROUNDS:
                break
            answers = []
            for c in asks:
                name, text = str(c.args.get("agent", "")), c.args.get("question")
                if not isinstance(text, str) or not text.strip():
                    result = f"({name} could not answer: the question is missing)"
                else:
                    result = delegation.ask(name, text)
                failed = result.startswith(f"({name} could not answer")
                error = result[len(f"({name} could not answer: "):-1] if failed else ""
                records.append({"name": "agents", "action": "ask", "ok": not failed, "error": error})
                answers.append(f"{name} says:\n{result}")
            ran = [ToolOutcome("agents", "ask", True)] * len(asks)
            results = ("Answers from the agents you asked (use them to answer my previous message):\n\n"
                       + "\n\n".join(answers))
            this_turn = this_turn + [{"role": "assistant", "content": _canonical(reply, asks, ran)},
                                     {"role": "user", "content": results}]
        session.record({"user": question, "assistant": reply, "tool_calls": records})
        return reply

    def _follow(self, session: Session, outcomes: list[ToolOutcome]) -> tuple[list[ToolCall], list[ToolOutcome]]:
        """For tools with `follow:` (e.g. search -> fetch_content): opens the first link in the result that works,
        so the model gets the page itself, not just a list of links it would have to decide to open."""
        calls, opened = [], []
        for o in outcomes:
            tool = self.tools.get(o.name)
            then = getattr(tool, "follow", {}).get(o.action) if o.ok else None
            if not then:
                continue
            spec = tool.actions[then]
            param = next(p for p in spec.params if p not in spec.optional)
            links = dict.fromkeys(m.rstrip(".,;:") for m in LINK.findall(json.dumps(o.result, ensure_ascii=False)))
            for link in list(links)[:FOLLOW_TRIES]:
                call = ToolCall(o.name, then, {param: link})
                outcome = self.run_tool(session, call.name, call.action, call.args)
                if outcome.ok:
                    calls.append(call)
                    opened.append(outcome)
                    break
                log.info("Follow-up %s.%s on %s failed: %s", o.name, then, link, outcome.error)
        return calls, opened

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
                approved = [_shorten(self.run_tool(session, c.name, c.action, c.args), user_message)
                            for c in pending]
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
                visible, parts, announced = VisibleText(), [], False
                messages = _fit(system_message, history, this_turn, self.max_prompt_chars)
                for chunk in self.backend.generate_stream(messages, self.max_new_tokens):
                    parts.append(chunk)
                    if hold_back and not announced:
                        name = tool_being_called("".join(parts))
                        if name:  # say so right away: the tool and the answer after it take a while
                            announced = True
                            yield notice([f"(Using the {name} tool... this can take a moment.)"])
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
                    if announced and not calls:
                        yield notice([f"(The {name} call was cut off or malformed, so nothing ran.)"])
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
                round_outcomes = [_shorten(self.run_tool(session, c.name, c.action, c.args), user_message)
                                  for c in calls]
                outcomes += round_outcomes
                transcript.append({"role": "assistant", "content": _canonical(said, calls, round_outcomes)})
                yield from (notice(lines) for lines in _report(calls, round_outcomes) if lines)
                followed, opened = self._follow(session, round_outcomes)
                opened = [_shorten(o, user_message) for o in opened]
                outcomes += opened
                yield from (notice(lines) for lines in _report(followed, opened) if lines)
                if held:  # tools marked `confirm: true` wait for the owner's explicit yes, next message
                    self._pending[session] = held
                    yield notice([f"(Waiting for your OK to run {c.name}.{c.action} "
                                  f"{json.dumps(c.args, ensure_ascii=False)}. Reply yes to run it.)" for c in held])
                # opened pages first: if the prompt budget cuts, it cuts the link list, not the page
                reads = [o for o in opened + round_outcomes if o.ok and o.kind == "read"]
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
