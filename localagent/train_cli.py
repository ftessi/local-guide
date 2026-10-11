"""`examples`, `train` and `export`: from source facts to an adapter, and from the internal agent to a
Tessera-facing one. Outside the layers: it reads the agent's config."""
import sys

from localagent.config import ConfigError
from localagent.protocol.guard import Protocol
from localagent.training.examples import InvalidSource, generate_examples


def protocol_for(config) -> Protocol:
    return Protocol.for_agent(config.agent_dir, config.compartments, tools={}, owner_secret="")


def compartment_arg(config, value: str | None, flag: str, command: str) -> str:
    if not value:
        raise ConfigError(f"'{command}' needs {flag} <compartment> (one of: {', '.join(config.compartments)})")
    if value not in config.compartments:
        raise ConfigError(f"'{value}' is not a compartment in agent.yaml (one of: {', '.join(config.compartments)})")
    return value


def make_examples(config, compartment: str, log=print) -> int:
    protocol = protocol_for(config)
    examples = generate_examples(compartment, protocol.training_sources(compartment))
    protocol.replace_training_examples(compartment, examples)
    log(f"{len(examples)} examples written to training/{compartment}/examples.jsonl")
    return len(examples)


def run(command: str, config, args, log=print) -> int:
    try:
        if command == "examples":
            make_examples(config, compartment_arg(config, args.compartment, "--compartment", command), log)
        else:
            raise ConfigError(f"Unknown command '{command}'")
    except (InvalidSource, ConfigError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    return 0
