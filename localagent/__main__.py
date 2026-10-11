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
}


def main(argv=None) -> int:
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
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    try:
        config = load_config(resolve_agent_dir(args.agent))
        if args.command in ("examples", "train", "export"):
            from localagent import train_cli
            return train_cli.run(args.command, config, args)
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
        return run_terminal(services.protocol, services.agent, config.get_env("AGENT_SECRET"))

    from localagent.connect.serve import serve
    return serve(services.connections, services.tools)


if __name__ == "__main__":
    sys.exit(main())
