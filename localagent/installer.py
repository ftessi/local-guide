"""`python -m localagent install` and `list`: get every entry of installables.yaml ready, and show them."""
import subprocess
import sys
import tempfile
from pathlib import Path

from localagent.config import AgentConfig
from localagent.extensions import ExtensionError, is_remote, mcp_tool, source_dir


def _run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise ExtensionError(f"Command failed: {' '.join(cmd)}\n{(result.stderr or result.stdout).strip()}")


def _pip(requirements: list[str]) -> None:
    _run([sys.executable, "-m", "pip", "install", "--quiet", *requirements])


def fetch_source(agent_dir: Path, kind: str, name: str, settings: dict, log=print) -> Path:
    """Clone or update a git source into extensions/<kind>/<name>/; a local folder is used as it is."""
    source, ref = settings["source"], settings.get("ref")
    folder = source_dir(agent_dir, kind, name, source)
    if not is_remote(source):
        if not (folder / "__init__.py").is_file():
            raise ExtensionError(f"{kind}.{name}: {folder} has no __init__.py")
        return folder
    if (folder / ".git").is_dir():
        log(f"  updating {source}")
        _run(["git", "-C", str(folder), "fetch", "--quiet", "--depth", "1", "origin", ref or "HEAD"])
        _run(["git", "-C", str(folder), "checkout", "--quiet", "--detach", "FETCH_HEAD"])
    else:
        log(f"  downloading {source}")
        folder.parent.mkdir(parents=True, exist_ok=True)
        _run(["git", "clone", "--quiet", "--depth", "1", *(["--branch", ref] if ref else []), source, str(folder)])
    if not (folder / "__init__.py").is_file():
        raise ExtensionError(f"{kind}.{name}: {source} has no __init__.py at its top level")
    return folder


def check_mcp(name: str, settings: dict) -> list[str]:
    """Starts the server once (which also downloads it, for npx/uvx commands) and returns its action names."""
    tool = mcp_tool(name, {k: v for k, v in settings.items() if k not in ("compartment", "confirm")})
    with tempfile.TemporaryDirectory() as tmp:
        try:
            tool.setup(Path(tmp), None)
            return list(tool.actions)
        except Exception as e:
            raise ExtensionError(f"tools.{name}: {e}") from e
        finally:
            tool.close()


def install(config: AgentConfig, log=print, pip=None, check=check_mcp) -> int:
    pip = pip or _pip
    entries = [("tools", n, s) for n, s in config.installables.tools.items()]
    entries += [("connections", n, s) for n, s in config.installables.connections.items()]
    if not entries:
        log("installables.yaml lists no tools or connections; nothing to install.")
    for kind, name, settings in entries:
        log(f"{kind}/{name}")
        if settings.get("builtin"):
            log("  ok: built in")
        elif "mcp" in settings:
            packages = settings.get("pip") or []
            packages = [packages] if isinstance(packages, str) else list(packages)
            if packages:
                log(f"  pip install {' '.join(packages)}")
                pip(packages)
            actions = check(name, settings)
            log(f"  ok: MCP server runs; the model sees {len(actions)} action(s): {', '.join(actions)}")
        else:
            folder = fetch_source(config.agent_dir, kind, name, settings, log)
            if (folder / "requirements.txt").is_file():
                log("  pip install -r requirements.txt")
                pip(["-r", str(folder / "requirements.txt")])
            log(f"  ok: {folder}")
    return 0


def describe(config: AgentConfig) -> str:
    """Text for `python -m localagent list`."""
    lines = []
    for kind, entries in (("tools", config.installables.tools), ("connections", config.installables.connections)):
        lines.append(f"{kind}:")
        if not entries:
            lines.append("  (none)")
        for name, settings in entries.items():
            if settings.get("builtin"):
                where = "built in"
            elif "mcp" in settings:
                where = "MCP: " + " ".join(settings["mcp"])
            else:
                folder = source_dir(config.agent_dir, kind, name, settings["source"])
                state = "" if (folder / "__init__.py").is_file() else "   [not installed: run install]"
                where = f"{settings['source']}{state}"
            lines.append(f"  {name:<12} {where}")
    return "\n".join(lines)
