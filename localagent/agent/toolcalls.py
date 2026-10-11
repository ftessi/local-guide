"""The model-agnostic tool-call format: <tool>{"name":..,"action":..,"args":{..}}</tool> after the reply.

Parsing is lenient on purpose: small local models drift from the format (see tests/test_toolcalls.py)."""
import json
import re
from dataclasses import dataclass, field

OPENERS = ("<tool>", "<tool_call>")  # <tool_call> is the native format of Qwen/Hermes-style models
_OPEN = re.compile(r"<tool(?:_call)?>")
_CLOSE = re.compile(r"\s*</tool(?:_call)?>")
_DECODER = json.JSONDecoder()


@dataclass(frozen=True)
class ToolCall:
    name: str
    action: str
    args: dict = field(default_factory=dict)


def _to_call(data) -> ToolCall | None:
    """Accepts the documented shape plus what small models write instead:
    "name":"calendar.create" (with any or no action) and "arguments" instead of "args"."""
    if not isinstance(data, dict) or not isinstance(data.get("name"), str):
        return None
    name, _, dotted = data["name"].partition(".")
    action = dotted or data.get("action")
    args = data.get("args", data.get("arguments"))
    if args is None:
        args = {}
    if not name or not isinstance(action, str) or not action or not isinstance(args, dict):
        return None
    return ToolCall(name, action, args)


def parse_tool_calls(text: str) -> tuple[list[ToolCall], list[str]]:
    """Reads one JSON object after each opening tag. The closing tag is optional: models often forget it."""
    calls, errors = [], []
    pos = 0
    while (match := _OPEN.search(text, pos)) is not None:
        body_start = match.end()
        while body_start < len(text) and text[body_start].isspace():
            body_start += 1
        try:
            data, end = _DECODER.raw_decode(text, body_start)
        except json.JSONDecodeError:
            cut_off = _CLOSE.search(text, body_start) is None
            errors.append("unterminated <tool> tag (reply cut off?)" if cut_off
                          else f"invalid JSON in tool tag: {text[body_start:body_start + 80]}")
            pos = body_start
            continue
        call = _to_call(data)
        if call is None:
            errors.append(f"tool tag needs string name/action and object args: {text[body_start:end][:80]}")
        else:
            calls.append(call)
        close = _CLOSE.match(text, end)
        pos = close.end() if close else end
    return calls, errors


def strip_tool_tags(text: str) -> str:
    """Everything from the first tag on is hidden, the same as VisibleText does while streaming."""
    match = _OPEN.search(text)
    return (text[:match.start()] if match else text).strip()


class VisibleText:
    """Streaming filter: passes text through until the first tool tag, then hides the rest."""

    def __init__(self):
        self._buf = ""
        self._hidden = False

    def feed(self, chunk: str) -> str:
        if self._hidden:
            return ""
        self._buf += chunk
        match = _OPEN.search(self._buf)
        if match:
            out, self._buf, self._hidden = self._buf[:match.start()], "", True
            return out
        # Hold back a trailing piece that could be the start of a tag
        longest = max(len(o) for o in OPENERS) - 1
        keep = next((k for k in range(min(longest, len(self._buf)), 0, -1)
                     if any(o.startswith(self._buf[-k:]) for o in OPENERS)), 0)
        out = self._buf[:len(self._buf) - keep]
        self._buf = self._buf[len(self._buf) - keep:]
        return out

    def flush(self) -> str:
        out = "" if self._hidden else self._buf
        self._buf = ""
        return out
