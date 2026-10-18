"""Tessera commands: id, peers, connect, ask. Outside the layers: reads the agent's config and files."""
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import yaml

from localagent.config import ConfigError
from localagent.connect.peer.tessera.client import Reply, TesseraClient
from localagent.protocol.guard import Protocol
from localagent.protocol.identity import AGENT_ID_RE, load_agent_id, load_identity
from localagent.protocol.policy import PolicyError
from localagent.protocol.prompts import REFUSAL

REMOTE_NAME = re.compile(r"[a-z][a-z0-9_-]*")
PURPOSE_MAX = 200
ID_MARK = "id:"  # __main__ marks agent ids starting with "-" so argparse doesn't take them for options


def _id(value: str) -> str:
    return value[len(ID_MARK):] if value.startswith(ID_MARK) else value


def _checked_id(value: str) -> str:
    agent_id = _id(value)
    if not AGENT_ID_RE.fullmatch(agent_id):
        raise ConfigError(f"'{agent_id}' is not an agent id (43 characters, from their `python -m localagent id`)")
    return agent_id


def protocol_for(config) -> Protocol:
    return Protocol.for_agent(config.agent_dir, config.compartments, tools={}, owner_secret="")


def _remotes_path(config) -> Path:
    return Path(config.agent_dir) / "tessera" / "remotes.yaml"


def _remotes(config) -> dict:
    path = _remotes_path(config)
    if not path.is_file():
        return {}
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError, ValueError) as e:
        raise ConfigError(f"{path} is not readable: {e}") from e
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} must be a mapping of names to {{address, id, purpose}}")
    return raw


def _remote(config, name: str) -> dict:
    entry = _remotes(config).get(name)
    if entry is None:
        raise ConfigError(f"Unknown remote '{name}'. Add it first: python -m localagent connect <address> <id> "
                          f"--name {name} --purpose \"…\"")
    if (not isinstance(entry, dict) or not isinstance(entry.get("address"), str)
            or not isinstance(entry.get("id"), str) or not AGENT_ID_RE.fullmatch(entry["id"])):
        raise ConfigError(f"{_remotes_path(config)}: '{name}' needs string fields address and id "
                          "(id: 43 characters, from their `python -m localagent id`)")
    purpose = entry.get("purpose", "")
    if not isinstance(purpose, str) or len(purpose) > PURPOSE_MAX:
        raise ConfigError(f"{_remotes_path(config)}: '{name}' has a bad purpose "
                          f"(text, at most {PURPOSE_MAX} characters)")
    return entry


def _identity(config):
    identity_dir = Path(config.agent_dir) / "identity"
    if not (identity_dir / "agent.key").is_file():
        raise ConfigError(f"{identity_dir} has no agent.key, so this agent has no identity "
                          "(agents created with scripts/new_agent.py have one)")
    return load_identity(identity_dir)


def _safe(text) -> str:
    """Text from another agent, made safe for the owner's terminal: control and format characters (escape
    sequences, carriage returns, bidi marks) are shown as visible escapes. Newlines stay."""
    out = []
    for ch in str(text):
        if ch != "\n" and unicodedata.category(ch) in ("Cc", "Cf"):
            out.append(repr(ch)[1:-1])  # a visible escape such as x1b or r
        else:
            out.append(ch)
    return "".join(out)


def describe_reply(name: str, reply: Reply) -> str:
    """Peer text is always labelled with its origin: every line of an answer is indented under the label."""
    if reply.kind == "answer":
        body = "\n".join("  " + line for line in (_safe(reply.text).splitlines() or [""]))
        return f"{name} says:\n{body}"
    if reply.kind == "decline":
        return f"{name} declined: {REFUSAL}"
    if reply.kind == "not_connected":
        return f"Not connected: {name} hasn't accepted this agent (or isn't reachable)."
    return f"Error talking to {name}: {_safe(reply.text)}"


@dataclass
class Answer:
    text: str
    reply: Reply


