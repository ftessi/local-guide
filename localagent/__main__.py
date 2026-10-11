"""python -m localagent {serve|chat} [--agent DIR]"""
import argparse
import logging
import sys

from localagent.agent.tools.registry import ToolConfigError
from localagent.config import ConfigError, load_config, resolve_agent_dir
from localagent.protocol.policy import PolicyError


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m localagent")
    parser.add_argument("command", choices=["serve", "chat"], help="serve = web/phone server, chat = terminal")
    parser.add_argument("--agent", help="agent folder (default: $LOCALAGENT_DIR or ./my-agent)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    try:
        config = load_config(resolve_agent_dir(args.agent))
        print(f"Agent '{config.name}' at {config.agent_dir}")
        print(f"Loading model {config.model.id} [{config.model.backend}, {config.model.quantization}]...")
        from localagent.bootstrap import build_services
        services = build_services(config)
    except (ConfigError, PolicyError, ToolConfigError, NotImplementedError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    if args.command == "chat":
        from localagent.connect.owner.terminal import run_terminal
        return run_terminal(services.protocol, services.agent, config.get_env("AGENT_SECRET"))

    import uvicorn
    from localagent.connect.owner.server import create_app
    app = create_app(protocol=services.protocol, agent=services.agent, push=services.push, tools=services.tools)
    print("Server ready.")
    uvicorn.run(app, host=config.host, port=config.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
