"""policy.yaml: what your own sessions get, and which agents you accepted, at which Tessera level. Peers are
only used by a Tessera-facing agent, which serves exactly one connection (its only compartment)."""
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from localagent.protocol.identity import AGENT_ID_RE
from localagent.protocol.scopes import InvalidScope, Scope

LEVELS_AVAILABLE = (1,)  # 1 = Ask. Tessera levels 2-4 are specified but not implemented yet
HEADER = ("# Who may see what. owner: your own sessions. peers: agents you accepted (python -m localagent peers)\n"
          "# and their Tessera level (1 = Ask). Only a Tessera-facing agent (one compartment) uses peers.\n"
          "# `peers accept/reject/remove` rewrite this file: comments other than this header are not kept.\n")


class PolicyError(ValueError):
    pass


@dataclass(frozen=True)
class PeerEntry:
    name: str
    level: int


@dataclass(frozen=True)
class Policy:
    owner: Scope
    peers: dict = field(default_factory=dict)  # agent id -> PeerEntry

    def peer(self, agent_id: str) -> PeerEntry | None:
        return self.peers.get(agent_id)


def make_peer_entry(agent_id, name, level, where: str = "policy.yaml") -> PeerEntry:
    if not isinstance(agent_id, str) or not AGENT_ID_RE.fullmatch(agent_id):
        raise PolicyError(f"{where}: '{agent_id}' is not an agent id (43 characters, from `python -m localagent id`)")
    if not isinstance(name, str) or not name.strip():
        raise PolicyError(f"{where}: peer {agent_id[:8]}… needs a name")
    if type(level) is not int or level not in LEVELS_AVAILABLE:
        raise PolicyError(f"{where}: peer {name}: level {level} is not available (only 1 = Ask for now)")
    return PeerEntry(name.strip(), level)


def load_policy(path: Path) -> Policy:
    path = Path(path)
    raw = {}
    if path.is_file():
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as e:
            raise PolicyError(f"{path.name} is not valid YAML: {e}") from e
    if not isinstance(raw, dict):
        raise PolicyError(f"{path.name} must be a mapping")
    if "default_peer" in raw:
        raise PolicyError(f"'default_peer' in {path.name} was removed: agents you haven't accepted now get nothing. "
                          "Delete that line, and accept agents with: python -m localagent peers accept")
    unknown = set(raw) - {"owner", "peers"}
    if unknown:
        raise PolicyError(f"Unknown key(s) in {path.name}: {', '.join(sorted(unknown))}")
    peers_raw = raw.get("peers") or {}
    if not isinstance(peers_raw, dict):
        raise PolicyError(f"'peers' in {path.name} must map agent ids to {{name, level}}")
    peers = {}
    for agent_id, entry in peers_raw.items():
        if not isinstance(entry, dict) or set(entry) != {"name", "level"}:
            raise PolicyError(f"{path.name}: each peer must look like {{name: \"Bob's agent\", level: 1}}")
        peers[agent_id] = make_peer_entry(agent_id, entry["name"], entry["level"], path.name)
    try:
        owner = Scope(raw.get("owner", ["all"]) or [])
    except InvalidScope as e:
        raise PolicyError(f"{path.name}: {e}") from e
    return Policy(owner=owner, peers=peers)


def save_policy(path: Path, policy: Policy) -> None:
    data = {"owner": sorted(policy.owner.items),
            "peers": {k: {"name": e.name, "level": e.level} for k, e in policy.peers.items()}}
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(HEADER + yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    tmp.replace(path)
