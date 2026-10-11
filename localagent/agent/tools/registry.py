"""Load the tools enabled in agent.yaml. A tool is a package localagent/agent/tools/<name>/ exporting TOOL."""
import importlib
import re
from pathlib import Path

from localagent.agent.tools.base import Notify, Tool

_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
_SETTINGS = {"enabled", "compartment"}


class ToolConfigError(ValueError):
    pass


def load_tools(tools_config: dict, data_root: Path, notify: Notify | None,
               compartments: list[str]) -> dict[str, Tool]:
    tools = {}
    for name, cfg in (tools_config or {}).items():
        cfg = cfg or {}
        unknown = set(cfg) - _SETTINGS
        if unknown:
            raise ToolConfigError(f"Unknown setting(s) for tool '{name}': {', '.join(sorted(unknown))}")
        if not cfg.get("enabled", True):
            continue
        if not _NAME.match(name):
            raise ToolConfigError(f"Invalid tool name '{name}'")
        module_name = f"localagent.agent.tools.{name}"
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError as e:
            if e.name == module_name:
                raise ToolConfigError(
                    f"Unknown tool '{name}' in agent.yaml (no folder localagent/agent/tools/{name}/)"
                ) from e
            raise
        tool = module.TOOL()
        tool.compartment = cfg.get("compartment", tool.compartment)
        if tool.compartment not in compartments:
            raise ToolConfigError(f"Tool '{name}' uses compartment '{tool.compartment}', "
                                  f"which is not in agent.yaml compartments {compartments}")
        tool.setup(Path(data_root) / name, notify)
        tools[name] = tool
    return tools
