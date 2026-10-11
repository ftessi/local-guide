"""The guard: opens sessions, builds training sets, keeps Tessera's peer list and records. The only owner of the vault."""
import hmac
from datetime import datetime
from pathlib import Path

from localagent.protocol.audit import Audit
from localagent.protocol.policy import PeerEntry, Policy, PolicyError, load_policy, make_peer_entry, save_policy
from localagent.protocol.scopes import Scope
from localagent.protocol.session import Session, model_slug
from localagent.vault.store import Vault

OWNER_MEMORY = "private"


class AuthError(PermissionError):
    pass


class Protocol:
    def __init__(self, *, vault: Vault, policy: Policy, audit: Audit, tools: dict,
                 adapters_dir: Path, owner_secret: str, policy_path: Path | None = None):
        self.vault = vault
        self.policy = policy
        self.audit = audit
        self.tools = tools
        self.adapters_dir = Path(adapters_dir)
        self._owner_secret = owner_secret or ""
        self.policy_path = Path(policy_path) if policy_path else None
        self._policy_stamp = self._stamp()

    @classmethod
    def for_agent(cls, agent_dir: Path, compartments: list[str], tools: dict, owner_secret: str) -> "Protocol":
        agent_dir = Path(agent_dir)
        return cls(vault=Vault(agent_dir, compartments), policy=load_policy(agent_dir / "policy.yaml"),
                   audit=Audit(agent_dir / "audit.log"), tools=tools,
                   adapters_dir=agent_dir / "training" / "adapters", owner_secret=owner_secret,
                   policy_path=agent_dir / "policy.yaml")

    def _session(self, principal: str, scope, memory_compartment: str) -> Session:
        return Session(principal=principal, scope=scope, memory_compartment=memory_compartment,
                       vault=self.vault, audit=self.audit, tools=self.tools, adapters_dir=self.adapters_dir)

    def open_owner_session(self, token: str) -> Session:
        if not self._owner_secret:
            self.audit.log("auth_failed", principal="owner", reason="no AGENT_SECRET configured")
            raise AuthError("AGENT_SECRET is not set in the agent's .env, so owner access is disabled")
        if not isinstance(token, str) or not hmac.compare_digest(token.encode(), self._owner_secret.encode()):
            self.audit.log("auth_failed", principal="owner", reason="wrong token")
            raise AuthError("Invalid token")
        self.audit.log("session_opened", principal="owner", scope=sorted(self.policy.owner.items))
        return self._session("owner", self.policy.owner, OWNER_MEMORY)

    # ── Tessera peers ────────────────────────────────────────────────────────

    def _stamp(self) -> tuple | None:
        """Identifies the current policy.yaml. Time alone can repeat within one clock tick on Windows; a rewrite
        (save_policy replaces the file) also changes the file id, and usually the size."""
        try:
            st = self.policy_path.stat() if self.policy_path else None
        except OSError:
            return None
        return (st.st_mtime_ns, st.st_size, st.st_ino) if st else None

    def _current_policy(self) -> Policy:
        """Re-read policy.yaml if it changed: `peers remove` in another terminal applies to a running server."""
        stamp = self._stamp()
        if stamp != self._policy_stamp:
            self.policy, self._policy_stamp = load_policy(self.policy_path), stamp
        return self.policy

    def connection(self) -> str | None:
        """The connection a Tessera-facing agent serves: its only compartment. None for any other agent."""
        compartments = self.vault.compartments
        return compartments[0] if len(compartments) == 1 and compartments[0] != OWNER_MEMORY else None

    def peer_grant(self, agent_id: str, requested_level: int) -> PeerEntry | None:
        """What a requesting agent gets: None (refuse) unless the owner accepted it on a Tessera-facing agent."""
        entry = self._current_policy().peer(agent_id)
        if entry is None:
            return None
        if self.connection() is None:
            self.audit.log("tessera_not_facing", peer=agent_id)
            return None
        level = min(requested_level, entry.level)
        return PeerEntry(entry.name, level) if level >= 1 else None

    def open_peer_session(self, agent_id: str) -> Session:
        """A peer gets the connection's adapter and its own memory. No tools, no knowledge, no work, ever."""
        entry = self.peer_grant(agent_id, 1)
        if entry is None:
            self.audit.log("auth_failed", principal=f"peer:{agent_id}", reason="not an accepted peer")
            raise AuthError("Not an accepted peer")
        scope = Scope([f"adapter:{self.connection()}", f"memory:peer:{agent_id}"])
        self.audit.log("session_opened", principal=f"peer:{agent_id}", scope=sorted(scope.items))
        return self._session(f"peer:{agent_id}", scope, f"peer:{agent_id}")

    def _latest_requests(self) -> dict:
        latest = {}
        for record in self.vault.read_tessera("requests"):
            latest[record.get("id")] = record
        return latest

    def record_request(self, agent_id: str, purpose: str, level: int) -> None:
        """Remembers an unknown agent's request for the owner, once: repeats and rejected agents add nothing."""
        if self._current_policy().peer(agent_id) is not None or agent_id in self._latest_requests():
            return
        self.vault.append_tessera("requests", {"id": agent_id, "purpose": purpose, "level": level,
                                               "status": "pending",
                                               "time": datetime.now().isoformat(timespec="seconds")})
        self.audit.log("tessera_request", peer=agent_id, level=level)

    def requests(self) -> list[dict]:
        policy = self._current_policy()
        return [r for r in self._latest_requests().values()
                if r.get("status") == "pending" and policy.peer(r.get("id")) is None]

    def _set_request_status(self, agent_id: str, status: str) -> None:
        if agent_id in self._latest_requests():
            self.vault.append_tessera("requests", {**self._latest_requests()[agent_id], "status": status,
                                                   "time": datetime.now().isoformat(timespec="seconds")})

    def _save(self, peers: dict) -> None:
        if self.policy_path is None:
            raise PolicyError("This protocol has no policy.yaml to write")
        policy = Policy(owner=self._current_policy().owner, peers=peers)
        save_policy(self.policy_path, policy)
        self.policy, self._policy_stamp = policy, self._stamp()

    def accept_peer(self, agent_id: str, *, name: str, level: int = 1) -> PeerEntry:
        if self.connection() is None:
            raise PolicyError("Only a Tessera-facing agent accepts peers: its agent.yaml lists exactly one "
                              "compartment, not private (docs/guide/07-connect-to-others.md)")
        entry = make_peer_entry(agent_id, name, level)
        self._save({**self._current_policy().peers, agent_id: entry})
        self._set_request_status(agent_id, "accepted")
        self.audit.log("tessera_peer_accepted", peer=agent_id, level=level)
        return entry

    def reject_request(self, agent_id: str) -> None:
        self._set_request_status(agent_id, "rejected")
        self.audit.log("tessera_request_rejected", peer=agent_id)

    def remove_peer(self, agent_id: str) -> None:
        peers = dict(self._current_policy().peers)
        if peers.pop(agent_id, None) is None:
            raise PolicyError(f"{agent_id} is not an accepted peer")
        self._save(peers)
        self._set_request_status(agent_id, "rejected")
        self.audit.log("tessera_peer_removed", peer=agent_id)

    def record_envelope(self, other_id: str, session_id: str, envelope: dict) -> None:
        self.vault.append_tessera(f"{other_id}/{session_id}", envelope)

    def read_record(self, other_id: str, session_id: str) -> list[dict]:
        return self.vault.read_tessera(f"{other_id}/{session_id}")

    def training_set(self, compartment: str) -> list[dict]:
        """Only examples labeled exactly `compartment`. Peer data is never included."""
        if compartment not in self.vault.compartments:
            raise ValueError(f"Training sets exist only for configured compartments "
                             f"{self.vault.compartments}, not '{compartment}'")
        return [i.content for i in self.vault.read("training", [compartment]) if i.compartment == compartment]

    def training_sources(self, compartment: str) -> list[tuple[str, object]]:
        return self.vault.read_sources(compartment)

    def replace_training_examples(self, compartment: str, examples: list[dict]) -> None:
        self.vault.replace_training_examples(compartment, examples)

    def adapter_path(self, model_id: str, compartment: str) -> Path:
        return self.adapters_dir / model_slug(model_id) / compartment
