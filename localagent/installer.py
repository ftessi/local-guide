"""`python -m localagent install`: fetch the extensions source and install what installables.yaml lists."""
import subprocess
import sys
from pathlib import Path

from localagent.config import AgentConfig
from localagent.extensions import ExtensionError, available, extension_root, is_remote


def _run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise ExtensionError(f"Command failed: {' '.join(cmd)}\n{(result.stderr or result.stdout).strip()}")


def fetch_source(config: AgentConfig, log=print) -> Path:
    """Clone or update a remote source into extensions/; a local folder is used as it is."""
    source, ref = config.installables.source, config.installables.ref
    root = extension_root(config)
    if not is_remote(source):
        if not root.is_dir():
            raise ExtensionError(f"Extensions folder {root} (source in installables.yaml) does not exist")
        log(f"Using local extensions at {root}")
    elif (root / ".git").is_dir():
        log(f"Updating {source} ({ref})...")
        _run(["git", "-C", str(root), "fetch", "--depth", "1", "origin", ref])
        _run(["git", "-C", str(root), "checkout", "--quiet", "--detach", "FETCH_HEAD"])
    else:
        log(f"Downloading {source} ({ref})...")
        root.parent.mkdir(parents=True, exist_ok=True)
        _run(["git", "clone", "--quiet", "--depth", "1", "--branch", ref, source, str(root)])
    return root


def install(config: AgentConfig, log=print, pip=None) -> int:
    pip = pip or (lambda req: _run([sys.executable, "-m", "pip", "install", "--quiet", "-r", str(req)]))
    root = fetch_source(config, log)
    found = available(root)
    wanted = {"tools": config.installables.tools, "connections": config.installables.connections}
    missing = [f"{kind}/{name}" for kind, names in wanted.items() for name in names if name not in found[kind]]
    if missing:
        raise ExtensionError(f"Not in {root}: {', '.join(missing)}. "
                             f"Available: {', '.join(f'{k}/{n}' for k in found for n in found[k]) or 'nothing'}")
    for kind, names in wanted.items():
        for name in names:
            requirements = root / kind / name / "requirements.txt"
            if requirements.is_file():
                log(f"Installing requirements of {kind}/{name}...")
                pip(requirements)
            log(f"  ok  {kind}/{name}")
    if not any(wanted.values()):
        log("installables.yaml lists no tools or connections; nothing to install.")
    return 0


def describe(config: AgentConfig) -> str:
    """Text for `python -m localagent list`: what the source offers and what this agent uses."""
    root = extension_root(config)
    if not root.is_dir():
        return f"Extensions not downloaded yet ({config.installables.source}). Run:  python -m localagent install"
    found = available(root)
    wanted = {"tools": config.installables.tools, "connections": config.installables.connections}
    lines = [f"Extensions in {root}  ([x] = used by this agent)"]
    for kind in found:
        lines.append(f"\n{kind}:")
        for name, summary in found[kind].items():
            lines.append(f"  [{'x' if name in wanted[kind] else ' '}] {name:<14} {summary}")
    return "\n".join(lines)
