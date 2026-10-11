"""policy.yaml: which scopes the owner and each peer agent get."""
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from localagent.protocol.scopes import InvalidScope, Scope

DEFAULTS = {"owner": ["all"], "default_peer": ["knowledge:shared", "adapter:shared"], "peers": {}}


class PolicyError(ValueError):
    pass


@dataclass(frozen=True)
class Policy:
    owner: Scope
    default_peer: Scope
    peers: dict = field(default_factory=dict)

    def for_peer(self, agent_id: str) -> Scope:
        return self.peers.get(agent_id, self.default_peer)


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
    unknown = set(raw) - set(DEFAULTS)
    if unknown:
        raise PolicyError(f"Unknown key(s) in {path.name}: {', '.join(sorted(unknown))}")
    peers_raw = raw.get("peers") or {}
    if not isinstance(peers_raw, dict):
        raise PolicyError(f"'peers' in {path.name} must map agent ids to scope lists")
    try:
        return Policy(
            owner=Scope(raw.get("owner", DEFAULTS["owner"]) or []),
            default_peer=Scope(raw.get("default_peer", DEFAULTS["default_peer"]) or []),
            peers={str(k): Scope(v or []) for k, v in peers_raw.items()},
        )
    except InvalidScope as e:
        raise PolicyError(f"{path.name}: {e}") from e
