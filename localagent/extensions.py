"""Loads the tools and connections listed in installables.yaml. Not a layer itself.

Each entry comes from one of:
  source: <folder or git URL>   your own (or someone's) code: a folder whose __init__.py exports
                                TOOL (a localagent.agent.tools.base.Tool subclass) or
                                CONNECTION (a localagent.connect.base.Connection subclass),
                                plus an optional requirements.txt
  mcp: [command, args...]       tools only: any MCP server, e.g. [npx, -y, @modelcontextprotocol/server-filesystem]
"""
import importlib.util
import sys
from pathlib import Path

from localagent.agent.tools.base import Notify, Tool
from localagent.agent.tools.mcp_bridge import McpError, McpTool
from localagent.config import REPO_ROOT
from localagent.connect.base import Connection, ConnectionContext

EXTENSIONS_DIR = REPO_ROOT / "extensions"  # gitignored: where git sources are cloned, as <kind>/<name>/
SOURCE_KEYS = {"source", "ref"}
MCP_KEYS = {"mcp", "pip", "cwd", "env", "actions", "fixed_args", "describe", "max_result_chars", "timeout"}


class ExtensionError(ValueError):
    """An installable is missing, broken, or misconfigured."""


def is_remote(source: str) -> bool:
    return "://" in source or source.startswith("git@")


def source_dir(agent_dir: Path, kind: str, name: str, source: str) -> Path:
    """Where an entry's code is: its clone in extensions/, or the local folder (relative to the agent folder)."""
    if is_remote(source):
        return EXTENSIONS_DIR / kind / name
    path = Path(source).expanduser()
    return path if path.is_absolute() else (Path(agent_dir) / path).resolve()


def _import(folder: Path, kind: str, name: str):
    if not (folder / "__init__.py").is_file():
        raise ExtensionError(f"{kind[:-1].capitalize()} '{name}' is not installed (no {folder / '__init__.py'}).\n"
                             "Run:  python -m localagent install")
    module_name = f"localagent_ext.{kind}.{name}"
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, folder / "__init__.py",
                                                  submodule_search_locations=[str(folder)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except ImportError as e:
        del sys.modules[module_name]
        raise ExtensionError(f"{kind[:-1].capitalize()} '{name}' could not be imported ({e}).\n"
                             "Its requirements may be missing. Run:  python -m localagent install") from e
    except BaseException:
        del sys.modules[module_name]
        raise
    return module


def _check_options(kind: str, name: str, settings: dict, allowed) -> None:
    unknown = set(settings) - set(allowed)
    if unknown:
        raise ExtensionError(f"Unknown setting(s) for {kind[:-1]} '{name}' in installables.yaml: "
                             f"{', '.join(sorted(unknown))} (allowed: {', '.join(sorted(allowed))})")


def mcp_tool(name: str, settings: dict) -> McpTool:
    _check_options("tools", name, settings, MCP_KEYS | {"compartment", "confirm", "follow"})
    cwd = Path(settings["cwd"]) if settings.get("cwd") else None
    if cwd is not None:
        cwd.mkdir(parents=True, exist_ok=True)  # e.g. the agent's workspace folder
    return McpTool(name, list(settings["mcp"]), cwd=cwd, env=settings.get("env"),
                   only=settings.get("actions") or (), fixed_args=settings.get("fixed_args"),
                   describe=settings.get("describe"), max_result_chars=int(settings.get("max_result_chars", 4000)),
                   timeout=float(settings.get("timeout", 60)))


def load_tools(tools_config: dict, agent_dir: Path, data_root: Path, notify: Notify | None,
               compartments: list[str]) -> dict[str, Tool]:
    """Creates and sets up every listed tool. MCP servers are started here (before the model loads)."""
    tools = {}
    try:
        for name, settings in (tools_config or {}).items():
            settings = dict(settings)
            compartment = settings.pop("compartment", None)
            confirm = settings.pop("confirm", None)
            follow = settings.pop("follow", None) or {}
            if "mcp" in settings:
                tool = mcp_tool(name, settings)
                settings = {}
            else:
                folder = source_dir(agent_dir, "tools", name, settings["source"])
                tool_cls = getattr(_import(folder, "tools", name), "TOOL", None)
                if not (isinstance(tool_cls, type) and issubclass(tool_cls, Tool)):
                    raise ExtensionError(f"{folder / '__init__.py'} must export TOOL, a Tool subclass")
                tool = tool_cls()
                settings = {k: v for k, v in settings.items() if k not in SOURCE_KEYS}
                _check_options("tools", name, settings, {"compartment", "confirm", "follow", *tool.options})
            tool.compartment = compartment or tool.compartment
            if confirm is not None:
                tool.confirm = bool(confirm)
            tool.settings = settings
            if tool.compartment not in compartments:
                raise ExtensionError(f"Tool '{name}' uses compartment '{tool.compartment}', "
                                     f"which is not in agent.yaml compartments {compartments}")
            try:
                tool.setup(Path(data_root) / name, notify)
            except McpError as e:
                raise ExtensionError(str(e)) from e
            tools[name] = tool
            tool.follow = _check_follow(name, tool, follow)
    except BaseException:
        close_tools(tools)
        raise
    return tools


def _check_follow(name: str, tool: Tool, follow: dict) -> dict:
    """`follow: {search: fetch_content}`: after a search, the agent opens the links it found itself, so a small
    model doesn't have to decide to. The second action gets each link as its one required argument."""
    if not isinstance(follow, dict):
        raise ExtensionError(f"Tool '{name}': follow must look like {{search: fetch_content}}")
    for first, then in follow.items():
        for action in (first, then):
            if action not in tool.actions:
                raise ExtensionError(f"Tool '{name}': follow names action '{action}', which it doesn't have "
                                     f"(it has: {', '.join(tool.actions)})")
        spec = tool.actions[then]
        if len([p for p in spec.params if p not in spec.optional]) != 1:
            raise ExtensionError(f"Tool '{name}': follow action '{then}' must take exactly one required "
                                 "argument (the link)")
    return dict(follow)


def close_tools(tools: dict) -> None:
    for tool in tools.values():
        close = getattr(tool, "close", None)
        if close:
            close()


def load_connections(connections_config: dict, agent_dir: Path) -> dict[str, Connection]:
    """Imports and checks the listed connections. setup() is called later, once the agent exists."""
    connections = {}
    for name, settings in (connections_config or {}).items():
        folder = source_dir(agent_dir, "connections", name, settings["source"])
        conn_cls = getattr(_import(folder, "connections", name), "CONNECTION", None)
        if not (isinstance(conn_cls, type) and issubclass(conn_cls, Connection)):
            raise ExtensionError(f"{folder / '__init__.py'} must export CONNECTION, a Connection subclass")
        connection = conn_cls()
        _check_options("connections", name, _own_settings(settings), connection.options)
        connections[name] = connection
    return connections


def _own_settings(settings: dict) -> dict:
    return {k: v for k, v in (settings or {}).items() if k not in SOURCE_KEYS}


def setup_connections(connections: dict[str, Connection], connections_config: dict, data_root: Path,
                      **ctx_fields) -> None:
    for name, connection in connections.items():
        data_dir = Path(data_root) / name
        data_dir.mkdir(parents=True, exist_ok=True)
        connection.setup(ConnectionContext(settings=_own_settings(connections_config.get(name)),
                                           data_dir=data_dir, **ctx_fields))
