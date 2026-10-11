"""The guard: opens sessions and builds training sets. The only owner of the vault."""
import hmac
from pathlib import Path

from localagent.protocol.audit import Audit
from localagent.protocol.policy import Policy, load_policy
from localagent.protocol.session import Session
from localagent.vault.store import Vault

OWNER_MEMORY = "private"


class AuthError(PermissionError):
    pass


class Protocol:
    def __init__(self, *, vault: Vault, policy: Policy, audit: Audit, tools: dict,
                 adapters_dir: Path, owner_secret: str):
        self.vault = vault
        self.policy = policy
        self.audit = audit
        self.tools = tools
        self.adapters_dir = Path(adapters_dir)
        self._owner_secret = owner_secret or ""

    @classmethod
    def for_agent(cls, agent_dir: Path, compartments: list[str], tools: dict, owner_secret: str) -> "Protocol":
        agent_dir = Path(agent_dir)
        return cls(vault=Vault(agent_dir, compartments), policy=load_policy(agent_dir / "policy.yaml"),
                   audit=Audit(agent_dir / "audit.log"), tools=tools,
                   adapters_dir=agent_dir / "training" / "adapters", owner_secret=owner_secret)

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

    def open_peer_session(self, request: dict) -> Session:
        raise NotImplementedError("Peer connections arrive with the peer protocol sub-project")

    def training_set(self, compartment: str) -> list[dict]:
        """Only examples labeled exactly `compartment`. Peer data is never included."""
        if compartment not in self.vault.compartments:
            raise ValueError(f"Training sets exist only for configured compartments "
                             f"{self.vault.compartments}, not '{compartment}'")
        return [i.content for i in self.vault.read("training", [compartment]) if i.compartment == compartment]
