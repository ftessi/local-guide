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


def train(config, compartment: str, *, device: str = "auto", epochs: int | None = None, log=print) -> dict:
    from localagent.config import ensure_hf_home
    from localagent.training import lora

    protocol = protocol_for(config)
    examples = protocol.training_set(compartment)
    if not examples:
        raise lora.TrainingError(f"training/{compartment}/examples.jsonl is empty or missing. "
                                 f"Run first: python -m localagent examples --compartment {compartment}")
    ensure_hf_home()
    out = protocol.adapter_path(config.model.id, compartment)
    log(f"Training adapter '{compartment}' on {len(examples)} examples with {config.model.id}...")
    info = lora.train_adapter(config.model.id, examples, out, compartment=compartment, device=device, log=log,
                              **({"epochs": epochs} if epochs else {}))
    log(f"Saved {out} (final loss {info['final_loss']})")
    return info


def run(command: str, config, args, log=print) -> int:
    from localagent.training.lora import TrainingError

    try:
        if command == "examples":
            make_examples(config, compartment_arg(config, args.compartment, "--compartment", command), log)
        elif command == "train":
            train(config, compartment_arg(config, args.adapter, "--adapter", command), device=args.device,
                  epochs=args.epochs, log=log)
        else:
            raise ConfigError(f"Unknown command '{command}'")
    except (InvalidSource, TrainingError, ConfigError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    return 0
