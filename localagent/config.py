"""Loads an agent folder (agent.yaml + installables.yaml + .env) into an AgentConfig."""
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import dotenv_values

from localagent.protocol.scopes import INTERNAL_COMPARTMENT

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_AGENT_DIR = REPO_ROOT / "my-agent"
QUANTIZATIONS = ("4bit", "fp16", "none")  # transformers backend
GGUF_QUANTIZATION_RE = re.compile(r"^(i?q\d[a-z0-9_]*|f16|bf16|f32)$")  # llamacpp backend: q4_k_m, q8_0...
COMPARTMENT_RE = re.compile(r"^[a-z][a-z0-9-]*$")
TOP_LEVEL_KEYS = {"name", "model", "compartments", "memory"}
EXTENSION_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
BUILTIN_CONNECTIONS = ("tessera",)  # connections whose code is part of LocalAgent: `builtin: true`, no source


class ConfigError(Exception):
    """The agent folder or agent.yaml is missing or invalid."""


@dataclass
class ModelConfig:
    id: str = "Qwen/Qwen2.5-3B-Instruct"
    backend: str = "llamacpp"
    quantization: str = "q4_k_m"
    max_new_tokens: int = 256
    max_prompt_chars: int = 8000
    gguf: str = ""        # llamacpp: HuggingFace repo with GGUF files (default: id + "-GGUF") or a .gguf file
    device: str = "auto"  # llamacpp: auto | cpu | a device from `llama-server --list-devices`


@dataclass
class Installables:
    """What the agent uses beyond the core, from installables.yaml. Listed = enabled.
    Each entry has `source:` (a folder or git URL with Tool/Connection code) or, for tools, `mcp:` (a command
    that runs an MCP server). Any "{agent}" in a value is replaced by the agent folder's path."""
    tools: dict[str, dict] = field(default_factory=dict)
    connections: dict[str, dict] = field(default_factory=dict)


@dataclass
class AgentConfig:
    agent_dir: Path
    name: str = "my-agent"
    model: ModelConfig = field(default_factory=ModelConfig)
    compartments: list[str] = field(default_factory=lambda: [INTERNAL_COMPARTMENT, "shared"])
    installables: Installables = field(default_factory=Installables)
    history_turns: int = 20
    env: dict[str, str] = field(default_factory=dict)

    def get_env(self, key: str, default: str = "") -> str:
        """Process environment first, then the agent's .env file."""
        return os.environ.get(key) or self.env.get(key) or default

    @property
    def tessera_facing(self) -> bool:
        """Serves one Tessera connection: exactly one compartment, not private. Nobody chats with it."""
        return len(self.compartments) == 1 and self.compartments[0] != INTERNAL_COMPARTMENT


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


def _expand(value, agent_dir: Path):
    if isinstance(value, str):
        return value.replace("{agent}", Path(agent_dir).resolve().as_posix())
    if isinstance(value, list):
        return [_expand(v, agent_dir) for v in value]
    if isinstance(value, dict):
        return {k: _expand(v, agent_dir) for k, v in value.items()}
    return value


def _extensions(raw, kind: str, agent_dir: Path) -> dict[str, dict]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError(f"'{kind}' in installables.yaml must map names to settings")
    where = "`source:` (a folder or git URL)" + (" or `mcp:` (a command that runs an MCP server)"
                                                 if kind == "tools" else "")
    result = {}
    for name, value in raw.items():
        if not isinstance(name, str) or not EXTENSION_NAME_RE.match(name):
            raise ConfigError(f"Invalid {kind[:-1]} name '{name}' in installables.yaml")
        builtin = kind == "connections" and isinstance(value, dict) and value.get("builtin") is True
        if builtin and name not in BUILTIN_CONNECTIONS:
            raise ConfigError(f"connections.{name}: there is no built-in connection called '{name}' "
                              f"(built-in: {', '.join(BUILTIN_CONNECTIONS)})")
        if not isinstance(value, dict) or not (builtin or value.get("source")
                                               or (kind == "tools" and value.get("mcp"))):
            raise ConfigError(f"{kind}.{name} in installables.yaml needs {where}")
        value = _expand(value, agent_dir)
        if isinstance(value.get("mcp"), str):
            value["mcp"] = value["mcp"].split()
        if "mcp" in value and not all(isinstance(a, str) for a in value["mcp"]):
            raise ConfigError(f"tools.{name}.mcp must be a command: a list of words, e.g. [npx, -y, some-server]")
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
    unknown = set(raw) - {"tools", "connections"}
    if unknown:
        raise ConfigError(f"Unknown setting(s) in installables.yaml: {', '.join(sorted(unknown))} "
                          "(only tools: and connections:; each entry has its own source: or mcp:)")
    return Installables(tools=_extensions(raw.get("tools"), "tools", agent_dir),
                        connections=_extensions(raw.get("connections"), "connections", agent_dir))


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
    if model.backend == "llamacpp":
        model.quantization = str(model.quantization).lower()
        if not GGUF_QUANTIZATION_RE.match(model.quantization):
            raise ConfigError("model.quantization for llamacpp is a GGUF quantization such as q4_k_m, q5_k_m or "
                              f"q8_0, got '{model.quantization}'")
    elif model.quantization not in QUANTIZATIONS:
        raise ConfigError(
            f"model.quantization must be one of {', '.join(QUANTIZATIONS)}, got '{model.quantization}'"
        )
    if not isinstance(model.max_new_tokens, int) or model.max_new_tokens <= 0:
        raise ConfigError("model.max_new_tokens must be a positive integer")
    if not isinstance(model.max_prompt_chars, int) or model.max_prompt_chars < 1000:
        raise ConfigError("model.max_prompt_chars must be an integer of at least 1000")

    compartments = raw.get("compartments", [INTERNAL_COMPARTMENT, "shared"])
    if not isinstance(compartments, list) or not compartments:
        raise ConfigError("'compartments' must be a non-empty list")
    for c in compartments:
        if not isinstance(c, str) or not COMPARTMENT_RE.match(c):
            raise ConfigError(f"Invalid compartment name '{c}': use lowercase letters, digits and '-'")
    if len(set(compartments)) != len(compartments):
        raise ConfigError("'compartments' contains a duplicate name")
    if INTERNAL_COMPARTMENT not in compartments and len(compartments) != 1:
        raise ConfigError("'compartments' must include 'private' (owner conversations are stored there). Only a "
                          "Tessera-facing agent, which serves one connection, lists a single other compartment.")

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
