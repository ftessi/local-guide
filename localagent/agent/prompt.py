"""Builds the system prompt from what the session allows. No tool-specific text lives here.

The wording is tuned against real small models: scripts/tool_eval.py measures it. Re-run that after any change."""
import json
from datetime import datetime, timedelta

BASE_PROMPT = "You are a helpful local AI assistant running on your owner's own computer."

TOOLS_INTRO = """You can use tools. To use one, write one short sentence for the user, then the tool tag on its own line.
The tag is JSON inside <tool>...</tool>, with "name", "action" and "args". Nothing comes after the tag.

Example: if the user says "{request}", your whole reply is these two lines:
Sure, one moment.
{tag}

If no tool is needed, just answer normally with no tag.
Arguments: use exactly the names listed. Dates and times are ISO 8601 (2026-10-12T18:00:00).
After a "read" action you will receive the result and can then answer with the real data.

Available tools:"""

_SAMPLE = {"str": "...", "int": 1, "iso-datetime": "2026-10-12T18:00:00"}


def _example(view) -> dict:
    """A worked example built from the agent's own tool, so the prompt stays tool-agnostic.
    It must be concrete: given a placeholder, small models copy the placeholder."""
    action_name, action = next(iter(view.actions.items()))
    args = {p: _SAMPLE.get(t, "...") for p, t in action.params.items()}
    return {"request": f"{action.description}, please.",
            "tag": f"<tool>{json.dumps({'name': view.name, 'action': action_name, 'args': args})}</tool>"}


def _dates(now: datetime) -> str:
    # Small models get weekday arithmetic wrong; a lookup table fixes "tomorrow" and "on Friday".
    days = [now + timedelta(days=i) for i in range(1, 8)]
    return (f"Current date and time: {now:%Y-%m-%d %H:%M} ({now:%A}). Tomorrow is {days[0]:%A %Y-%m-%d}.\n"
            "Next days: " + ", ".join(f"{d:%A} {d:%Y-%m-%d}" for d in days))


def build_system_prompt(items: list, tools: list, now: datetime) -> str:
    sections = [BASE_PROMPT, _dates(now)]
    if tools:
        lines = [TOOLS_INTRO.format(**_example(tools[0]))]
        for view in tools:
            for action_name, action in view.actions.items():
                params = ", ".join(f'"{p}": <{t}>' for p, t in action.params.items())
                lines.append(f'- name "{view.name}", action "{action_name}" ({action.kind}): '
                             f"{action.description}. args: {{{params}}}")
        sections.append("\n".join(lines))
    knowledge = [i.content for i in items if i.kind == "knowledge"]
    if knowledge:
        sections.append("What you know:\n\n" + "\n\n".join(knowledge))
    work = [i.content for i in items if i.kind == "work" and i.content.get("status") == "active"]
    if work:
        sections.append("Current work:\n\n" + "\n\n".join(f"## {w['title']}\n{w['body']}".strip() for w in work))
    return "\n\n".join(sections)
