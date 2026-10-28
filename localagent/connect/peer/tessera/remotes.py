"""The agents an owner connected this agent to (tessera/remotes.yaml): what `ask`, `/talk` and delegation call."""
from dataclasses import dataclass
from pathlib import Path

import yaml

from localagent.protocol.identity import AGENT_ID_RE

PURPOSE_MAX = 200


class RemotesError(ValueError):
    """remotes.yaml is unreadable, or an entry is wrong. The message says what to fix."""


@dataclass(frozen=True)
class Remote:
    name: str
    id: str
    address: str
    purpose: str
    delegate: bool = True  # a delegating agent may call it; false keeps it for the owner


def path(agent_dir) -> Path:
    return Path(agent_dir) / "tessera" / "remotes.yaml"


def read(agent_dir) -> dict:
    """The raw mapping, for `connect` to add to."""
    file = path(agent_dir)
    if not file.is_file():
        return {}
    try:
        raw = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError, ValueError) as e:
        raise RemotesError(f"{file} is not readable: {e}") from e
    if not isinstance(raw, dict):
        raise RemotesError(f"{file} must be a mapping of names to {{address, id, purpose}}")
    return raw


def _entry(agent_dir, name: str, entry) -> Remote:
    file = path(agent_dir)
    if (not isinstance(entry, dict) or not isinstance(entry.get("address"), str)
            or not isinstance(entry.get("id"), str) or not AGENT_ID_RE.fullmatch(entry["id"])):
        raise RemotesError(f"{file}: '{name}' needs string fields address and id "
                           "(id: 43 characters, from their `python -m localagent id`)")
    purpose = entry.get("purpose", "")
    if not isinstance(purpose, str) or len(purpose) > PURPOSE_MAX:
        raise RemotesError(f"{file}: '{name}' has a bad purpose (text, at most {PURPOSE_MAX} characters)")
    delegate = entry.get("delegate", True)
    if not isinstance(delegate, bool):
        raise RemotesError(f"{file}: '{name}': `delegate` must be true or false")
    return Remote(str(name), entry["id"], entry["address"], purpose, delegate)


def get(agent_dir, name: str) -> Remote:
    entry = read(agent_dir).get(name)
    if entry is None:
        raise RemotesError(f"Unknown remote '{name}'. Add it first: python -m localagent connect <address> <id> "
                           f"--name {name} --purpose \"…\"")
    return _entry(agent_dir, name, entry)


def load(agent_dir) -> dict[str, Remote]:
    return {str(name): _entry(agent_dir, name, entry) for name, entry in read(agent_dir).items()}
