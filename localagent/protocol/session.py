"""A session: who is talking, what they may see, and the only door to the agent's data."""
import json
from dataclasses import dataclass
from pathlib import Path

from localagent.protocol.audit import Audit
from localagent.protocol.scopes import INTERNAL_COMPARTMENT, Scope
from localagent.vault.store import Item, Vault

WITHHELD = {"withheld": "this data is outside the scope of this session"}


class ScopeError(PermissionError):
    """A request outside the session's granted scope."""


class UnknownToolError(LookupError):
    """The tool or action does not exist."""


@dataclass(frozen=True)
class ToolView:
    name: str
    actions: dict  # action name -> Action (description, params, kind)


def model_slug(model_id: str) -> str:
    return model_id.replace("/", "--")


RESET_EVENT = "history_reset"
PLAIN_TURNS = 2  # with tools, how many of the latest turns answered without one are replayed (see history())
OWNER_ADAPTER = INTERNAL_COMPARTMENT  # the internal model; peers get their connection's adapter, never this one


def _valid_transcript(transcript) -> bool:
    return (isinstance(transcript, list) and bool(transcript)
            and all(isinstance(m, dict) and m.get("role") in ("user", "assistant")
                    and isinstance(m.get("content"), str) for m in transcript)
            and transcript[-1]["role"] == "assistant")


class Session:
    def __init__(self, *, principal: str, scope: Scope, memory_compartment: str, vault: Vault,
                 audit: Audit, tools: dict, adapters_dir: Path):
        self.principal = principal
        self.scope = scope
        self.memory_compartment = memory_compartment
        self.vault = vault
        self.audit = audit
        self._tools = tools
        self.adapters_dir = Path(adapters_dir)

    def _compartments(self, kind: str) -> list[str]:
        return [c for c in self.vault.list_compartments(kind) if self.scope.allows(kind, c)]

    def context(self) -> list[Item]:
        """Knowledge and work items this session may see."""
        return (self.vault.read("knowledge", self._compartments("knowledge"))
                + self.vault.read("work", self._compartments("work")))

    def _own_memory(self) -> list[dict]:
        return [i.content for i in self.vault.read("memory", [self.memory_compartment])]

    def history(self, n: int) -> list[dict]:
        """Last n turns of this session's own conversation, as chat messages."""
        if n <= 0:
            return []
        records = self._own_memory()
        resets = [i for i, r in enumerate(records) if r.get("event") == RESET_EVENT]
        if resets:  # history starts after the latest reset, even across restarts
            records = records[resets[-1] + 1:]
        records = records[-n:]
        if self.tools():
            # Small models copy their own earlier answers over the system prompt: a few turns of guesses or
            # "I can't browse" and they stop calling tools. So only the latest tool-less turns are replayed;
            # turns that really used a tool are kept (they show working calls).
            plain = [i for i, r in enumerate(records)
                     if not any(c.get("ok") for c in r.get("tool_calls") or [] if isinstance(c, dict))]
            dropped = set(plain[:-PLAIN_TURNS])
            records = [r for i, r in enumerate(records) if i not in dropped]
        messages = []
        for record in records:
            if isinstance(record.get("user"), str) and isinstance(record.get("assistant"), str):
                messages.append({"role": "user", "content": record["user"]})
                # transcript = what the model itself said and was told (tool tags, tool results);
                # assistant = what the user saw. Replay the model's own words (with its tool tags) so it learns
                # from its working calls, but not the tool results: given those, small models start
                # writing fake "Tool results" themselves instead of calling the tool.
                transcript = record.get("transcript")
                if _valid_transcript(transcript):
                    said = "\n\n".join(m["content"] for m in transcript if m["role"] == "assistant" and m["content"])
                    messages.append({"role": "assistant", "content": said})
                else:
                    messages.append({"role": "assistant", "content": record["assistant"]})
        return messages

    def reset_history(self) -> None:
        """Stop replaying earlier turns to the model, for good. They stay saved in memory/."""
        self.vault.append_memory(self.memory_compartment, {"event": RESET_EVENT})

    def tools(self) -> list[ToolView]:
        views = []
        for name, tool in self._tools.items():
            allowed = {a: act for a, act in tool.actions.items() if self.scope.allows_tool(name, a)}
            if allowed:
                views.append(ToolView(name, allowed))
        return views

    def check_tool_call(self, name: str, action: str) -> None:
        tool = self._tools.get(name)
        if tool is None or action not in tool.actions:
            self.audit.log("tool_unknown", principal=self.principal, tool=name, action=action)
            raise UnknownToolError(f"Unknown tool action '{name}.{action}'")
        if not self.scope.allows_tool(name, action):
            self.audit.log("tool_denied", principal=self.principal, tool=name, action=action)
            raise ScopeError(f"'{name}.{action}' is outside this session's scope")

    def filter_tool_result(self, name: str, result):
        """A tool's data is visible only to sessions that may know its compartment."""
        compartment = self._tools[name].compartment
        if self.scope.allows("knowledge", compartment):
            return result
        self.audit.log("tool_result_withheld", principal=self.principal, tool=name, compartment=compartment)
        return WITHHELD

    def adapters(self, model_id: str) -> list[Path]:
        """The one adapter this session uses: `private` for the owner, its connection's for a peer. Adapters are
        never combined: one trained to answer and one trained to decline the same question would fight."""
        allowed = [c for c in self.vault.compartments if self.scope.allows("adapter", c)]
        if self.principal != "owner" and OWNER_ADAPTER in allowed:
            raise ValueError(f"Session '{self.principal}' may not load the private adapter; it is never loaded for peers")
        if self.scope.is_all:
            allowed = [c for c in allowed if c == OWNER_ADAPTER]
        if len(allowed) > 1:
            raise ValueError(f"Session '{self.principal}' may load adapters {allowed}; a session uses exactly one")
        path = self.adapters_dir / model_slug(model_id) / allowed[0] if allowed else None
        if path is None or not path.is_dir():
            return []
        try:
            info = json.loads((path / "adapter.json").read_text(encoding="utf-8"))
            trained_for = info.get("base_model")
            compartment = info.get("compartment")
        except (OSError, ValueError, AttributeError):
            trained_for = compartment = None
            info = None
        if self.principal != "owner" and (not isinstance(info, dict) or compartment != allowed[0]):
            # a peer's adapter is trusted by what adapter.json says it is, not by its folder name
            raise ValueError(f"Adapter {path} has no valid adapter.json naming '{allowed[0]}' as its compartment; "
                             "a peer session will not load it")
        if trained_for and trained_for != model_id:
            raise ValueError(f"Adapter {path} was trained for {trained_for}, not {model_id}. "
                             f"Retrain it: python -m localagent train --adapter {allowed[0]}")
        return [path]

    def record(self, turn: dict) -> None:
        self.vault.append_memory(self.memory_compartment, turn)

    def close(self) -> None:
        self.audit.log("session_closed", principal=self.principal)
