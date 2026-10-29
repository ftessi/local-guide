"""The guard: opens sessions, builds training sets, keeps Tessera's peer list and records. The only owner of the vault."""
import hmac
import logging
from datetime import datetime
from pathlib import Path

from localagent.protocol.audit import Audit
from localagent.protocol.identity import AGENT_ID_RE, load_record_key
from localagent.protocol.policy import PeerEntry, Policy, PolicyError, load_policy, make_peer_entry, save_policy
from localagent.protocol.scopes import INTERNAL_COMPARTMENT, Scope
from localagent.protocol.session import Session, model_slug
from localagent.protocol.tessera.records import is_sealed, open_line, seal_line
from localagent.vault.store import Vault

OWNER_MEMORY = INTERNAL_COMPARTMENT


class AuthError(PermissionError):
    pass


class Protocol:
    def __init__(self, *, vault: Vault, policy: Policy, audit: Audit, tools: dict,
                 adapters_dir: Path, owner_secret: str, policy_path: Path | None = None,
                 identity_dir: Path | None = None):
        self.vault = vault
        self.policy = policy
        self.audit = audit
        self.tools = tools
        self.adapters_dir = Path(adapters_dir)
        self._owner_secret = owner_secret or ""
        self.policy_path = Path(policy_path) if policy_path else None
        self.identity_dir = Path(identity_dir) if identity_dir else None
        self._record_key = None  # loaded when a record is first read or written
        self._policy_stamp = self._stamp()
        self._invalid_stamp = None  # the last broken policy.yaml we audited, so it is audited once

    @classmethod
    def for_agent(cls, agent_dir: Path, compartments: list[str], tools: dict, owner_secret: str) -> "Protocol":
        agent_dir = Path(agent_dir)
        protocol = cls(vault=Vault(agent_dir, compartments), policy=load_policy(agent_dir / "policy.yaml"),
                       audit=Audit(agent_dir / "audit.log"), tools=tools,
                       adapters_dir=agent_dir / "training" / "adapters", owner_secret=owner_secret,
                       policy_path=agent_dir / "policy.yaml", identity_dir=agent_dir / "identity")
        protocol.seal_plain_records()
        return protocol

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
        """Re-read policy.yaml if it changed: `peers remove` in another terminal applies to a running server.
        A broken file fails closed: nobody is a peer until it is fixed. The stamp is not advanced, so the
        next call retries the file."""
        stamp = self._stamp()
        if stamp != self._policy_stamp:
            try:
                self.policy = load_policy(self.policy_path)
            except PolicyError as e:
                if stamp != self._invalid_stamp:
                    self._invalid_stamp = stamp
                    self.audit.log("tessera_policy_invalid", reason=str(e))
                self.policy = Policy(owner=self.policy.owner, peers={})
                return self.policy
            self._policy_stamp = stamp
        return self.policy

    def _fresh_policy(self) -> Policy:
        """For writes: read policy.yaml now and refuse if it is broken, so a save never drops other peers."""
        if self.policy_path is None:
            raise PolicyError("This protocol has no policy.yaml to write")
        return load_policy(self.policy_path)

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

    def public_grant(self, agent_id: str) -> PeerEntry | None:
        """A public agent (connections.tessera `public: true`) answers strangers that come through the relay at level 1.
        Never a request for the owner; a rejected or removed id stays refused."""
        if not isinstance(agent_id, str) or not AGENT_ID_RE.fullmatch(agent_id) or self.connection() is None:
            return None
        if self._latest_requests().get(agent_id, {}).get("status") == "rejected":
            return None
        return PeerEntry("public", 1)

    def chain_allowed(self, ids: list[str], *, public: bool, via: str) -> bool:
        """A delegated ask (v0.3): every id in its mandate chain must be allowed as if it had asked directly, the
        same way. Unknown ids become requests for the owner, but only when this agent isn't public."""
        refused = [i for i in ids if self.peer_grant(i, 1) is None and not (public and self.public_grant(i))]
        for agent_id in refused:
            if not public:
                self.record_request(agent_id, f"via {via}", 1)
            self.audit.log("tessera_chain_refused", peer=agent_id, via=via)
        return not refused

    def open_peer_session(self, agent_id: str, *, public: bool = False) -> Session:
        """A peer gets the connection's adapter and its own memory. No tools, no knowledge, no work, ever."""
        entry = self.peer_grant(agent_id, 1)
        if entry is None and public:
            entry = self.public_grant(agent_id)
        if entry is None:
            self.audit.log("auth_failed", principal=f"peer:{agent_id}", reason="not an accepted peer")
            raise AuthError("Not an accepted peer")
        scope = Scope([f"adapter:{self.connection()}", f"memory:peer:{agent_id}"])
        self.audit.log("session_opened", principal=f"peer:{agent_id}", scope=sorted(scope.items))
        return self._session(f"peer:{agent_id}", scope, f"peer:{agent_id}")

    def _latest_requests(self) -> dict:
        latest = {}
        for record in self._read("requests"):
            latest[record.get("id")] = record
        return latest

    def record_request(self, agent_id: str, purpose: str, level: int) -> None:
        """Remembers an unknown agent's request for the owner, once: repeats and rejected agents add nothing."""
        if not isinstance(agent_id, str) or not AGENT_ID_RE.fullmatch(agent_id):
            return
        if self._current_policy().peer(agent_id) is not None or agent_id in self._latest_requests():
            return
        self._append("requests", {"id": agent_id, "purpose": str(purpose)[:200], "level": level,
                                               "status": "pending",
                                               "time": datetime.now().isoformat(timespec="seconds")})
        self.audit.log("tessera_request", peer=agent_id, level=level)

    def requests(self) -> list[dict]:
        policy = self._current_policy()
        return [r for r in self._latest_requests().values()
                if r.get("status") == "pending" and policy.peer(r.get("id")) is None]

    def _set_request_status(self, agent_id: str, status: str) -> None:
        """Appends the id's latest state with a new status; an id never requested gets a bare record, so it
        can't queue itself later."""
        base = self._latest_requests().get(agent_id, {"id": agent_id})
        self._append("requests", {**base, "status": status,
                                               "time": datetime.now().isoformat(timespec="seconds")})

    def _save(self, peers: dict) -> None:
        policy = Policy(owner=self._fresh_policy().owner, peers=peers)
        save_policy(self.policy_path, policy)
        self.policy, self._policy_stamp = policy, self._stamp()

    def accept_peer(self, agent_id: str, *, name: str, level: int = 1) -> PeerEntry:
        if self.connection() is None:
            raise PolicyError("Only a Tessera-facing agent accepts peers: its agent.yaml lists exactly one "
                              "compartment, not private (docs/08-connecting-agents.md)")
        entry = make_peer_entry(agent_id, name, level)
        self._save({**self._fresh_policy().peers, agent_id: entry})
        self._set_request_status(agent_id, "accepted")
        self.audit.log("tessera_peer_accepted", peer=agent_id, level=level)
        return entry

    def reject_request(self, agent_id: str) -> None:
        self._set_request_status(agent_id, "rejected")
        self.audit.log("tessera_request_rejected", peer=agent_id)

    def remove_peer(self, agent_id: str) -> None:
        peers = dict(self._fresh_policy().peers)
        if peers.pop(agent_id, None) is None:
            raise PolicyError(f"{agent_id} is not an accepted peer")
        self._save(peers)
        self._set_request_status(agent_id, "rejected")  # so a removed peer cannot queue itself again
        self.audit.log("tessera_peer_removed", peer=agent_id)

    def mark_public_session(self, peer: str, session_id: str) -> None:
        """Remembers that a session was opened in public mode, not by the owner's acceptance."""
        self._append("public", {"peer": peer, "session": session_id})

    def public_sessions(self) -> set[str]:
        return {f"{r.get('peer')}/{r.get('session')}" for r in self._read("public")}

    def record_envelope(self, other_id: str, session_id: str, envelope: dict) -> None:
        self._append(f"{other_id}/{session_id}", envelope)

    def read_record(self, other_id: str, session_id: str) -> list[dict]:
        return self._read(f"{other_id}/{session_id}")

    def _key(self) -> bytes:
        if self._record_key is None:
            if self.identity_dir is None:
                raise ValueError("This agent has no identity folder, so it can't keep Tessera records")
            self._record_key = load_record_key(self.identity_dir)
        return self._record_key

    def _append(self, name: str, record: dict) -> None:
        self.vault.append_tessera(name, seal_line(self._key(), name, record))

    def _read(self, name: str) -> list[dict]:
        lines = self.vault.read_tessera(name, strict="/" in name)  # session records: a damaged line is an error
        return [open_line(self._key(), name, line) for line in lines] if lines else []

    def record_names(self) -> list[str]:
        return [n for n in self.vault.tessera_names() if "/" in n]

    def seal_plain_records(self) -> int:
        """Records written before v0.2 are encrypted in place, once. Returns how many files changed."""
        changed = 0
        for name in self.vault.tessera_names():
            try:
                lines = self.vault.read_tessera(name, strict="/" in name)
            except ValueError as e:
                logging.getLogger(__name__).warning("Not encrypted, left as it was: %s", e)
                continue
            if lines and not all(is_sealed(line) for line in lines):
                self.vault.rewrite_tessera(name, [line if is_sealed(line) else seal_line(self._key(), name, line)
                                                  for line in lines])
                changed += 1
        return changed

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
