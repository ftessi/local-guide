"""Wires the layers together for one agent folder. Not a layer itself."""
from dataclasses import dataclass
from pathlib import Path

from localagent.agent.core import Agent
from localagent.agent.tools.registry import load_tools
from localagent.config import AgentConfig, ensure_hf_home
from localagent.connect.owner.push import PushDispatcher
from localagent.protocol.guard import Protocol
from localagent.runtime.base import Backend
from localagent.runtime.factory import create_backend


@dataclass
class Services:
    config: AgentConfig
    backend: Backend
    protocol: Protocol
    agent: Agent
    tools: dict
    push: PushDispatcher


def _resolve_key(value: str, agent_dir: Path) -> str:
    """VAPID_PRIVATE_KEY may be a path relative to the agent folder."""
    if value and not Path(value).is_absolute() and (agent_dir / value).is_file():
        return str(agent_dir / value)
    return value


def build_services(config: AgentConfig, backend: Backend | None = None) -> Services:
    push = PushDispatcher(
        subs_path=config.agent_dir / "data" / "push_subscriptions.json",
        private_key=_resolve_key(config.get_env("VAPID_PRIVATE_KEY"), config.agent_dir),
        public_key=config.get_env("VAPID_PUBLIC_KEY"),
        claims_email=config.get_env("VAPID_CLAIMS_EMAIL", "admin@localhost"),
    )
    tools = load_tools(config.tools, config.agent_dir / "data", push.send, config.compartments)
    protocol = Protocol.for_agent(config.agent_dir, config.compartments, tools,
                                  owner_secret=config.get_env("AGENT_SECRET"))
    if backend is None:  # load the model last: config errors above surface in seconds, not minutes
        ensure_hf_home()
        backend = create_backend(config.model.backend)
        backend.load(config.model.id, config.model.quantization)
    agent = Agent(backend, tools, model_id=config.model.id, max_new_tokens=config.model.max_new_tokens,
                  history_turns=config.history_turns)
    return Services(config, backend, protocol, agent, tools, push)
