"""Scope strings: the single vocabulary for what a session may see or do."""
import re

ALL = "all"
INTERNAL_COMPARTMENT = "private"  # the owner's own compartment; every other one belongs to a connection
COMPARTMENT_KINDS = ("knowledge", "memory", "work", "adapter")
_NAME = re.compile(r"^[a-z][a-z0-9_-]*$")
_HELP = "expected all, knowledge:<c>, memory:<c>, work:<c>, adapter:<c>, tool:<name> or tool:<name>:<action>"


class InvalidScope(ValueError):
    pass


def _check(scope) -> None:
    if not isinstance(scope, str):
        raise InvalidScope(f"Invalid scope {scope!r}: {_HELP}")
    if scope == ALL:
        return
    kind, _, rest = scope.partition(":")
    if kind == "tool":
        parts = rest.split(":")
        if len(parts) in (1, 2) and all(_NAME.match(p) for p in parts):
            return
    elif kind in COMPARTMENT_KINDS and rest:
        if kind == "memory" and rest.startswith("peer:") and len(rest) > len("peer:"):
            return
        if _NAME.match(rest):
            return
    raise InvalidScope(f"Invalid scope '{scope}': {_HELP}")


class Scope:
    def __init__(self, scopes=()):
        if isinstance(scopes, str):
            raise InvalidScope(f"Scopes must be a list, got the string '{scopes}'")
        scopes = list(scopes)
        for s in scopes:
            _check(s)
        self.items = frozenset(scopes)

    @property
    def is_all(self) -> bool:
        return ALL in self.items

    def allows(self, kind: str, compartment: str) -> bool:
        return self.is_all or f"{kind}:{compartment}" in self.items

    def allows_tool(self, name: str, action: str) -> bool:
        return self.is_all or f"tool:{name}" in self.items or f"tool:{name}:{action}" in self.items

    def __repr__(self) -> str:
        return f"Scope({sorted(self.items)})"
