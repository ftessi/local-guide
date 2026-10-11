"""What a tool is: named actions with typed arguments, its own storage, an optional background job."""
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

Notify = Callable[[str, str], None]
PARAM_TYPES = ("str", "int", "iso-datetime")


@dataclass(frozen=True)
class Action:
    description: str
    params: dict = field(default_factory=dict)  # argument name -> "str" | "int" | "iso-datetime"
    kind: str = "read"                          # "read" results go back to the model; "write" changes data


class ToolArgsError(ValueError):
    pass


def _coerce(name: str, typ: str, value):
    if typ == "str":
        if not isinstance(value, str):
            raise ToolArgsError(f"'{name}' must be text")
        return value.strip()
    if typ == "int":
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().lstrip("-").isdigit():
            return int(value)
        raise ToolArgsError(f"'{name}' must be an integer")
    if typ == "iso-datetime":
        try:
            dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        except ValueError:
            raise ToolArgsError(f"'{name}' must be an ISO datetime like 2026-10-12T18:00:00") from None
        if dt.tzinfo is not None:
            dt = dt.astimezone().replace(tzinfo=None)  # store local, naive time
        return dt.isoformat(timespec="seconds")
    raise ToolArgsError(f"Unsupported parameter type '{typ}' for '{name}'")


def validate_args(action: Action, args) -> dict:
    if not isinstance(args, dict):
        raise ToolArgsError("args must be an object")
    unknown = set(args) - set(action.params)
    if unknown:
        raise ToolArgsError(f"Unknown argument(s): {', '.join(sorted(unknown))}")
    clean = {}
    for name, typ in action.params.items():
        if args.get(name) in (None, ""):
            raise ToolArgsError(f"Missing argument '{name}'")
        clean[name] = _coerce(name, typ, args[name])
    return clean


class Tool:
    name: str = ""
    compartment: str = "private"
    actions: dict = {}

    def setup(self, data_dir: Path, notify: Notify | None) -> None:
        """Called once with this tool's own data folder and a way to notify the owner."""

    def run(self, action: str, args: dict) -> dict:
        raise NotImplementedError

    def background(self) -> None:
        """Optional: called about once a minute by the owner server."""