class Asker:
    """Asks connected agents over Tessera. One client per remote, so a session is reused across questions;
    close_all() ends them (chat calls it on exit)."""

    def __init__(self, config):
        self._config = config
        self._clients = {}

    def ask(self, name: str, question: str) -> Answer:
        """Raises ConfigError (or PolicyError/OSError) for a setup problem. A failed exchange is a Reply."""
        if name not in self._clients:
            remote = _remote(self._config, name)
            self._clients[name] = TesseraClient(_identity(self._config), protocol_for(self._config),
                                                remote_id=remote["id"], address=remote["address"],
                                                purpose=remote.get("purpose", ""))
        reply = self._clients[name].ask(question)
        return Answer(describe_reply(name, reply), reply)

    def __call__(self, name: str, question: str) -> str:
        """For chat: a setup problem comes back as text, so /ask never ends the chat."""
        try:
            return self.ask(name, question).text
        except (ConfigError, OSError, ValueError) as e:
            return f"Error: {e}"

    def session(self, name: str) -> str | None:
        """The Tessera session of the latest exchange with `name`: chat's /talk notices when it changes."""
        client = self._clients.get(name)
        return client.session_id if client else None

    def check(self, name: str) -> str:
        """'' if `name` is a saved remote, otherwise the problem as text (for chat's /talk)."""
        try:
            _remote(self._config, name)
        except ConfigError as e:
            return f"Error: {e}"
        return ""

    def close_all(self) -> None:
        for client in self._clients.values():
            try:
                client.close()
            except (OSError, ValueError):
                pass
        self._clients.clear()


def make_asker(config) -> Asker:
    return Asker(config)


def _peers(config, rest: list[str], args, log) -> int:
    p = protocol_for(config)
    if not rest:
        log("Accepted:")
        for agent_id, e in p.policy.peers.items():
            log(f"  {_safe(e.name)}  {_safe(agent_id)}  level={e.level}")
        if not p.policy.peers:
            log("  (none)")
        log("Waiting for your answer:")
        requests = p.requests()
        for r in requests:
            log(f"  {_safe(r['id'])}  level {_safe(r['level'])}  {_safe(r['time'])}  purpose: {_safe(r['purpose'])}")
        if not requests:
            log("  (none)")
        log("Accept: python -m localagent peers accept <id> --name <name>")
        return 0
    if len(rest) != 2 or rest[0] not in ("accept", "reject", "remove"):
        raise ConfigError("Use: peers | peers accept <id> --name … | peers reject <id> | peers remove <id>")
    action, agent_id = rest[0], _checked_id(rest[1])
    if action == "accept":
        if not args.name:
            raise ConfigError("'peers accept' needs --name (a name for the other agent)")
        e = p.accept_peer(agent_id, name=args.name, level=args.level)
        log(f"Accepted {e.name} for connection '{p.connection()}', level {e.level}.")
    elif action == "reject":
        p.reject_request(agent_id)
        log("Rejected. That agent will keep getting a plain refusal.")
    else:
        p.remove_peer(agent_id)
        log("Removed. Its open sessions stop at its next question.")
    return 0


def _connect(config, rest: list[str], args, log) -> int:
    if len(rest) != 2 or not args.name or not args.purpose:
        raise ConfigError('Use: connect <address> <their agent id> --name <name> --purpose "<why>"')
    address, agent_id = rest[0], _checked_id(rest[1])
    if not REMOTE_NAME.fullmatch(args.name):
        raise ConfigError("--name: lowercase letters, digits, '-' or '_'")
    if len(args.purpose) > PURPOSE_MAX:
        raise ConfigError(f"--purpose: at most {PURPOSE_MAX} characters")
    remotes = _remotes(config)
    remotes[args.name] = {"address": address, "id": agent_id, "purpose": args.purpose}
    path = _remotes_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(remotes, sort_keys=True, allow_unicode=True), encoding="utf-8")
    log(f"Saved '{args.name}'. Ask with: python -m localagent ask {args.name} \"<question>\"")
    return 0


def _ask(config, rest: list[str], log) -> int:
    if len(rest) < 2:
        raise ConfigError('Use: ask <name> "<question>"')
    name, question = rest[0], " ".join(rest[1:])
    asker = make_asker(config)
    try:
        answer = asker.ask(name, question)
    finally:
        asker.close_all()
    log(answer.text)
    return 0 if answer.reply.kind in ("answer", "decline") else 1


def run(command: str, config, args, log=print) -> int:
    try:
        if command == "id":
            agent_id = load_agent_id(Path(config.agent_dir) / "identity")
            if not agent_id:
                raise ConfigError(f"{config.agent_dir} has no identity/agent.pub "
                                  "(agents created with scripts/new_agent.py have one)")
            log(agent_id)
            return 0
        if command == "peers":
            return _peers(config, args.rest, args, log)
        if command == "connect":
            return _connect(config, args.rest, args, log)
        return _ask(config, args.rest, log)
    except (ConfigError, PolicyError, ValueError, OSError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
