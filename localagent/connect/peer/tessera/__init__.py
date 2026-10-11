"""Tessera for LocalAgent: the built-in `tessera` connection, which only runs in an agent folder holding nothing
private (the Tessera-facing agent). Endpoint core, HTTP binding and client are in the modules next to this one."""
from pathlib import Path

from localagent.connect.base import Connection, SetupError
from localagent.protocol.identity import load_identity

INTERNAL = "private"
KEEP = ".gitkeep"
ROOT_FILES = {"agent.yaml", "installables.yaml", "policy.yaml", ".env", "README.md", "audit.log"}
ROOT_DIRS = {"identity", "data", "tessera", "memory", "training", "knowledge", "work"}


def _rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix() + ("/" if path.is_dir() else "")


def check_tessera_folder(config) -> list[str]:
    """Why this agent folder must not face other agents; empty means it may. An allowlist: anything not explicitly
    allowed is a problem. A Tessera-facing agent serves exactly one connection: one compartment, not private, and
    only that connection's exported adapter."""
    root, problems = Path(config.agent_dir), []
    compartment = config.compartments[0] if len(config.compartments) == 1 else None
    if len(config.compartments) != 1 or config.compartments[0] == INTERNAL:
        problems.append(f"agent.yaml must list exactly one compartment, the connection's, never private "
                        f"(it lists {config.compartments})")
    if config.installables.tools:
        problems.append(f"installables.yaml lists tools ({', '.join(config.installables.tools)}); "
                        "a Tessera-facing agent has none")
    others = [n for n in config.installables.connections if n != "tessera"]
    if others:
        problems.append(f"installables.yaml lists other connections ({', '.join(others)})")

    for entry in sorted(root.iterdir()):
        if entry.name == KEEP and entry.is_file():
            continue
        if entry.is_file() and entry.name in ROOT_FILES or entry.is_dir() and entry.name in ROOT_DIRS:
            continue
        problems.append(f"{_rel(entry, root)} is not allowed in the agent folder")

    for kind in ("knowledge", "work"):  # empty folders only
        for p in sorted((root / kind).rglob("*")) if (root / kind).is_dir() else []:
            if p.is_file() and p.name != KEEP:
                problems.append(f"{_rel(p, root)} is not allowed ({kind}/ must stay empty)")

    memory = root / "memory"  # peer memory only; a compartment's own conversations are never here
    for p in sorted(memory.iterdir()) if memory.is_dir() else []:
        if p.name == KEEP and p.is_file() or p.is_dir() and p.name.startswith("peer__"):
            continue
        if p.name == INTERNAL:
            problems.append("memory/private/ holds conversations (the private compartment)")
        else:
            problems.append(f"{_rel(p, root)} is not allowed (memory/ holds only peer__ folders)")

    training = root / "training"  # only exported adapters: training/adapters/<model>/<compartment>/
    for p in sorted(training.rglob("*")) if training.is_dir() else []:
        if p.name == KEEP and p.is_file():
            continue
        parts = p.relative_to(training).parts
        shown = _rel(p, root)
        if parts[0] != "adapters":
            if p.is_dir() and len(parts) > 1:
                continue  # its files are reported one by one
            if p.is_dir():
                problems.append(f"{shown} is not allowed (only adapters/ belongs in training/)")
            else:
                problems.append(f"{shown} is not an exported adapter")
        elif len(parts) <= 2:  # adapters/ and adapters/<model>/ are folders; files there are not adapters
            if p.is_file():
                problems.append(f"{shown} is not an exported adapter")
        elif len(parts) == 3 and parts[2] == compartment and p.is_dir():
            continue  # the one exported adapter; anything inside it is fine
        elif len(parts) == 3 and parts[2] == compartment:
            problems.append(f"{shown} is not an exported adapter")  # a file beside the adapter, not inside it
        elif len(parts) == 3 and parts[2] == INTERNAL:
            problems.append(f"the private adapter is here ({shown})")
        elif len(parts) == 3:
            problems.append(f"{shown} is not an exported adapter (only {compartment or 'the connection'} belongs here)")
        # deeper paths under a rejected adapter are reported with it

    data = root / "data"  # the connection's own data only
    for p in sorted(data.iterdir()) if data.is_dir() else []:
        if p.name == KEEP and p.is_file() or p.name == "tessera" and p.is_dir():
            continue
        problems.append(f"data/{_rel(p, data)} is not allowed (only the connection's data/tessera/ belongs here)")
    return problems


class TesseraConnection(Connection):
    name = "tessera"
    options = ("builtin", "host", "port")

    def setup(self, ctx) -> None:
        problems = check_tessera_folder(ctx.config)
        if problems:
            raise SetupError("This agent folder can't face other agents:\n- " + "\n- ".join(problems) +
                             "\nPeers must reach a separate agent folder that holds only exported connection "
                             "adapters (docs/guide/07-connect-to-others.md).")
        from localagent.connect.peer.tessera.endpoint import TesseraEndpoint
        from localagent.connect.peer.tessera.http import TesseraServer

        identity = load_identity(Path(ctx.config.agent_dir) / "identity")
        self.endpoint = TesseraEndpoint(identity, ctx.protocol, ctx.agent, name=ctx.config.name)
        self.server = TesseraServer(self.endpoint, str(ctx.settings.get("host", "127.0.0.1")),
                                    int(ctx.settings.get("port", 8100)))
        self.agent_id = identity.agent_id

    def start(self) -> None:
        self.server.start()
        print(f"Tessera: http://{self.server.host}:{self.server.port}/tessera  (agent id {self.agent_id})")

    def stop(self) -> None:
        self.server.stop()
