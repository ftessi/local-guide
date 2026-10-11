"""What a connection is. Connections (phone app, tunnel, agent network…) are installables, not part of the core:
their code lives in the extensions repo and is listed in the agent's installables.yaml."""
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)


class SetupError(Exception):
    """A connection can't run (missing program, bad setting...). The message is shown to the user as is."""


class Notifier:
    """How tools reach the owner. Connections add channels (e.g. phone push); tools call it."""

    def __init__(self):
        self._channels: list[Callable[[str, str], None]] = []

    def add(self, channel: Callable[[str, str], None]) -> None:
        self._channels.append(channel)

    def __call__(self, title: str, body: str) -> None:
        if not self._channels:
            log.info("No notification channel installed. %s: %s", title, body)
        for channel in self._channels:
            try:
                channel(title, body)
            except Exception:
                log.exception("Notification channel failed")


@dataclass
class ConnectionContext:
    """Everything a connection may use. It reaches the agent only through protocol sessions."""
    config: object                      # localagent.config.AgentConfig
    protocol: object                    # localagent.protocol.guard.Protocol
    agent: object                       # localagent.agent.core.Agent
    tools: dict
    notifier: Notifier
    settings: dict = field(default_factory=dict)  # this connection's block in installables.yaml
    data_dir: Path = Path(".")          # <agent>/data/<connection name>/, created for it


class Connection:
    name: str = ""
    options: tuple = ()  # setting names accepted in installables.yaml; anything else is a typo

    def setup(self, ctx: ConnectionContext) -> None:
        """Called once after the model is loaded. Read settings, prepare, add notification channels.
        Raise SetupError with a helpful message if the connection can't run."""

    def start(self) -> None:
        """Start serving without blocking (thread or subprocess). Called by `python -m localagent serve`."""

    def stop(self) -> None:
        """Stop what start() started. Called on Ctrl+C."""
