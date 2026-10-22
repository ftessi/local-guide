"""python -m localagent {chat|serve|install|list} [--agent DIR]"""
import argparse
import logging
import sys

from localagent.config import ConfigError, load_config, resolve_agent_dir
from localagent.connect.base import SetupError
from localagent.extensions import ExtensionError
from localagent.protocol.policy import PolicyError

COMMANDS = {
    "chat": "talk to your agent in this terminal",
    "serve": "start the connections in installables.yaml (phone app, tunnel...) and run reminders",
    "install": "download/update the tools and connections listed in installables.yaml",
    "list": "show the available tools and connections, and which ones this agent uses",
    "examples": "turn training/<compartment>/sources/*.yaml into training examples (--compartment)",
    "train": "train one compartment's LoRA adapter (--adapter; optional --device, --epochs). Stop the agent first",
    "export": "copy a connection's adapter to the Tessera-facing agent (--adapter, --to). Never the private one",
    "id": "show this agent's id, to give to another agent's owner",
    "peers": "list accepted agents and connection requests; peers accept|reject|remove <id>",
    "connect": 'save another agent to ask: connect <address> <their id> --name <name> --purpose "<why>"',
    "ask": 'ask a connected agent one question over Tessera: ask <name> "<question>"',
    "records": "show this agent's Tessera records, decrypted: records | records show|verify <session> | "
               "records export <session> --to <file>",
    "inspection": "send this agent's finished conversations to the relay operator for security analysis: "
                  "inspection | inspection on [--relay URL] | inspection off",
    "inspect": "for the relay operator: open an inspection upload (inspect <file> --key <private key> [--delete])",
    "relay": "run a Tessera relay that agents connect out to (--host, --port, --max-agents, --public-url)",
}


def main(argv=None) -> int:
    from localagent.protocol.identity import AGENT_ID_RE
    argv = list(sys.argv[1:] if argv is None else argv)
    argv = [f"id:{a}" if a.startswith("-") and AGENT_ID_RE.fullmatch(a) else a for a in argv]
    parser = argparse.ArgumentParser(prog="python -m localagent",
                                     formatter_class=argparse.RawDescriptionHelpFormatter,
                                     epilog="\n".join(f"  {c:<8} {h}" for c, h in COMMANDS.items()))
    parser.add_argument("command", choices=list(COMMANDS))
    parser.add_argument("--agent", help="agent folder (default: $LOCALAGENT_DIR or ./my-agent)")
    parser.add_argument("--compartment", help="examples: which compartment's sources to use")
    parser.add_argument("--adapter", help="train/export: which compartment's adapter")
    parser.add_argument("--device", choices=["auto", "cuda", "cpu"], default="auto", help="train: where to train")
    parser.add_argument("--epochs", type=int, help="train: passes over the examples (default 8)")
    parser.add_argument("--to", help="export: the destination agent folder")
    parser.add_argument("rest", nargs="*", help="peers/connect/ask: their arguments")
    parser.add_argument("--name", help="peers accept / connect: a name for the other agent")
    parser.add_argument("--level", type=int, default=1, help="peers accept: Tessera level (only 1 = Ask for now)")
    parser.add_argument("--purpose", help="connect: why you're connecting (shown to their owner)")
    parser.add_argument("--relay", help="inspection on: the relay that receives uploads")
    parser.add_argument("--key", help="inspect: the company's private key file")
    parser.add_argument("--delete", action="store_true", help="inspect: remove the upload afterwards")
    parser.add_argument("--host", default="127.0.0.1", help="relay: address to listen on (0.0.0.0 = every network)")
    parser.add_argument("--port", type=int, default=8200, help="relay: port to listen on")
    parser.add_argument("--max-agents", type=int, default=100, help="relay: most agents connected at once")
    parser.add_argument("--public-url", help="relay: the address agents and askers use, e.g. https://relay.example.com")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if args.command == "inspect":
        from localagent.tessera_cli import inspect_file
        if len(args.rest) != 1 or not args.key:
            print("Error: use: inspect <file> --key <private key file> [--delete]", file=sys.stderr)
            return 2
        return inspect_file(args.rest[0], args.key, args.delete)
    if args.command == "relay":
        from localagent.relay.http import run_relay
        return run_relay(args.host, args.port, args.max_agents, args.public_url)

    try:
        config = load_config(resolve_agent_dir(args.agent))
        if args.command in ("examples", "train", "export"):
            from localagent import train_cli
            return train_cli.run(args.command, config, args)
        if args.command in ("id", "peers", "connect", "ask", "records", "inspection"):
            from localagent import tessera_cli
            return tessera_cli.run(args.command, config, args)
        if args.command in ("install", "list"):
            from localagent.installer import describe, install
            if args.command == "list":
                print(describe(config))
                return 0
            return install(config)

        if args.command == "chat" and config.tessera_facing:
            print(f"Error: {config.agent_dir.name} is a Tessera-facing agent (compartments: {config.compartments}): "
                  "it only answers other agents. Chat with your internal agent instead.", file=sys.stderr)
            return 2
        if args.command == "serve" and config.tessera_facing and set(config.installables.connections) != {"tessera"}:
            print(f"Error: {config.agent_dir.name} is a Tessera-facing agent: serve runs only its tessera connection "
                  f"(installables.yaml lists {sorted(config.installables.connections)})", file=sys.stderr)
            return 2
        if args.command == "serve" and config.tessera_facing:  # before the model loads, which takes minutes
            from localagent.connect.peer.tessera import check_tessera_folder, missing_adapter
            problems = check_tessera_folder(config) + ([missing_adapter(config)] if missing_adapter(config) else [])
            if problems:
                print("Error: this agent folder can't face other agents:\n- " + "\n- ".join(problems),
                      file=sys.stderr)
                return 2
        print(f"Agent '{config.name}' at {config.agent_dir}")
        if args.command == "serve" and not config.installables.connections:
            print("Error: installables.yaml lists no connections, so there is nothing to serve.\n"
                  "Add one (e.g. phone) and run `python -m localagent install`, or use `chat`.", file=sys.stderr)
            return 2
        print(f"Loading model {config.model.id} [{config.model.backend}, {config.model.quantization}]...")
        from localagent.bootstrap import build_services
        services = build_services(config, with_connections=args.command == "serve")
    except (ConfigError, PolicyError, ExtensionError, SetupError, NotImplementedError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    if args.command == "chat":
        from localagent.connect.owner.terminal import run_terminal
        from localagent.tessera_cli import make_asker, send_inspection_quietly
        code = run_terminal(services.protocol, services.agent, config.get_env("AGENT_SECRET"),
                            ask=make_asker(config))
        send_inspection_quietly(config)
        return code

    from localagent.connect.serve import serve
    return serve(services.connections, services.tools)


if __name__ == "__main__":
    sys.exit(main())
