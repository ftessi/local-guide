"""Loads an agent folder (agent.yaml + installables.yaml + .env) into an AgentConfig."""
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import dotenv_values

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_AGENT_DIR = REPO_ROOT / "my-agent"
QUANTIZATIONS = ("4bit", "fp16", "none")
COMPARTMENT_RE = re.compile(r"^[a-z][a-z0-9-]*$")
TOP_LEVEL_KEYS = {"name", "model", "compartments", "memory"}
EXTENSION_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
DEFAULT_EXTENSIONS_SOURCE = "https://github.com/ftessi/local-guide-extensions.git"


class ConfigError(Exception):
    """The agent folder or agent.yaml is missing or invalid."""


@dataclass
class ModelConfig:
    id: str = "Qwen/Qwen2.5-3B-Instruct"
    backend: str = "transformers"
    quantization: str = "4bit"
    max_new_tokens: int = 256


@dataclass
class Installables:
    """What the agent uses beyond the core, from installables.yaml. Presence in the file = enabled."""
    source: str = DEFAULT_EXTENSIONS_SOURCE  # git URL, or a local folder (relative to the agent folder)
    ref: str = "main"
    tools: dict[str, dict] = field(default_factory=dict)
    connections: dict[str, dict] = field(default_factory=dict)


@dataclass
class AgentConfig:
    agent_dir: Path
    name: str = "my-agent"
    model: ModelConfig = field(default_factory=ModelConfig)
    compartments: list[str] = field(default_factory=lambda: ["private", "shared"])
    installables: Installables = field(default_factory=Installables)
    history_turns: int = 20
    env: dict[str, str] = field(default_factory=dict)

    def get_env(self, key: str, default: str = "") -> str:
        """Process environment first, then the agent's .env file."""
        return os.environ.get(key) or self.env.get(key) or default


def ensure_hf_home() -> None:
    os.environ.setdefault("HF_HOME", str(REPO_ROOT / "models"))


def resolve_agent_dir(cli_value: str | None) -> Path:
    value = cli_value or os.getenv("LOCALAGENT_DIR")
    path = Path(value).expanduser().resolve() if value else DEFAULT_AGENT_DIR
    if not (path / "agent.yaml").is_file():
        raise ConfigError(
            f"No agent found at {path} (agent.yaml is missing).\n"
            f"Create one with:  python scripts/new_agent.py --agent \"{path}\""
        )
    return path


def _section(raw: dict, key: str) -> dict:
    value = raw.get(key) or {}
    if not isinstance(value, dict):
        raise ConfigError(f"'{key}' in agent.yaml must be a mapping")
    return value


def _extensions(raw, kind: str) -> dict[str, dict]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError(f"'{kind}' in installables.yaml must map names to settings")
    result = {}
    for name, value in raw.items():
        if not isinstance(name, str) or not EXTENSION_NAME_RE.match(name):
            raise ConfigError(f"Invalid {kind[:-1]} name '{name}' in installables.yaml")
        if value is None:
            value = {}
        if not isinstance(value, dict):
            raise ConfigError(f"{kind}.{name} in installables.yaml must be a mapping of settings (or empty)")
        result[name] = value
    return result


def load_installables(agent_dir: Path) -> Installables:
    path = Path(agent_dir) / "installables.yaml"
    if not path.is_file():
        return Installables()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise ConfigError(f"installables.yaml is not valid YAML: {e}") from e
    if not isinstance(raw, dict):
        raise ConfigError("installables.yaml must be a mapping of settings")
    unknown = set(raw) - {"source", "ref", "tools", "connections"}
    if unknown:
        raise ConfigError(f"Unknown setting(s) in installables.yaml: {', '.join(sorted(unknown))}")
    return Installables(source=str(raw.get("source") or DEFAULT_EXTENSIONS_SOURCE),
                        ref=str(raw.get("ref") or "main"),
                        tools=_extensions(raw.get("tools"), "tools"),
                        connections=_extensions(raw.get("connections"), "connections"))


def load_config(agent_dir: Path) -> AgentConfig:
    agent_dir = Path(agent_dir)
    try:
        raw = yaml.safe_load((agent_dir / "agent.yaml").read_text(encoding="utf-8")) or {}
    except FileNotFoundError as e:
        raise ConfigError(f"{agent_dir / 'agent.yaml'} does not exist") from e
    except yaml.YAMLError as e:
        raise ConfigError(f"agent.yaml is not valid YAML: {e}") from e
    if not isinstance(raw, dict):
        raise ConfigError("agent.yaml must be a mapping of settings")
    moved = {"tools", "server"} & set(raw)
    if moved:
        raise ConfigError(f"'{', '.join(sorted(moved))}' moved from agent.yaml to installables.yaml "
                          "(tools: and connections: phone: host/port). See README.md.")
    unknown = set(raw) - TOP_LEVEL_KEYS
    if unknown:
        raise ConfigError(f"Unknown setting(s) in agent.yaml: {', '.join(sorted(unknown))}")

    model_raw = _section(raw, "model")
    unknown = set(model_raw) - set(ModelConfig.__dataclass_fields__)
    if unknown:
        raise ConfigError(f"Unknown model setting(s): {', '.join(sorted(unknown))}")
    model = ModelConfig(**model_raw)
    if model.quantization not in QUANTIZATIONS:
        raise ConfigError(
            f"model.quantization must be one of {', '.join(QUANTIZATIONS)}, got '{model.quantization}'"
        )
    if not isinstance(model.max_new_tokens, int) or model.max_new_tokens <= 0:
        raise ConfigError("model.max_new_tokens must be a positive integer")

    compartments = raw.get("compartments", ["private", "shared"])
    if not isinstance(compartments, list) or not compartments:
        raise ConfigError("'compartments' must be a non-empty list")
    for c in compartments:
        if not isinstance(c, str) or not COMPARTMENT_RE.match(c):
            raise ConfigError(f"Invalid compartment name '{c}': use lowercase letters, digits and '-'")
    if len(set(compartments)) != len(compartments):
        raise ConfigError("'compartments' contains a duplicate name")
    if "private" not in compartments:
        raise ConfigError("'compartments' must include 'private' (owner conversations are stored there)")

    memory = _section(raw, "memory")
    env = {k: v for k, v in dotenv_values(agent_dir / ".env").items() if v is not None}
    return AgentConfig(
        agent_dir=agent_dir,
        name=str(raw.get("name") or agent_dir.name),
        model=model,
        compartments=list(compartments),
        installables=load_installables(agent_dir),
        history_turns=int(memory.get("history_turns", 20)),
        env=env,
    )
