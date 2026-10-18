"""Wires the layers and the installed extensions together for one agent folder. Not a layer itself."""
from dataclasses import dataclass, field

from localagent.agent.core import Agent
from localagent.config import AgentConfig, ensure_hf_home
from localagent.connect.base import Notifier
from localagent.extensions import load_connections, load_tools, setup_connections
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
    notifier: Notifier
    connections: dict = field(default_factory=dict)


def build_services(config: AgentConfig, backend: Backend | None = None, *,
                   with_connections: bool = True) -> Services:
    data_root = config.agent_dir / "data"
    notifier = Notifier()
    tools = load_tools(config.installables.tools, config.agent_dir, data_root, notifier, config.compartments)
    connections = load_connections(config.installables.connections, config.agent_dir) if with_connections else {}
    protocol = Protocol.for_agent(config.agent_dir, config.compartments, tools,
                                  owner_secret=config.get_env("AGENT_SECRET"))
    if backend is None:  # load the model last: config and extension errors above surface in seconds, not minutes
        ensure_hf_home()
        backend = create_backend(config.model.backend, config.model)
        backend.load(config.model.id, config.model.quantization)
    agent = Agent(backend, tools, model_id=config.model.id, max_new_tokens=config.model.max_new_tokens,
                  max_prompt_chars=config.model.max_prompt_chars,
                  history_turns=config.history_turns)
    setup_connections(connections, config.installables.connections, data_root, config=config,
                      protocol=protocol, agent=agent, tools=tools, notifier=notifier)
    return Services(config, backend, protocol, agent, tools, notifier, connections)
