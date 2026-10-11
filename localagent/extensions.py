"""Finds and loads installables (tools and connections) from the extensions source. Not a layer itself.

An extensions source is a folder (usually a clone of the extensions repo) laid out as:
    tools/<name>/__init__.py         exports TOOL       (a localagent.agent.tools.base.Tool subclass)
    connections/<name>/__init__.py   exports CONNECTION (a localagent.connect.base.Connection subclass)
    <either>/<name>/requirements.txt optional pip requirements, installed by `python -m localagent install`
"""
import ast
import importlib.util
import re
import sys
from pathlib import Path

from localagent.agent.tools.base import Notify, Tool
from localagent.config import REPO_ROOT, AgentConfig
from localagent.connect.base import Connection, ConnectionContext

EXTENSIONS_DIR = REPO_ROOT / "extensions"  # gitignored: where remote sources are cloned
KINDS = ("tools", "connections")


class ExtensionError(ValueError):
    """An installable is missing, broken, or misconfigured."""


def is_remote(source: str) -> bool:
    return "://" in source or source.startswith("git@")


def source_slug(source: str) -> str:
    """https://github.com/ftessi/local-guide-extensions.git -> ftessi--local-guide-extensions"""
    parts = [p for p in re.split(r"[/:]", source.removesuffix(".git")) if p][-2:]
    return re.sub(r"[^A-Za-z0-9._-]", "-", "--".join(parts))


def extension_root(config: AgentConfig) -> Path:
    source = config.installables.source
    if is_remote(source):
        return EXTENSIONS_DIR / source_slug(source)
    path = Path(source).expanduser()
    return path if path.is_absolute() else (config.agent_dir / path).resolve()


def available(root: Path) -> dict[str, dict[str, str]]:
    """{kind: {name: first line of its docstring}} for everything in a source."""
    found = {}
    for kind in KINDS:
        found[kind] = {}
        for init in sorted(Path(root, kind).glob("*/__init__.py")):
            doc = ast.get_docstring(ast.parse(init.read_text(encoding="utf-8"))) or ""
            found[kind][init.parent.name] = doc.strip().splitlines()[0] if doc.strip() else ""
    return found


def _import(root: Path, kind: str, name: str):
    folder = Path(root) / kind / name
    if not (folder / "__init__.py").is_file():
        raise ExtensionError(
            f"{kind[:-1].capitalize()} '{name}' is listed in installables.yaml but not installed "
            f"(no {folder}).\nRun:  python -m localagent install")
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
                             f"Its requirements may be missing. Run:  python -m localagent install") from e
    except BaseException:
        del sys.modules[module_name]
        raise
    return module


def _check_options(kind: str, name: str, settings: dict, allowed) -> None:
    unknown = set(settings) - set(allowed)
    if unknown:
        raise ExtensionError(f"Unknown setting(s) for {kind[:-1]} '{name}' in installables.yaml: "
                             f"{', '.join(sorted(unknown))} (allowed: {', '.join(sorted(allowed)) or 'none'})")


def load_tools(tools_config: dict, root: Path, data_root: Path, notify: Notify | None,
               compartments: list[str]) -> dict[str, Tool]:
    tools = {}
    for name, settings in (tools_config or {}).items():
        settings = dict(settings or {})
        tool_cls = getattr(_import(root, "tools", name), "TOOL", None)
        if not (isinstance(tool_cls, type) and issubclass(tool_cls, Tool)):
            raise ExtensionError(f"tools/{name}/__init__.py must export TOOL, a Tool subclass")
        tool = tool_cls()
        _check_options("tools", name, settings, {"compartment", *tool.options})
        tool.compartment = settings.pop("compartment", tool.compartment)
        tool.settings = settings
        if tool.compartment not in compartments:
            raise ExtensionError(f"Tool '{name}' uses compartment '{tool.compartment}', "
                                 f"which is not in agent.yaml compartments {compartments}")
        tool.setup(Path(data_root) / name, notify)
        tools[name] = tool
    return tools


def load_connections(connections_config: dict, root: Path) -> dict[str, Connection]:
    """Imports and checks the listed connections. setup() is called later, once the agent exists."""
    connections = {}
    for name, settings in (connections_config or {}).items():
        conn_cls = getattr(_import(root, "connections", name), "CONNECTION", None)
        if not (isinstance(conn_cls, type) and issubclass(conn_cls, Connection)):
            raise ExtensionError(f"connections/{name}/__init__.py must export CONNECTION, a Connection subclass")
        connection = conn_cls()
        _check_options("connections", name, settings or {}, connection.options)
        connections[name] = connection
    return connections


def setup_connections(connections: dict[str, Connection], connections_config: dict, data_root: Path,
                      **ctx_fields) -> None:
    for name, connection in connections.items():
        data_dir = Path(data_root) / name
        data_dir.mkdir(parents=True, exist_ok=True)
        connection.setup(ConnectionContext(settings=dict(connections_config.get(name) or {}),
                                           data_dir=data_dir, **ctx_fields))
