"""Builds the system prompt from what the session allows. No tool-specific text lives here.

The wording is tuned against real small models: scripts/tool_eval.py measures it. Re-run that after any change."""
import json
from datetime import datetime, timedelta

BASE_PROMPT = "You are a helpful local AI assistant running on your owner's own computer."

TOOLS_INTRO = """You can use tools. They are real and they work: when a request needs one, use it instead of saying you can't.
To use one, write one short sentence for the user, then the tool tag on its own line.
The tag is JSON inside <tool>...</tool>, with "name", "action" and "args". Nothing comes after the tag.

Examples of complete replies:
{examples}

If no tool is needed, just answer normally with no tag.
Never pretend: don't say you searched, fetched or ran anything unless you wrote the tag and got its result.
Never invent facts, numbers or sources. If you don't know, use a tool, or say you don't know.
Arguments: use exactly the names listed. Dates and times are ISO 8601 (2026-10-12T18:00:00).
After a "read" action you will receive the result and can then answer with the real data.
If a result isn't enough to answer (e.g. it only lists pages), use another tool first, such as opening one of those pages. Up to 3 tools in a row.

Available tools:"""

_SAMPLE = {"str": "...", "int": 1, "number": 1, "bool": True, "list": [], "object": {},
           "iso-datetime": "2026-10-12T18:00:00"}


def _example(view) -> str:
    """One worked example per tool, built from the tool's own first action, so the prompt stays tool-agnostic.
    It must be concrete: given a placeholder, small models copy the placeholder."""
    action_name, action = next(iter(view.actions.items()))
    args = {p: _SAMPLE.get(t, "...") for p, t in action.params.items() if p not in action.optional}
    tag = json.dumps({"name": view.name, "action": action_name, "args": args}, ensure_ascii=False)
    return f'- If the user says "{action.description.rstrip(".")}, please.":\nSure, one moment.\n<tool>{tag}</tool>'


def _dates(now: datetime) -> str:
    # Small models get weekday arithmetic wrong; a lookup table fixes "tomorrow" and "on Friday".
    days = [now + timedelta(days=i) for i in range(1, 8)]
    return (f"Current date and time: {now:%Y-%m-%d %H:%M} ({now:%A}). Tomorrow is {days[0]:%A %Y-%m-%d}.\n"
            "Next days: " + ", ".join(f"{d:%A} {d:%Y-%m-%d}" for d in days))


def build_system_prompt(items: list, tools: list, now: datetime, recent: str = "") -> str:
    sections = [BASE_PROMPT, _dates(now)]
    tools = [view for view in tools if view.actions]
    if tools:
        lines = [TOOLS_INTRO.format(examples="\n".join(_example(view) for view in tools))]
        for view in tools:
            for action_name, action in view.actions.items():
                params = ", ".join(f'"{p}": <{t}{", optional" if p in action.optional else ""}>'
                                   for p, t in action.params.items())
                lines.append(f'- name "{view.name}", action "{action_name}" ({action.kind}): '
                             f"{action.description.rstrip('.')}. args: {{{params}}}")
        sections.append("\n".join(lines))
    if recent:
        sections.append("Results of your latest tool calls (use them for follow-up questions, "
                        "and name the pages/URLs they came from when asked):\n" + recent)
    knowledge = [i.content for i in items if i.kind == "knowledge"]
    if knowledge:
        sections.append("What you know:\n\n" + "\n\n".join(knowledge))
    work = [i.content for i in items if i.kind == "work" and i.content.get("status") == "active"]
    if work:
        sections.append("Current work:\n\n" + "\n\n".join(f"## {w['title']}\n{w['body']}".strip() for w in work))
    return "\n\n".join(sections)
