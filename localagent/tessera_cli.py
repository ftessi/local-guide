"""Tessera commands: id, peers, connect, ask. Outside the layers: reads the agent's config and files."""
import re
import sys
from pathlib import Path

import yaml

from localagent.config import ConfigError
from localagent.connect.peer.tessera.client import Reply, TesseraClient
from localagent.protocol.guard import Protocol
from localagent.protocol.identity import AGENT_ID_RE, load_agent_id, load_identity
from localagent.protocol.policy import PolicyError
from localagent.protocol.prompts import REFUSAL

REMOTE_NAME = re.compile(r"^[a-z][a-z0-9_-]*$")
ID_MARK = "id:"  # __main__ marks agent ids starting with "-" so argparse doesn't take them for options


def _id(value: str) -> str:
    return value[len(ID_MARK):] if value.startswith(ID_MARK) else value


def protocol_for(config) -> Protocol:
    return Protocol.for_agent(config.agent_dir, config.compartments, tools={}, owner_secret="")


def _remotes_path(config) -> Path:
    return Path(config.agent_dir) / "tessera" / "remotes.yaml"


def _remotes(config) -> dict:
    path = _remotes_path(config)
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}) if path.is_file() else {}


def describe_reply(name: str, reply: Reply) -> str:
    if reply.kind == "answer":
        return f"{name}: {reply.text}"
    if reply.kind == "decline":
        return f"{name} declined: {REFUSAL}"
    if reply.kind == "not_connected":
        return f"Not connected: {name} hasn't accepted this agent (or isn't reachable)."
    return f"Error talking to {name}: {reply.text}"


def make_asker(config):
    """For /ask in chat: one client per remote, so a session is reused across questions."""
    clients = {}

    def ask(name: str, question: str) -> str:
        if name not in clients:
            remote = _remotes(config).get(name)
            if not remote:
                return f"Unknown remote '{name}'. Add it with: python -m localagent connect <address> <id> --name {name}"
            clients[name] = TesseraClient(load_identity(Path(config.agent_dir) / "identity"), protocol_for(config),
                                          remote_id=remote["id"], address=remote["address"],
                                          purpose=remote.get("purpose", ""))
        return describe_reply(name, clients[name].ask(question))

    return ask


def _peers(config, rest: list[str], args, log) -> int:
    p = protocol_for(config)
    if not rest:
        log("Accepted:")
        for agent_id, e in p.policy.peers.items():
            log(f"  {e.name}  {agent_id}  level={e.level}")
        if not p.policy.peers:
            log("  (none)")
        log("Waiting for your answer:")
        for r in p.requests():
            log(f"  {r['id']}  level {r['level']}  {r['time']}  purpose: {r['purpose']}")
        if not p.requests():
            log("  (none)")
        log("Accept: python -m localagent peers accept <id> --name <name>")
        return 0
    action, agent_id = rest[0], _id(rest[1]) if len(rest) > 1 else ""
    if action not in ("accept", "reject", "remove") or not agent_id:
        raise ConfigError("Use: peers | peers accept <id> --name … | peers reject <id> | peers remove <id>")
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
    address, agent_id = rest[0], _id(rest[1])
    if not AGENT_ID_RE.fullmatch(agent_id):
        raise ConfigError(f"'{agent_id}' is not an agent id (43 characters, from their `python -m localagent id`)")
    if not REMOTE_NAME.match(args.name):
        raise ConfigError("--name: lowercase letters, digits, '-' or '_'")
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
    if name not in _remotes(config):
        raise ConfigError(f"Unknown remote '{name}'. Add it first: python -m localagent connect <address> <id> "
                          f"--name {name} --purpose \"…\"")
    text = make_asker(config)(name, question)
    log(text)
    return 0 if not text.startswith(("Not connected", "Error")) else 1


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
    except (ConfigError, PolicyError, ValueError, FileNotFoundError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
