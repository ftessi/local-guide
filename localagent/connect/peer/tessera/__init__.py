"""Tessera for LocalAgent: the built-in `tessera` connection, which only runs in an agent folder holding nothing
private (the Tessera-facing agent). Endpoint core, HTTP binding and client are in the modules next to this one."""
from pathlib import Path

from localagent.connect.base import Connection, SetupError
from localagent.protocol.identity import load_identity

INTERNAL = "private"


def _has_files(folder: Path) -> bool:
    return folder.is_dir() and any(p.is_file() and not p.name.startswith(".") for p in folder.rglob("*"))


def check_tessera_folder(config) -> list[str]:
    """Why this agent folder must not face other agents; empty means it may. A Tessera-facing agent serves exactly
    one connection: one compartment, not private, holding only that connection's exported adapter."""
    root, problems = Path(config.agent_dir), []
    if len(config.compartments) != 1 or config.compartments[0] == INTERNAL:
        problems.append(f"agent.yaml must list exactly one compartment, the connection's, never private "
                        f"(it lists {config.compartments})")
    if config.installables.tools:
        problems.append(f"installables.yaml lists tools ({', '.join(config.installables.tools)}); "
                        "a Tessera-facing agent has none")
    others = [n for n in config.installables.connections if n != "tessera"]
    if others:
        problems.append(f"installables.yaml lists other connections ({', '.join(others)})")
    for kind in ("knowledge", "work"):
        if _has_files(root / kind):
            problems.append(f"{kind}/ has files")
    training = root / "training"
    for d in sorted(training.iterdir()) if training.is_dir() else []:
        if d.is_dir() and d.name != "adapters" and ((d / "sources").exists() or (d / "examples.jsonl").exists()):
            problems.append(f"training/{d.name}/ has sources or examples (only exported adapters belong here)")
    for model_dir in sorted((training / "adapters").glob("*")) if (training / "adapters").is_dir() else []:
        for adapter in sorted(model_dir.iterdir()) if model_dir.is_dir() else []:
            if adapter.name == INTERNAL:
                problems.append(f"the private adapter is here ({adapter})")
            elif adapter.is_dir() and not adapter.name.endswith(".tmp") and adapter.name not in config.compartments:
                problems.append(f"adapter '{adapter.name}' is not a compartment in agent.yaml")
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
