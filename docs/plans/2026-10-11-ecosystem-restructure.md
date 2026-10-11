# Ecosystem Restructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reshape the repo into a layered `localagent` package (runtime → vault → protocol guard → agent/training → connect), with each person's data in a gitignored agent folder, and keep the current chat, calendar, push and phone app working.

**Architecture:** Six layer packages with one-way imports, enforced by a test. `protocol` is the only layer that reads `vault`; `agent` gets data only through a `Session`. Composition lives outside the layers in `localagent/bootstrap.py` and `localagent/__main__.py`. Agent folders are created from `agent_template/` by `localagent/setup_agent.py`, which the `new_agent.py` and `migrate_legacy.py` scripts call.

**Tech Stack:** Python 3.10, FastAPI, APScheduler 3, pywebpush, HF Transformers + bitsandbytes (+ optional peft), PyYAML, cryptography, pytest.

**Spec:** `docs/design/2026-10-11-ecosystem-restructure-design.md`

## Global Constraints

- Python 3.10 (`X | None` is fine; no `match`-only features required).
- The owner asked for **no commits**: every "Commit" step is replaced by "leave the change uncommitted". Don't stage files.
- Plans/specs go to `docs/plans/` and `docs/design/`, never `docs/superpowers/`.
- No test loads real model weights; the model is always a `FakeBackend`.
- Allowed imports between layers (spec §2): runtime → none; vault → none; protocol → vault; agent → `protocol.session`, `runtime.base` only; training → protocol, runtime; connect → protocol, agent, runtime.
- Compartment names: `^[a-z][a-z0-9-]*$`, must include `private`. Peer compartments are `peer:<agent-id>` and are stored on disk as folder `peer__<agent-id>`.
- Quantization values: `4bit | fp16 | none`. Backends: `transformers` implemented; `llamacpp`, `mlx` raise `NotImplementedError`.
- The PWA's WebSocket protocol is unchanged: `{"type":"chunk","text":...}` then `{"type":"done"}`.

## Review Focus

1. The model's reply gets cut off by `max_new_tokens` in the middle of a `<tool>` tag. The half tag must not be shown to the user and must not be executed. *(Task 6: `test_unterminated_tag_*`)*
2. The model writes `remind_at` with a timezone (`...Z`, `+02:00`) or as a date only. It must be stored as local, naive `YYYY-MM-DDTHH:MM:SS`, or else it never fires or fires at the wrong time. *(Task 5: `test_iso_datetime_*`)*
3. A crash leaves a half-written line in a memory `.jsonl` file. The agent must still start and chat, skipping that line. *(Task 3: `test_corrupt_memory_line_skipped`)*
4. `AGENT_SECRET` is empty or missing. Every owner session must be refused; the current code accepts an empty token. *(Task 4: `test_empty_secret_refuses_everyone`)*
5. The agent folder is missing or `agent.yaml` is malformed. The user must get a clear message telling them what to run or fix, not a traceback. *(Task 1: `test_missing_agent_dir_message`, `test_bad_yaml_message`)*

---

## File map

| File | Responsibility |
|---|---|
| `localagent/config.py` | `AgentConfig`, `load_config`, `resolve_agent_dir`, `ensure_hf_home` |
| `localagent/runtime/base.py` | `Backend` protocol, `AdapterLoadError` |
| `localagent/runtime/transformers_backend.py` | HF backend incl. LoRA adapters via peft |
| `localagent/runtime/factory.py` | `create_backend`, `AVAILABLE_BACKENDS` |
| `localagent/runtime/hardware.py` | `detect`, `recommend` |
| `localagent/vault/store.py` | `Vault`, `Item` |
| `localagent/protocol/scopes.py` | `Scope`, `InvalidScope` |
| `localagent/protocol/policy.py` | `Policy`, `load_policy`, `PolicyError` |
| `localagent/protocol/audit.py` | `Audit` |
| `localagent/protocol/identity.py` | `generate_identity`, `load_agent_id` |
| `localagent/protocol/session.py` | `Session`, `ToolView`, `ScopeError`, `UnknownToolError`, `WITHHELD`, `model_slug` |
| `localagent/protocol/guard.py` | `Protocol`, `AuthError` |
| `localagent/protocol/handshake.py` | peer handshake stub |
| `localagent/agent/tools/base.py` | `Tool`, `Action`, `validate_args`, `ToolArgsError` |
| `localagent/agent/tools/registry.py` | `load_tools`, `ToolConfigError` |
| `localagent/agent/tools/calendar/` | `CalendarTool` |
| `localagent/agent/toolcalls.py` | `ToolCall`, `parse_tool_calls`, `strip_tool_tags`, `VisibleText` |
| `localagent/agent/prompt.py` | `build_system_prompt` |
| `localagent/agent/core.py` | `Agent`, `ToolOutcome` |
| `localagent/training/dataset.py` | `validate_example`, `make_example` |
| `localagent/connect/owner/push.py` | `PushDispatcher` |
| `localagent/connect/owner/server.py` | `create_app` |
| `localagent/connect/owner/terminal.py` | `run_terminal` |
| `localagent/connect/owner/static/` | PWA (moved from `static/`) |
| `localagent/bootstrap.py` | `Services`, `build_services` |
| `localagent/setup_agent.py` | `create_agent`, `migrate_legacy` |
| `localagent/__main__.py` | CLI `serve` / `chat` |
| `agent_template/` | skeleton agent folder |
| `scripts/new_agent.py`, `scripts/migrate_legacy.py`, `scripts/diagnose.py` | CLIs |
| `tests/fakes.py` | `FakeBackend`, `write_agent_yaml` |

---

### Task 1: Package skeleton, config, layer rule test

**Files:**
- Create: `localagent/__init__.py`, `localagent/{runtime,vault,protocol,agent,agent/tools,training,connect,connect/owner,connect/peer}/__init__.py` (empty)
- Create: `localagent/config.py`
- Create: `tests/fakes.py`, `tests/test_config.py`, `tests/test_layers.py`
- Modify: `requirements.txt` (add `pyyaml>=6.0`, `cryptography>=42`, a commented `# peft>=0.13  # optional: LoRA adapters`)
- Modify: `.gitignore` (add `my-agent/`)

**Interfaces:**
- Produces: `ConfigError`, `ModelConfig`, `AgentConfig(agent_dir, name, model, compartments, tools, history_turns, host, port, env)`, `AgentConfig.get_env(key, default="") -> str`, `load_config(agent_dir) -> AgentConfig`, `resolve_agent_dir(cli_value) -> Path`, `ensure_hf_home()`, `REPO_ROOT`, `DEFAULT_AGENT_DIR`, `COMPARTMENT_RE`.
- Produces: `tests/fakes.write_agent_yaml(agent_dir, text=None) -> Path`.

- [ ] **Step 1: Write the failing tests**

`tests/fakes.py` (the fake backend is added in Task 2):
```python
from pathlib import Path

DEFAULT_AGENT_YAML = """\
name: test-agent
model:
  id: fake/model
  backend: transformers
  quantization: 4bit
  max_new_tokens: 64
compartments: [private, shared]
tools:
  calendar:
    enabled: true
memory:
  history_turns: 5
"""


def write_agent_yaml(agent_dir: Path, text: str | None = None) -> Path:
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "agent.yaml").write_text(text or DEFAULT_AGENT_YAML, encoding="utf-8")
    return agent_dir
```

`tests/test_config.py`:
```python
import pytest

from localagent.config import ConfigError, load_config, resolve_agent_dir
from tests.fakes import write_agent_yaml


def test_load_defaults_and_values(tmp_path):
    cfg = load_config(write_agent_yaml(tmp_path / "a"))
    assert cfg.name == "test-agent"
    assert cfg.model.id == "fake/model"
    assert cfg.model.max_new_tokens == 64
    assert cfg.compartments == ["private", "shared"]
    assert cfg.tools == {"calendar": {"enabled": True}}
    assert cfg.history_turns == 5
    assert cfg.port == 8000


def test_minimal_yaml_uses_defaults(tmp_path):
    cfg = load_config(write_agent_yaml(tmp_path / "a", "name: x\n"))
    assert cfg.model.id == "Qwen/Qwen2.5-3B-Instruct"
    assert cfg.model.quantization == "4bit"
    assert cfg.compartments == ["private", "shared"]


def test_tool_shorthands_normalized(tmp_path):
    cfg = load_config(write_agent_yaml(tmp_path / "a", "tools:\n  calendar:\n  other: false\n"))
    assert cfg.tools == {"calendar": {}, "other": {"enabled": False}}


def test_env_file_and_environment(tmp_path, monkeypatch):
    d = write_agent_yaml(tmp_path / "a")
    (d / ".env").write_text("AGENT_SECRET=from-file\nVAPID_PUBLIC_KEY=pub\n")
    monkeypatch.delenv("AGENT_SECRET", raising=False)
    monkeypatch.setenv("VAPID_PUBLIC_KEY", "from-env")
    cfg = load_config(d)
    assert cfg.get_env("AGENT_SECRET") == "from-file"
    assert cfg.get_env("VAPID_PUBLIC_KEY") == "from-env"
    assert cfg.get_env("MISSING", "dflt") == "dflt"


@pytest.mark.parametrize("text, fragment", [
    ("model:\n  quantization: 8bit\n", "quantization"),
    ("compartments: [shared]\n", "private"),
    ("compartments: [private, Bad_Name]\n", "Bad_Name"),
    ("compartments: [private, private]\n", "duplicate"),
    ("modle:\n  id: x\n", "modle"),
    ("model:\n  max_new_tokens: 0\n", "max_new_tokens"),
])
def test_invalid_values_rejected(tmp_path, text, fragment):
    with pytest.raises(ConfigError, match=fragment):
        load_config(write_agent_yaml(tmp_path / "a", text))


def test_bad_yaml_message(tmp_path):
    with pytest.raises(ConfigError, match="not valid YAML"):
        load_config(write_agent_yaml(tmp_path / "a", "model: [unclosed\n"))


def test_missing_agent_dir_message(tmp_path):
    with pytest.raises(ConfigError, match="new_agent.py"):
        resolve_agent_dir(str(tmp_path / "nope"))


def test_resolve_from_env(tmp_path, monkeypatch):
    d = write_agent_yaml(tmp_path / "a")
    monkeypatch.setenv("LOCALAGENT_DIR", str(d))
    assert resolve_agent_dir(None) == d.resolve()
```

`tests/test_layers.py`:
```python
import ast
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent / "localagent"
ALLOWED = {
    "runtime": (),
    "vault": (),
    "protocol": ("localagent.vault",),
    "agent": ("localagent.protocol.session", "localagent.runtime.base"),
    "training": ("localagent.protocol", "localagent.runtime"),
    "connect": ("localagent.protocol", "localagent.agent", "localagent.runtime"),
}


def _imports(path: Path, module: str):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    package = module.rsplit(".", 1)[0] if path.name != "__init__.py" else module
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".")
                base = base[: len(base) - (node.level - 1)]
                yield ".".join(base + ([node.module] if node.module else []))
            else:
                yield node.module


def _violations():
    found = []
    for layer, allowed in ALLOWED.items():
        for path in (PKG / layer).rglob("*.py"):
            rel = path.relative_to(PKG.parent).with_suffix("")
            module = ".".join(rel.parts).removesuffix(".__init__")
            for imp in _imports(path, module):
                if not imp or not imp.startswith("localagent"):
                    continue
                if imp == f"localagent.{layer}" or imp.startswith(f"localagent.{layer}."):
                    continue
                if any(imp == a or imp.startswith(a + ".") for a in allowed):
                    continue
                found.append(f"{module} imports {imp}")
    return found


def test_layer_import_rules():
    assert _violations() == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_config.py tests/test_layers.py -v`
Expected: test_config fails with `ModuleNotFoundError: localagent`.

- [ ] **Step 3: Implement**

Create the empty `__init__.py` files. `localagent/config.py`:
```python
"""Loads an agent folder (agent.yaml + .env) into an AgentConfig."""
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
TOP_LEVEL_KEYS = {"name", "model", "compartments", "tools", "memory", "server"}


class ConfigError(Exception):
    """The agent folder or agent.yaml is missing or invalid."""


@dataclass
class ModelConfig:
    id: str = "Qwen/Qwen2.5-3B-Instruct"
    backend: str = "transformers"
    quantization: str = "4bit"
    max_new_tokens: int = 256


@dataclass
class AgentConfig:
    agent_dir: Path
    name: str = "my-agent"
    model: ModelConfig = field(default_factory=ModelConfig)
    compartments: list[str] = field(default_factory=lambda: ["private", "shared"])
    tools: dict[str, dict] = field(default_factory=dict)
    history_turns: int = 20
    host: str = "127.0.0.1"
    port: int = 8000
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


def _normalize_tools(raw_tools) -> dict[str, dict]:
    if raw_tools is None:
        return {}
    if not isinstance(raw_tools, dict):
        raise ConfigError("'tools' in agent.yaml must map tool names to settings")
    tools = {}
    for name, value in raw_tools.items():
        if value is None or value is True:
            value = {}
        elif value is False:
            value = {"enabled": False}
        if not isinstance(value, dict):
            raise ConfigError(f"tools.{name} must be a mapping, true or false")
        tools[str(name)] = value
    return tools


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
    unknown = set(raw) - TOP_LEVEL_KEYS
    if unknown:
        raise ConfigError(f"Unknown setting(s) in agent.yaml: {', '.join(sorted(unknown))}")

    model_raw = _section(raw, "model")
    unknown = set(model_raw) - set(ModelConfig.__dataclass_fields__)
    if unknown:
        raise ConfigError(f"Unknown model setting(s): {', '.join(sorted(unknown))}")
    model = ModelConfig(**model_raw)
    if model.quantization not in QUANTIZATIONS:
        raise ConfigError(f"model.quantization must be one of {', '.join(QUANTIZATIONS)}, got '{model.quantization}'")
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
    server = _section(raw, "server")
    env = {k: v for k, v in dotenv_values(agent_dir / ".env").items() if v is not None}
    return AgentConfig(
        agent_dir=agent_dir,
        name=str(raw.get("name") or agent_dir.name),
        model=model,
        compartments=list(compartments),
        tools=_normalize_tools(raw.get("tools")),
        history_turns=int(memory.get("history_turns", 20)),
        host=str(server.get("host", "127.0.0.1")),
        port=int(server.get("port", 8000)),
        env=env,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_config.py tests/test_layers.py -v`
Expected: all PASS.

- [ ] **Step 5: Leave uncommitted** (owner instruction).

---

### Task 2: Runtime: interface, fake, Transformers backend, factory, hardware

**Files:**
- Create: `localagent/runtime/base.py`, `transformers_backend.py`, `factory.py`, `hardware.py`
- Modify: `tests/fakes.py` (add `FakeBackend`)
- Create: `tests/test_runtime_contract.py`, `tests/test_hardware.py`

**Interfaces:**
- Produces: `Backend` protocol (`load(model_id, quantization)`, `generate(messages, max_new_tokens) -> str`, `generate_stream(messages, max_new_tokens) -> Iterator[str]`, `set_adapters(paths: list[Path])`, `info() -> dict`), `AdapterLoadError`, `create_backend(name) -> Backend`, `AVAILABLE_BACKENDS`, `detect() -> dict`, `recommend(info) -> dict` with keys `recommended_backend`, `recommended_model`, `recommended_quantization`, `backend_available`.
- Produces: `tests.fakes.FakeBackend(replies=None, fail_adapters=False)` with `.calls` (list of message lists) and `.adapters`.

- [ ] **Step 1: Write failing tests**

Append to `tests/fakes.py`:
```python
from localagent.runtime.base import AdapterLoadError


class FakeBackend:
    """Scripted backend: returns replies in order, then 'OK'. Streams in 7-char chunks."""

    def __init__(self, replies=None, fail_adapters: bool = False):
        self.replies = list(replies or [])
        self.fail_adapters = fail_adapters
        self.calls: list[list[dict]] = []
        self.adapters: list[Path] = []
        self.model_id = ""

    def load(self, model_id, quantization="4bit"):
        self.model_id = model_id

    def _next(self) -> str:
        return self.replies.pop(0) if self.replies else "OK"

    def generate(self, messages, max_new_tokens=256):
        self.calls.append(list(messages))
        return self._next()

    def generate_stream(self, messages, max_new_tokens=256):
        self.calls.append(list(messages))
        text = self._next()
        for i in range(0, len(text), 7):
            yield text[i:i + 7]

    def set_adapters(self, paths):
        if self.fail_adapters and paths:
            self.adapters = []
            raise AdapterLoadError("fake failure")
        self.adapters = list(paths)

    def info(self):
        return {"model_id": self.model_id, "backend": "fake", "device": "none",
                "adapters": [str(p) for p in self.adapters]}
```

`tests/test_runtime_contract.py`:
```python
from pathlib import Path

import pytest

from localagent.runtime.base import AdapterLoadError, Backend
from localagent.runtime.factory import AVAILABLE_BACKENDS, create_backend
from localagent.runtime.transformers_backend import TransformersBackend
from tests.fakes import FakeBackend

MSGS = [{"role": "user", "content": "hi"}]


@pytest.fixture(params=[FakeBackend])
def backend(request):
    b = request.param(replies=["hello there friend", "hello there friend"])
    b.load("fake/model", "4bit")
    return b


def test_satisfies_protocol(backend):
    assert isinstance(backend, Backend)


def test_generate_returns_str(backend):
    assert isinstance(backend.generate(MSGS, 16), str)


def test_stream_yields_str_chunks(backend):
    chunks = list(backend.generate_stream(MSGS, 16))
    assert chunks and all(isinstance(c, str) for c in chunks)


def test_set_adapters_empty_is_base(backend):
    backend.set_adapters([])
    assert backend.info()["adapters"] == []


def test_info_keys(backend):
    assert {"model_id", "backend", "device", "adapters"} <= set(backend.info())


def test_adapter_failure_leaves_none_active():
    b = FakeBackend(fail_adapters=True)
    with pytest.raises(AdapterLoadError):
        b.set_adapters([Path("x")])
    assert b.info()["adapters"] == []


def test_transformers_backend_satisfies_protocol_without_loading():
    assert isinstance(TransformersBackend(), Backend)


def test_factory():
    assert "transformers" in AVAILABLE_BACKENDS
    assert isinstance(create_backend("transformers"), TransformersBackend)
    with pytest.raises(NotImplementedError, match="planned"):
        create_backend("mlx")
    with pytest.raises(ValueError, match="Unknown backend"):
        create_backend("nope")
```

`tests/test_hardware.py`:
```python
from localagent.runtime.hardware import detect, recommend


def _info(gpu=None, ram=8):
    return {"os": "Windows", "machine": "AMD64", "ram_gb": ram, "gpu": gpu}


def test_nvidia_small_card_gets_fast_small_model():
    r = recommend(_info({"vendor": "nvidia", "name": "GTX 1050", "vram_gb": 3.9}))
    assert r["recommended_backend"] == "transformers"
    assert r["recommended_model"] == "Qwen/Qwen2.5-1.5B-Instruct"
    assert r["recommended_quantization"] == "fp16"
    assert r["backend_available"] is True


def test_nvidia_big_card():
    r = recommend(_info({"vendor": "nvidia", "name": "RTX", "vram_gb": 12}))
    assert r["recommended_model"] == "Qwen/Qwen2.5-7B-Instruct"


def test_mid_card():
    r = recommend(_info({"vendor": "nvidia", "name": "RTX", "vram_gb": 8}))
    assert r["recommended_model"] == "Qwen/Qwen2.5-3B-Instruct"
    assert r["recommended_quantization"] == "4bit"


def test_apple_and_cpu_backends_not_yet_available():
    assert recommend(_info({"vendor": "apple", "name": "M4", "vram_gb": None}, ram=16))["recommended_backend"] == "mlx"
    cpu = recommend(_info(None, ram=8))
    assert cpu["recommended_backend"] == "llamacpp"
    assert cpu["backend_available"] is False


def test_detect_shape():
    info = detect()
    assert {"os", "ram_gb", "gpu", "recommended_backend"} <= set(info)
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_runtime_contract.py tests/test_hardware.py -v`
Expected: FAIL, `ModuleNotFoundError: localagent.runtime.base`.

- [ ] **Step 3: Implement**

`localagent/runtime/base.py`:
```python
"""The one interface every model backend implements. Nothing above this layer knows which model runs."""
from pathlib import Path
from typing import Iterator, Protocol, runtime_checkable


class AdapterLoadError(RuntimeError):
    """Adapters could not be activated. No adapter is active afterwards."""


@runtime_checkable
class Backend(Protocol):
    def load(self, model_id: str, quantization: str) -> None: ...

    def generate(self, messages: list[dict], max_new_tokens: int) -> str: ...

    def generate_stream(self, messages: list[dict], max_new_tokens: int) -> Iterator[str]: ...

    def set_adapters(self, paths: list[Path]) -> None:
        """Activate exactly these LoRA adapters; [] means the base model."""
        ...

    def info(self) -> dict: ...
```

`localagent/runtime/transformers_backend.py`:
```python
"""HuggingFace Transformers backend (NVIDIA / CUDA, CPU fallback)."""
from pathlib import Path
from threading import Thread

from localagent.runtime.base import AdapterLoadError


class TransformersBackend:
    name = "transformers"

    def __init__(self):
        self.model = None
        self.tokenizer = None
        self.model_id = ""
        self._adapters: list[Path] = []

    def load(self, model_id: str, quantization: str = "4bit") -> None:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

        kwargs = {"device_map": "auto"}
        if quantization == "4bit":
            kwargs["quantization_config"] = BitsAndBytesConfig(
                load_in_4bit=True, bnb_4bit_compute_dtype=torch.float16
            )
        elif quantization == "fp16":
            kwargs["dtype"] = torch.float16
        elif quantization != "none":
            raise ValueError(f"Unknown quantization '{quantization}'")
        self.tokenizer = AutoTokenizer.from_pretrained(model_id)
        self.model = AutoModelForCausalLM.from_pretrained(model_id, **kwargs)
        self.model_id = model_id

    def _prepare_inputs(self, messages: list[dict]):
        text = self.tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        return self.tokenizer([text], return_tensors="pt").to(self.model.device)

    def generate(self, messages: list[dict], max_new_tokens: int = 256) -> str:
        inputs = self._prepare_inputs(messages)
        input_len = inputs["input_ids"].shape[1]
        output_ids = self.model.generate(
            **inputs, max_new_tokens=max_new_tokens, do_sample=False,
            pad_token_id=self.tokenizer.eos_token_id,
        )
        return self.tokenizer.decode(output_ids[0][input_len:], skip_special_tokens=True).strip()

    def generate_stream(self, messages: list[dict], max_new_tokens: int = 256):
        from transformers import TextIteratorStreamer

        inputs = self._prepare_inputs(messages)
        streamer = TextIteratorStreamer(self.tokenizer, skip_prompt=True, skip_special_tokens=True)
        thread = Thread(target=self.model.generate, kwargs=dict(
            **inputs, max_new_tokens=max_new_tokens, do_sample=False,
            pad_token_id=self.tokenizer.eos_token_id, streamer=streamer,
        ))
        thread.start()
        for chunk in streamer:
            yield chunk
        thread.join()

    def set_adapters(self, paths: list[Path]) -> None:
        paths = [Path(p) for p in paths]
        if paths == self._adapters:
            return
        self._remove_adapters()
        if not paths:
            return
        model = None
        try:
            from peft import PeftModel

            model = PeftModel.from_pretrained(self.model, str(paths[0]), adapter_name="a0")
            for i, path in enumerate(paths[1:], start=1):
                model.load_adapter(str(path), adapter_name=f"a{i}")
            model.base_model.set_adapter([f"a{i}" for i in range(len(paths))])
        except Exception as e:
            if model is not None:
                try:
                    self.model = model.unload()
                except Exception:
                    pass
            hint = " (pip install peft)" if isinstance(e, ImportError) else ""
            raise AdapterLoadError(f"Could not load adapters {[str(p) for p in paths]}: {e}{hint}") from e
        self.model = model
        self._adapters = paths

    def _remove_adapters(self) -> None:
        if self._adapters:
            self.model = self.model.unload()
            self._adapters = []

    def info(self) -> dict:
        device = str(getattr(self.model, "device", "not loaded")) if self.model is not None else "not loaded"
        return {"model_id": self.model_id, "backend": self.name, "device": device,
                "adapters": [str(p) for p in self._adapters]}
```

`localagent/runtime/factory.py`:
```python
"""Backend name (from agent.yaml) -> backend instance."""
from localagent.runtime.base import Backend

AVAILABLE_BACKENDS = ("transformers",)
PLANNED_BACKENDS = ("llamacpp", "mlx")


def create_backend(name: str) -> Backend:
    if name == "transformers":
        from localagent.runtime.transformers_backend import TransformersBackend
        return TransformersBackend()
    if name in PLANNED_BACKENDS:
        raise NotImplementedError(
            f"Backend '{name}' is planned but not implemented yet. Use 'transformers' for now."
        )
    raise ValueError(f"Unknown backend '{name}'. Available: {', '.join(AVAILABLE_BACKENDS)}")
```

`localagent/runtime/hardware.py`:
```python
"""Detect this machine's hardware and recommend a backend and model size."""
import os
import platform
import shutil
import subprocess

from localagent.runtime.factory import AVAILABLE_BACKENDS


def _ram_gb() -> float | None:
    try:
        if platform.system() == "Windows":
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return round(stat.ullTotalPhys / 2**30, 1)
        return round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30, 1)
    except Exception:
        return None


def _gpu() -> dict | None:
    try:
        import torch

        if torch.cuda.is_available():
            props = torch.cuda.get_device_properties(0)
            return {"vendor": "nvidia", "name": props.name, "vram_gb": round(props.total_memory / 2**30, 1)}
    except Exception:
        pass
    smi = shutil.which("nvidia-smi")
    if smi:
        try:
            out = subprocess.run([smi, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True, timeout=10).stdout.strip().splitlines()
            if out:
                name, mem = out[0].rsplit(",", 1)
                return {"vendor": "nvidia", "name": name.strip(), "vram_gb": round(int(mem) / 1024, 1)}
        except Exception:
            pass
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        return {"vendor": "apple", "name": "Apple Silicon (unified memory)", "vram_gb": None}
    return None


def recommend(info: dict) -> dict:
    gpu = info.get("gpu") or {}
    vendor = gpu.get("vendor")
    vram = gpu.get("vram_gb") or 0
    ram = info.get("ram_gb") or 0
    if vendor == "nvidia":
        if vram >= 10:
            backend, model, quant = "transformers", "Qwen/Qwen2.5-7B-Instruct", "4bit"
        elif vram >= 6:
            backend, model, quant = "transformers", "Qwen/Qwen2.5-3B-Instruct", "4bit"
        elif vram >= 3.5:
            # Measured on a GTX 1050: 1.5B fp16 is ~12x faster than 3B 4-bit (scripts/benchmark_results.csv)
            backend, model, quant = "transformers", "Qwen/Qwen2.5-1.5B-Instruct", "fp16"
        else:
            backend, model, quant = "transformers", "Qwen/Qwen2.5-1.5B-Instruct", "4bit"
    elif vendor == "apple":
        backend, model, quant = "mlx", ("Qwen/Qwen2.5-7B-Instruct" if ram >= 16 else "Qwen/Qwen2.5-3B-Instruct"), "4bit"
    else:
        backend, model, quant = "llamacpp", ("Qwen/Qwen2.5-3B-Instruct" if ram >= 16 else "Qwen/Qwen2.5-1.5B-Instruct"), "4bit"
    return {"recommended_backend": backend, "recommended_model": model,
            "recommended_quantization": quant, "backend_available": backend in AVAILABLE_BACKENDS}


def detect() -> dict:
    info = {"os": platform.system(), "machine": platform.machine(),
            "python": platform.python_version(), "ram_gb": _ram_gb(), "gpu": _gpu()}
    info.update(recommend(info))
    return info
```

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python -m pytest tests/test_runtime_contract.py tests/test_hardware.py tests/test_layers.py -v`
Expected: PASS.

- [ ] **Step 5: Leave uncommitted.**

---

### Task 3: Vault

**Files:**
- Create: `localagent/vault/store.py`, `tests/test_vault.py`

**Interfaces:**
- Produces: `Item(kind, compartment, id, content)` (frozen dataclass), `Vault(agent_dir, compartments)` with `.root`, `.compartments`, `read(kind, compartments) -> list[Item]`, `list_compartments(kind) -> list[str]`, `append_memory(compartment, record)`, `write_training_examples(compartment, examples)`; `compartment_to_folder(c)`, `folder_to_compartment(name)`, `PEER_PREFIX = "peer:"`.
- Content types: knowledge → `str`; memory/training → `dict` (one JSON line); work → `{"title", "status", "meta", "body"}`.

- [ ] **Step 1: Write failing tests** — `tests/test_vault.py`:
```python
import json

import pytest

from localagent.vault.store import Vault


@pytest.fixture
def vault(tmp_path):
    (tmp_path / "knowledge/private").mkdir(parents=True)
    (tmp_path / "knowledge/shared").mkdir(parents=True)
    (tmp_path / "knowledge/private/me.md").write_text("I live in Madrid.")
    (tmp_path / "knowledge/shared/style.txt").write_text("Be brief.")
    (tmp_path / "knowledge/shared/empty.md").write_text("   ")
    return Vault(tmp_path, ["private", "shared"])


def test_knowledge_labeled_by_folder(vault):
    items = vault.read("knowledge", ["private", "shared"])
    assert [(i.compartment, i.content) for i in items] == [("private", "I live in Madrid."), ("shared", "Be brief.")]


def test_knowledge_filtered(vault):
    assert [i.content for i in vault.read("knowledge", ["shared"])] == ["Be brief."]


def test_unknown_folder_ignored(vault, caplog):
    (vault.root / "knowledge/family").mkdir()
    (vault.root / "knowledge/family/x.md").write_text("secret")
    assert all(i.content != "secret" for i in vault.read("knowledge", ["family", "private"]))
    assert "family" in caplog.text


def test_memory_roundtrip_and_peer(vault):
    vault.append_memory("private", {"user": "hi", "assistant": "hello"})
    vault.append_memory("peer:abc_-1", {"user": "q", "assistant": "a"})
    assert (vault.root / "memory/peer__abc_-1").is_dir()
    priv = vault.read("memory", ["private"])
    assert priv[0].content["user"] == "hi" and "ts" in priv[0].content
    assert vault.read("memory", ["peer:abc_-1"])[0].compartment == "peer:abc_-1"
    assert "peer:abc_-1" in vault.list_compartments("memory")
    assert "peer:abc_-1" not in vault.list_compartments("knowledge")


def test_memory_unknown_compartment_rejected(vault):
    with pytest.raises(ValueError):
        vault.append_memory("family", {"user": "x"})


def test_corrupt_memory_line_skipped(vault, caplog):
    vault.append_memory("private", {"user": "ok", "assistant": "fine"})
    f = next((vault.root / "memory/private").glob("*.jsonl"))
    with f.open("a") as fh:
        fh.write('{"user": "half-writ')
    items = vault.read("memory", ["private"])
    assert len(items) == 1 and "corrupt" in caplog.text


def test_work_front_matter(vault):
    (vault.root / "work").mkdir()
    (vault.root / "work/trip.md").write_text("---\ncompartment: shared\nstatus: active\ntitle: Trip\n---\nBook flights\n")
    (vault.root / "work/plain.md").write_text("No header here")
    (vault.root / "work/bad.md").write_text("---\ncompartment: family\n---\nx\n")
    shared = vault.read("work", ["shared"])
    assert [(w.content["title"], w.content["body"]) for w in shared] == [("Trip", "Book flights")]
    private = vault.read("work", ["private"])
    assert [w.content["title"] for w in private] == ["plain"]


def test_training_roundtrip(vault):
    ex = {"messages": [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]}
    vault.write_training_examples("shared", [ex])
    items = vault.read("training", ["shared"])
    assert items[0].content == ex and items[0].compartment == "shared"
    assert vault.read("training", ["private"]) == []
    with pytest.raises(ValueError):
        vault.write_training_examples("peer:x", [ex])
```

- [ ] **Step 2: Run to verify failure**: `.venv/Scripts/python -m pytest tests/test_vault.py -v`. Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement** `localagent/vault/store.py`:
```python
"""Passive, labeled storage over an agent folder. Applies the filters it is given; decides nothing."""
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

KINDS = ("knowledge", "memory", "work", "training")
PEER_PREFIX = "peer:"
_FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)(.*)\Z", re.DOTALL)


@dataclass(frozen=True)
class Item:
    kind: str
    compartment: str
    id: str
    content: object  # str for knowledge; dict for memory, work and training


def compartment_to_folder(compartment: str) -> str:
    return compartment.replace(":", "__", 1)


def folder_to_compartment(name: str) -> str:
    return name.replace("__", ":", 1)


class Vault:
    def __init__(self, agent_dir: Path, compartments: list[str]):
        self.root = Path(agent_dir)
        self.compartments = list(compartments)
        self._warned: set[str] = set()

    # ── reading ──────────────────────────────────────────────────────────────

    def read(self, kind: str, compartments: list[str]) -> list[Item]:
        if kind not in KINDS:
            raise ValueError(f"Unknown kind '{kind}'")
        wanted = list(dict.fromkeys(compartments))
        return getattr(self, f"_read_{kind}")(wanted)

    def list_compartments(self, kind: str) -> list[str]:
        """Labels that can exist for `kind`: configured compartments, plus peer:* for memory."""
        found = list(self.compartments)
        memory = self.root / "memory"
        if kind == "memory" and memory.is_dir():
            for d in sorted(memory.iterdir()):
                c = folder_to_compartment(d.name)
                if d.is_dir() and c.startswith(PEER_PREFIX):
                    found.append(c)
        return found

    def _warn(self, message: str) -> None:
        if message not in self._warned:
            self._warned.add(message)
            log.warning(message)

    def _warn_unknown_folders(self, base: Path) -> None:
        if base.is_dir():
            for d in base.iterdir():
                if d.is_dir() and d.name not in self.compartments and d.name != "adapters":
                    self._warn(f"{base.name}/{d.name} is not a compartment in agent.yaml; ignoring it")

    def _jsonl(self, path: Path):
        if not path.is_file():
            return
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                self._warn(f"Skipping corrupt line {path}:{n}")
                continue
            if isinstance(record, dict):
                yield n, record

    def _read_knowledge(self, wanted: list[str]) -> list[Item]:
        base = self.root / "knowledge"
        self._warn_unknown_folders(base)
        items = []
        for c in self.compartments:
            folder = base / c
            if c not in wanted or not folder.is_dir():
                continue
            for f in sorted(folder.glob("*.md")) + sorted(folder.glob("*.txt")):
                text = f.read_text(encoding="utf-8").strip()
                if text:
                    items.append(Item("knowledge", c, f"{c}/{f.name}", text))
        return items

    def _read_memory(self, wanted: list[str]) -> list[Item]:
        items = []
        for c in wanted:
            if c not in self.compartments and not c.startswith(PEER_PREFIX):
                continue
            folder = self.root / "memory" / compartment_to_folder(c)
            for f in sorted(folder.glob("*.jsonl")) if folder.is_dir() else []:
                for n, record in self._jsonl(f):
                    items.append(Item("memory", c, f"{f.name}#{n}", record))
        return items

    def _read_work(self, wanted: list[str]) -> list[Item]:
        folder = self.root / "work"
        items = []
        for f in sorted(folder.glob("*.md")) if folder.is_dir() else []:
            meta, body = self._front_matter(f)
            c = str(meta.get("compartment", "private"))
            if c not in self.compartments:
                self._warn(f"work/{f.name} has unknown compartment '{c}'; ignoring it")
                continue
            if c in wanted:
                items.append(Item("work", c, f.name, {
                    "title": str(meta.get("title", f.stem)),
                    "status": str(meta.get("status", "active")),
                    "meta": meta,
                    "body": body.strip(),
                }))
        return items

    def _front_matter(self, path: Path) -> tuple[dict, str]:
        text = path.read_text(encoding="utf-8")
        match = _FRONT_MATTER.match(text)
        if not match:
            return {}, text
        try:
            meta = yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError:
            meta = None
        if not isinstance(meta, dict):
            self._warn(f"work/{path.name} has an invalid header; treating it as private")
            return {}, match.group(2)
        return meta, match.group(2)

    def _read_training(self, wanted: list[str]) -> list[Item]:
        self._warn_unknown_folders(self.root / "training")
        items = []
        for c in self.compartments:
            if c in wanted:
                f = self.root / "training" / c / "examples.jsonl"
                items += [Item("training", c, f"{c}#{n}", r) for n, r in self._jsonl(f)]
        return items

    # ── writing ──────────────────────────────────────────────────────────────

    def _append_jsonl(self, path: Path, records: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            for record in records:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def append_memory(self, compartment: str, record: dict) -> None:
        if compartment not in self.compartments and not compartment.startswith(PEER_PREFIX):
            raise ValueError(f"Unknown memory compartment '{compartment}'")
        now = datetime.now()
        path = self.root / "memory" / compartment_to_folder(compartment) / f"{now:%Y-%m-%d}.jsonl"
        self._append_jsonl(path, [{"ts": now.isoformat(timespec="seconds"), **record}])

    def write_training_examples(self, compartment: str, examples: list[dict]) -> None:
        if compartment not in self.compartments:
            raise ValueError(f"Training examples must go to a configured compartment, not '{compartment}'")
        self._append_jsonl(self.root / "training" / compartment / "examples.jsonl", list(examples))
```

- [ ] **Step 4: Run**: `.venv/Scripts/python -m pytest tests/test_vault.py tests/test_layers.py -v`. Expected PASS.
- [ ] **Step 5: Leave uncommitted.**

---

### Task 4: Protocol guard (scopes, policy, audit, identity, session, Protocol)

**Files:**
- Create: `localagent/protocol/scopes.py`, `policy.py`, `audit.py`, `identity.py`, `session.py`, `guard.py`, `handshake.py`
- Create: `tests/test_policy.py`, `tests/test_session.py` (replaces old file), `tests/test_guard.py`

**Interfaces:**
- Consumes: `Vault`, `Item` (Task 3).
- Produces:
  - `Scope(scopes)` with `.items`, `.is_all`, `allows(kind, compartment)`, `allows_tool(name, action)`, and `InvalidScope`.
  - `Policy(owner, default_peer, peers)` with `.for_peer(id)`, plus `load_policy(path)` and `PolicyError`.
  - `Audit(path)` with `.log(event, **fields)`.
  - `generate_identity(dir) -> str` and `load_agent_id(dir) -> str | None`.
  - `ToolView(name, actions)`, `ScopeError`, `UnknownToolError`, `WITHHELD`, `model_slug(model_id)`.
  - `Session(*, principal, scope, memory_compartment, vault, audit, tools, adapters_dir)`, whose methods are `context()`, `history(n)`, `reset_history()`, `tools()`, `check_tool_call(name, action)`, `filter_tool_result(name, result)`, `adapters(model_id)`, `record(turn)` and `close()`.
  - `Protocol(*, vault, policy, audit, tools, adapters_dir, owner_secret)` with `Protocol.for_agent(agent_dir, compartments, tools, owner_secret)`, `open_owner_session(token)`, `open_peer_session(request)` and `training_set(compartment)`, plus `AuthError`.
- Tool objects are duck-typed. Each needs `.compartment: str` and `.actions: dict[str, Action-like]`. The tools dict maps tool name → tool.
- **Tool data rule:** a tool's result is visible only when the session has `knowledge:<tool compartment>` (or `all`). It is written in `docs/architecture.md` in Task 9.

- [ ] **Step 1: Write failing tests**

`tests/test_policy.py`:
```python
import pytest

from localagent.protocol.policy import PolicyError, load_policy
from localagent.protocol.scopes import InvalidScope, Scope


def test_scope_checks():
    s = Scope(["knowledge:shared", "tool:calendar:list", "memory:peer:abc"])
    assert s.allows("knowledge", "shared") and not s.allows("knowledge", "private")
    assert s.allows_tool("calendar", "list") and not s.allows_tool("calendar", "create")
    assert Scope(["tool:calendar"]).allows_tool("calendar", "delete")
    assert Scope(["all"]).allows("adapter", "private")


@pytest.mark.parametrize("bad", ["knowledge", "tool:", "files:x", "knowledge:Bad", "tool:a:b:c"])
def test_invalid_scopes(bad):
    with pytest.raises(InvalidScope):
        Scope([bad])


def test_scope_string_instead_of_list():
    with pytest.raises(InvalidScope, match="list"):
        Scope("all")


def test_defaults_when_missing(tmp_path):
    p = load_policy(tmp_path / "policy.yaml")
    assert p.owner.is_all
    assert p.for_peer("anyone").allows("knowledge", "shared")
    assert not p.for_peer("anyone").allows("knowledge", "private")


def test_peer_override(tmp_path):
    (tmp_path / "policy.yaml").write_text("peers:\n  abc: [tool:calendar:list]\n")
    p = load_policy(tmp_path / "policy.yaml")
    assert p.for_peer("abc").allows_tool("calendar", "list")
    assert not p.for_peer("abc").allows("knowledge", "shared")


@pytest.mark.parametrize("text, fragment", [
    ("owner: [everything]\n", "everything"),
    ("peerz: {}\n", "peerz"),
    ("peers: [a, b]\n", "peers"),
    ("owner: [all\n", "YAML"),
])
def test_policy_errors(tmp_path, text, fragment):
    (tmp_path / "policy.yaml").write_text(text)
    with pytest.raises(PolicyError, match=fragment):
        load_policy(tmp_path / "policy.yaml")
```

`tests/test_session.py`:
```python
import json
from dataclasses import dataclass, field

import pytest

from localagent.protocol.audit import Audit
from localagent.protocol.scopes import Scope
from localagent.protocol.session import WITHHELD, ScopeError, Session, UnknownToolError
from localagent.vault.store import Vault


@dataclass
class A:
    description: str = "d"
    params: dict = field(default_factory=dict)
    kind: str = "read"


class FakeTool:
    compartment = "private"
    actions = {"list": A(), "create": A(kind="write")}


@pytest.fixture
def agent_dir(tmp_path):
    (tmp_path / "knowledge/private").mkdir(parents=True)
    (tmp_path / "knowledge/shared").mkdir(parents=True)
    (tmp_path / "knowledge/private/me.md").write_text("PRIVATE-FACT")
    (tmp_path / "knowledge/shared/s.md").write_text("SHARED-FACT")
    return tmp_path


def make(agent_dir, scopes, memory="private"):
    return Session(principal="peer:x" if memory != "private" else "owner", scope=Scope(scopes),
                   memory_compartment=memory, vault=Vault(agent_dir, ["private", "shared"]),
                   audit=Audit(agent_dir / "audit.log"), tools={"calendar": FakeTool()},
                   adapters_dir=agent_dir / "training/adapters")


def audit_events(agent_dir):
    return [json.loads(l)["event"] for l in (agent_dir / "audit.log").read_text().splitlines()]


def test_context_filtered(agent_dir):
    texts = [i.content for i in make(agent_dir, ["knowledge:shared"]).context()]
    assert texts == ["SHARED-FACT"]
    assert {i.content for i in make(agent_dir, ["all"]).context()} == {"PRIVATE-FACT", "SHARED-FACT"}


def test_tools_filtered_by_action(agent_dir):
    views = make(agent_dir, ["tool:calendar:list"]).tools()
    assert [(v.name, list(v.actions)) for v in views] == [("calendar", ["list"])]
    assert make(agent_dir, ["knowledge:shared"]).tools() == []


def test_check_tool_call(agent_dir):
    s = make(agent_dir, ["tool:calendar:list"])
    s.check_tool_call("calendar", "list")
    with pytest.raises(ScopeError):
        s.check_tool_call("calendar", "create")
    with pytest.raises(UnknownToolError):
        s.check_tool_call("email", "send")
    assert audit_events(agent_dir) == ["tool_denied", "tool_unknown"]


def test_tool_result_withheld_outside_compartment(agent_dir):
    s = make(agent_dir, ["tool:calendar:list", "knowledge:shared"])
    assert s.filter_tool_result("calendar", {"x": 1}) is WITHHELD
    assert "tool_result_withheld" in audit_events(agent_dir)
    assert make(agent_dir, ["all"]).filter_tool_result("calendar", {"x": 1}) == {"x": 1}


def test_adapters_per_scope(agent_dir):
    for c in ("private", "shared"):
        (agent_dir / f"training/adapters/org--model/{c}").mkdir(parents=True)
    assert [p.name for p in make(agent_dir, ["all"]).adapters("org/model")] == ["private", "shared"]
    assert [p.name for p in make(agent_dir, ["adapter:shared"]).adapters("org/model")] == ["shared"]
    assert make(agent_dir, ["adapter:shared"]).adapters("other/model") == []


def test_record_and_history(agent_dir):
    s = make(agent_dir, ["all"])
    s.record({"user": "u1", "assistant": "a1", "tool_calls": []})
    s.record({"user": "u2", "assistant": "a2", "tool_calls": []})
    assert [m["content"] for m in s.history(1)] == ["u2", "a2"]
    assert len(s.history(10)) == 4
    s.reset_history()
    assert s.history(10) == []
    s.record({"user": "u3", "assistant": "a3"})
    assert [m["content"] for m in s.history(10)] == ["u3", "a3"]


def test_peer_history_isolated(agent_dir):
    make(agent_dir, ["all"]).record({"user": "owner-secret", "assistant": "x"})
    peer = make(agent_dir, ["knowledge:shared"], memory="peer:x")
    assert peer.history(10) == []
```

`tests/test_guard.py`:
```python
import json

import pytest

from localagent.protocol.guard import AuthError, Protocol
from localagent.protocol.identity import generate_identity, load_agent_id
from localagent.protocol.scopes import Scope
from localagent.protocol.session import Session
from localagent.vault.store import Vault


@pytest.fixture
def agent_dir(tmp_path):
    (tmp_path / "knowledge/private").mkdir(parents=True)
    (tmp_path / "knowledge/private/me.md").write_text("MY-BANK-PIN-1234")
    (tmp_path / "knowledge/shared").mkdir(parents=True)
    (tmp_path / "knowledge/shared/s.md").write_text("I like jazz.")
    return tmp_path


def proto(agent_dir, secret="s3cret"):
    return Protocol.for_agent(agent_dir, ["private", "shared"], tools={}, owner_secret=secret)


def test_owner_session(agent_dir):
    s = proto(agent_dir).open_owner_session("s3cret")
    assert s.principal == "owner" and s.scope.is_all
    events = [json.loads(l)["event"] for l in (agent_dir / "audit.log").read_text().splitlines()]
    assert events == ["session_opened"]


def test_wrong_token(agent_dir):
    with pytest.raises(AuthError):
        proto(agent_dir).open_owner_session("nope")
    assert "auth_failed" in (agent_dir / "audit.log").read_text()


def test_empty_secret_refuses_everyone(agent_dir):
    for token in ("", "anything"):
        with pytest.raises(AuthError, match="AGENT_SECRET"):
            proto(agent_dir, secret="").open_owner_session(token)


def test_private_never_in_non_private_session(agent_dir):
    s = Session(principal="peer:x", scope=Scope(["knowledge:shared", "memory:shared", "work:shared"]),
                memory_compartment="peer:x", vault=Vault(agent_dir, ["private", "shared"]),
                audit=proto(agent_dir).audit, tools={}, adapters_dir=agent_dir / "training/adapters")
    blob = json.dumps([i.content for i in s.context()]) + json.dumps(s.history(100))
    assert "MY-BANK-PIN-1234" not in blob


def test_training_set_exact_compartment(agent_dir):
    v = Vault(agent_dir, ["private", "shared"])
    v.write_training_examples("private", [{"messages": [{"role": "user", "content": "PRIV"}]}])
    v.write_training_examples("shared", [{"messages": [{"role": "user", "content": "SHARED"}]}])
    v.append_memory("peer:x", {"user": "PEER", "assistant": "y"})
    p = proto(agent_dir)
    blob = json.dumps(p.training_set("shared"))
    assert "SHARED" in blob and "PRIV" not in blob and "PEER" not in blob
    with pytest.raises(ValueError):
        p.training_set("peer:x")


def test_peer_sessions_not_yet_supported(agent_dir):
    with pytest.raises(NotImplementedError):
        proto(agent_dir).open_peer_session({})


def test_identity(tmp_path):
    agent_id = generate_identity(tmp_path / "identity")
    assert load_agent_id(tmp_path / "identity") == agent_id
    assert len(agent_id) == 43  # 32 bytes, base64url without padding
    with pytest.raises(FileExistsError):
        generate_identity(tmp_path / "identity")
    assert load_agent_id(tmp_path / "missing") is None
```

- [ ] **Step 2: Run to verify failure**: `.venv/Scripts/python -m pytest tests/test_policy.py tests/test_session.py tests/test_guard.py -v`. Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement**

`localagent/protocol/scopes.py`:
```python
"""Scope strings: the single vocabulary for what a session may see or do."""
import re

ALL = "all"
COMPARTMENT_KINDS = ("knowledge", "memory", "work", "adapter")
_NAME = re.compile(r"^[a-z][a-z0-9_-]*$")
_HELP = "expected all, knowledge:<c>, memory:<c>, work:<c>, adapter:<c>, tool:<name> or tool:<name>:<action>"


class InvalidScope(ValueError):
    pass


def _check(scope) -> None:
    if not isinstance(scope, str):
        raise InvalidScope(f"Invalid scope {scope!r}: {_HELP}")
    if scope == ALL:
        return
    kind, _, rest = scope.partition(":")
    if kind == "tool":
        parts = rest.split(":")
        if len(parts) in (1, 2) and all(_NAME.match(p) for p in parts):
            return
    elif kind in COMPARTMENT_KINDS and rest:
        if kind == "memory" and rest.startswith("peer:") and len(rest) > len("peer:"):
            return
        if _NAME.match(rest):
            return
    raise InvalidScope(f"Invalid scope '{scope}': {_HELP}")


class Scope:
    def __init__(self, scopes=()):
        if isinstance(scopes, str):
            raise InvalidScope(f"Scopes must be a list, got the string '{scopes}'")
        scopes = list(scopes)
        for s in scopes:
            _check(s)
        self.items = frozenset(scopes)

    @property
    def is_all(self) -> bool:
        return ALL in self.items

    def allows(self, kind: str, compartment: str) -> bool:
        return self.is_all or f"{kind}:{compartment}" in self.items

    def allows_tool(self, name: str, action: str) -> bool:
        return self.is_all or f"tool:{name}" in self.items or f"tool:{name}:{action}" in self.items

    def __repr__(self) -> str:
        return f"Scope({sorted(self.items)})"
```

`localagent/protocol/policy.py`:
```python
"""policy.yaml: which scopes the owner and each peer agent get."""
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from localagent.protocol.scopes import InvalidScope, Scope

DEFAULTS = {"owner": ["all"], "default_peer": ["knowledge:shared", "adapter:shared"], "peers": {}}


class PolicyError(ValueError):
    pass


@dataclass(frozen=True)
class Policy:
    owner: Scope
    default_peer: Scope
    peers: dict = field(default_factory=dict)

    def for_peer(self, agent_id: str) -> Scope:
        return self.peers.get(agent_id, self.default_peer)


def load_policy(path: Path) -> Policy:
    path = Path(path)
    raw = {}
    if path.is_file():
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as e:
            raise PolicyError(f"{path.name} is not valid YAML: {e}") from e
    if not isinstance(raw, dict):
        raise PolicyError(f"{path.name} must be a mapping")
    unknown = set(raw) - set(DEFAULTS)
    if unknown:
        raise PolicyError(f"Unknown key(s) in {path.name}: {', '.join(sorted(unknown))}")
    peers_raw = raw.get("peers") or {}
    if not isinstance(peers_raw, dict):
        raise PolicyError(f"'peers' in {path.name} must map agent ids to scope lists")
    try:
        return Policy(
            owner=Scope(raw.get("owner", DEFAULTS["owner"]) or []),
            default_peer=Scope(raw.get("default_peer", DEFAULTS["default_peer"]) or []),
            peers={str(k): Scope(v or []) for k, v in peers_raw.items()},
        )
    except InvalidScope as e:
        raise PolicyError(f"{path.name}: {e}") from e
```

`localagent/protocol/audit.py`:
```python
"""Append-only audit log of sessions and refusals. Never records message content."""
import json
import threading
from datetime import datetime
from pathlib import Path


class Audit:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def log(self, event: str, **fields) -> None:
        record = {"ts": datetime.now().isoformat(timespec="seconds"), "event": event, **fields}
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
```

`localagent/protocol/identity.py`:
```python
"""Agent identity: an Ed25519 keypair. The public key (base64url) is the agent id."""
import base64
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat


def generate_identity(identity_dir: Path) -> str:
    identity_dir = Path(identity_dir)
    key_path, pub_path = identity_dir / "agent.key", identity_dir / "agent.pub"
    if key_path.exists() or pub_path.exists():
        raise FileExistsError(f"An identity already exists in {identity_dir}")
    identity_dir.mkdir(parents=True, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    key_path.write_bytes(key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
    raw = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    agent_id = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    pub_path.write_text(agent_id + "\n", encoding="utf-8")
    return agent_id


def load_agent_id(identity_dir: Path) -> str | None:
    pub_path = Path(identity_dir) / "agent.pub"
    return pub_path.read_text(encoding="utf-8").strip() if pub_path.is_file() else None
```

`localagent/protocol/session.py`:
```python
"""A session: who is talking, what they may see, and the only door to the agent's data."""
from dataclasses import dataclass
from pathlib import Path

from localagent.protocol.audit import Audit
from localagent.protocol.scopes import Scope
from localagent.vault.store import Item, Vault

WITHHELD = {"withheld": "this data is outside the scope of this session"}


class ScopeError(PermissionError):
    """A request outside the session's granted scope."""


class UnknownToolError(LookupError):
    """The tool or action does not exist."""


@dataclass(frozen=True)
class ToolView:
    name: str
    actions: dict  # action name -> Action (description, params, kind)


def model_slug(model_id: str) -> str:
    return model_id.replace("/", "--")


class Session:
    def __init__(self, *, principal: str, scope: Scope, memory_compartment: str, vault: Vault,
                 audit: Audit, tools: dict, adapters_dir: Path):
        self.principal = principal
        self.scope = scope
        self.memory_compartment = memory_compartment
        self.vault = vault
        self.audit = audit
        self._tools = tools
        self.adapters_dir = Path(adapters_dir)
        self._history_offset = 0

    def _compartments(self, kind: str) -> list[str]:
        return [c for c in self.vault.list_compartments(kind) if self.scope.allows(kind, c)]

    def context(self) -> list[Item]:
        """Knowledge and work items this session may see."""
        return (self.vault.read("knowledge", self._compartments("knowledge"))
                + self.vault.read("work", self._compartments("work")))

    def _own_memory(self) -> list[dict]:
        return [i.content for i in self.vault.read("memory", [self.memory_compartment])]

    def history(self, n: int) -> list[dict]:
        """Last n turns of this session's own conversation, as chat messages."""
        if n <= 0:
            return []
        messages = []
        for record in self._own_memory()[self._history_offset:][-n:]:
            if isinstance(record.get("user"), str) and isinstance(record.get("assistant"), str):
                messages += [{"role": "user", "content": record["user"]},
                             {"role": "assistant", "content": record["assistant"]}]
        return messages

    def reset_history(self) -> None:
        self._history_offset = len(self._own_memory())

    def tools(self) -> list[ToolView]:
        views = []
        for name, tool in self._tools.items():
            allowed = {a: act for a, act in tool.actions.items() if self.scope.allows_tool(name, a)}
            if allowed:
                views.append(ToolView(name, allowed))
        return views

    def check_tool_call(self, name: str, action: str) -> None:
        tool = self._tools.get(name)
        if tool is None or action not in tool.actions:
            self.audit.log("tool_unknown", principal=self.principal, tool=name, action=action)
            raise UnknownToolError(f"Unknown tool action '{name}.{action}'")
        if not self.scope.allows_tool(name, action):
            self.audit.log("tool_denied", principal=self.principal, tool=name, action=action)
            raise ScopeError(f"'{name}.{action}' is outside this session's scope")

    def filter_tool_result(self, name: str, result):
        compartment = self._tools[name].compartment
        if self.scope.allows("knowledge", compartment):
            return result
        self.audit.log("tool_result_withheld", principal=self.principal, tool=name, compartment=compartment)
        return WITHHELD

    def adapters(self, model_id: str) -> list[Path]:
        base = self.adapters_dir / model_slug(model_id)
        return [base / c for c in self.vault.compartments
                if self.scope.allows("adapter", c) and (base / c).is_dir()]

    def record(self, turn: dict) -> None:
        self.vault.append_memory(self.memory_compartment, turn)

    def close(self) -> None:
        self.audit.log("session_closed", principal=self.principal)
```

`localagent/protocol/guard.py`:
```python
"""The guard: opens sessions and builds training sets. The only owner of the vault."""
import hmac
from pathlib import Path

from localagent.protocol.audit import Audit
from localagent.protocol.policy import Policy, load_policy
from localagent.protocol.session import Session
from localagent.vault.store import Vault

OWNER_MEMORY = "private"


class AuthError(PermissionError):
    pass


class Protocol:
    def __init__(self, *, vault: Vault, policy: Policy, audit: Audit, tools: dict,
                 adapters_dir: Path, owner_secret: str):
        self.vault = vault
        self.policy = policy
        self.audit = audit
        self.tools = tools
        self.adapters_dir = Path(adapters_dir)
        self._owner_secret = owner_secret or ""

    @classmethod
    def for_agent(cls, agent_dir: Path, compartments: list[str], tools: dict, owner_secret: str) -> "Protocol":
        agent_dir = Path(agent_dir)
        return cls(vault=Vault(agent_dir, compartments), policy=load_policy(agent_dir / "policy.yaml"),
                   audit=Audit(agent_dir / "audit.log"), tools=tools,
                   adapters_dir=agent_dir / "training" / "adapters", owner_secret=owner_secret)

    def _session(self, principal: str, scope, memory_compartment: str) -> Session:
        return Session(principal=principal, scope=scope, memory_compartment=memory_compartment,
                       vault=self.vault, audit=self.audit, tools=self.tools, adapters_dir=self.adapters_dir)

    def open_owner_session(self, token: str) -> Session:
        if not self._owner_secret:
            self.audit.log("auth_failed", principal="owner", reason="no AGENT_SECRET configured")
            raise AuthError("AGENT_SECRET is not set in the agent's .env, so owner access is disabled")
        if not isinstance(token, str) or not hmac.compare_digest(token.encode(), self._owner_secret.encode()):
            self.audit.log("auth_failed", principal="owner", reason="wrong token")
            raise AuthError("Invalid token")
        self.audit.log("session_opened", principal="owner", scope=sorted(self.policy.owner.items))
        return self._session("owner", self.policy.owner, OWNER_MEMORY)

    def open_peer_session(self, request: dict) -> Session:
        raise NotImplementedError("Peer connections arrive with the peer protocol sub-project")

    def training_set(self, compartment: str) -> list[dict]:
        """Only examples labeled exactly `compartment`. Peer data is never included."""
        if compartment not in self.vault.compartments:
            raise ValueError(f"Training sets exist only for configured compartments "
                             f"{self.vault.compartments}, not '{compartment}'")
        return [i.content for i in self.vault.read("training", [compartment]) if i.compartment == compartment]
```

`localagent/protocol/handshake.py`:
```python
"""Agent-to-agent handshake (protocol spec v0.1 §2.2). Implemented in the peer protocol sub-project."""


def handshake(request: dict) -> dict:
    raise NotImplementedError("The peer handshake is not implemented yet")
```

- [ ] **Step 4: Run**: `.venv/Scripts/python -m pytest tests/test_policy.py tests/test_session.py tests/test_guard.py tests/test_layers.py -v`. Expected PASS. (The old `tests/test_session.py` is overwritten by this task.)
- [ ] **Step 5: Leave uncommitted.**

---

### Task 5: Tools: base, registry, calendar

**Files:**
- Create: `localagent/agent/tools/base.py`, `registry.py`, `calendar/__init__.py`, `calendar/tool.py`
- Create: `tests/test_tools_base.py`, `tests/test_calendar_tool.py`

**Interfaces:**
- Produces: `Action(description, params, kind)`, `Tool` (attrs `name`, `compartment`, `actions`; methods `setup(data_dir, notify)`, `run(action, args) -> dict`, `background()`), `validate_args(action, args) -> dict`, `ToolArgsError`, `Notify = Callable[[str, str], None]`.
- Produces: `load_tools(tools_config, data_root, notify, compartments) -> dict[str, Tool]`, `ToolConfigError`.
- Convention: a tool lives in a package `localagent/agent/tools/<name>/` that exports `TOOL` (the class).
- Calendar `run` results: `create → {"id": int}`, `list → {"reminders": [dict]}`, `delete → {"deleted": bool}`.

- [ ] **Step 1: Write failing tests**

`tests/test_tools_base.py`:
```python
import pytest

from localagent.agent.tools.base import Action, ToolArgsError, validate_args
from localagent.agent.tools.registry import ToolConfigError, load_tools

ACT = Action("x", {"title": "str", "n": "int", "at": "iso-datetime"}, kind="write")


def test_valid_args_coerced():
    out = validate_args(ACT, {"title": " Hi ", "n": "3", "at": "2026-10-12T18:00:00"})
    assert out == {"title": "Hi", "n": 3, "at": "2026-10-12T18:00:00"}


@pytest.mark.parametrize("args, fragment", [
    ({"n": 1, "at": "2026-10-12T18:00"}, "title"),
    ({"title": "a", "n": "x", "at": "2026-10-12T18:00"}, "integer"),
    ({"title": "a", "n": True, "at": "2026-10-12T18:00"}, "integer"),
    ({"title": "a", "n": 1, "at": "tomorrow"}, "ISO"),
    ({"title": "a", "n": 1, "at": "2026-10-12T18:00", "extra": 1}, "extra"),
])
def test_invalid_args(args, fragment):
    with pytest.raises(ToolArgsError, match=fragment):
        validate_args(ACT, args)


def test_iso_datetime_timezone_converted_to_local_naive():
    from datetime import datetime, timezone
    out = validate_args(Action("x", {"at": "iso-datetime"}), {"at": "2026-10-12T16:00:00Z"})["at"]
    expected = datetime(2026, 10, 12, 16, tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
    assert out == expected.isoformat(timespec="seconds")


def test_iso_datetime_date_only_is_midnight():
    assert validate_args(Action("x", {"at": "iso-datetime"}), {"at": "2026-10-12"})["at"] == "2026-10-12T00:00:00"


def test_registry_loads_calendar(tmp_path):
    tools = load_tools({"calendar": {}}, tmp_path, lambda t, b: None, ["private", "shared"])
    assert list(tools) == ["calendar"]
    assert (tmp_path / "calendar/calendar.db").exists()


def test_registry_disabled_and_override(tmp_path):
    assert load_tools({"calendar": {"enabled": False}}, tmp_path, None, ["private"]) == {}
    tools = load_tools({"calendar": {"compartment": "shared"}}, tmp_path, None, ["private", "shared"])
    assert tools["calendar"].compartment == "shared"


@pytest.mark.parametrize("cfg, fragment", [
    ({"nope": {}}, "Unknown tool"),
    ({"calendar": {"compartment": "family"}}, "family"),
    ({"calendar": {"colour": "red"}}, "colour"),
])
def test_registry_errors(tmp_path, cfg, fragment):
    with pytest.raises(ToolConfigError, match=fragment):
        load_tools(cfg, tmp_path, None, ["private", "shared"])
```

`tests/test_calendar_tool.py`:
```python
from datetime import datetime, timedelta

import pytest

from localagent.agent.tools.calendar import TOOL as CalendarTool


@pytest.fixture
def notified():
    return []


@pytest.fixture
def cal(tmp_path, notified):
    tool = CalendarTool()
    tool.setup(tmp_path / "calendar", lambda title, body: notified.append((title, body)))
    return tool


def iso(delta):
    return (datetime.now() + delta).isoformat(timespec="seconds")


def test_create_list_delete(cal):
    rid = cal.run("create", {"title": "Call John", "remind_at": iso(timedelta(hours=1))})["id"]
    assert [r["title"] for r in cal.run("list", {})["reminders"]] == ["Call John"]
    assert cal.run("delete", {"id": rid}) == {"deleted": True}
    assert cal.run("delete", {"id": rid}) == {"deleted": False}
    assert cal.run("list", {})["reminders"] == []


def test_background_fires_due_once(cal, notified):
    cal.run("create", {"title": "Overdue", "remind_at": iso(-timedelta(seconds=1))})
    cal.run("create", {"title": "Future", "remind_at": iso(timedelta(hours=1))})
    cal.background()
    cal.background()
    assert notified == [("Reminder", "Overdue")]


def test_notify_failure_still_marks_fired(tmp_path):
    tool = CalendarTool()

    def boom(title, body):
        raise RuntimeError("push down")

    tool.setup(tmp_path / "c", boom)
    tool.run("create", {"title": "X", "remind_at": iso(-timedelta(seconds=1))})
    tool.background()
    assert tool.get_due() == []
```

- [ ] **Step 2: Run to verify failure**: `.venv/Scripts/python -m pytest tests/test_tools_base.py tests/test_calendar_tool.py -v`. Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement**

`localagent/agent/tools/base.py`:
```python
"""What a tool is: named actions with typed arguments, its own storage, an optional background job."""
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

Notify = Callable[[str, str], None]
PARAM_TYPES = ("str", "int", "iso-datetime")


@dataclass(frozen=True)
class Action:
    description: str
    params: dict = field(default_factory=dict)  # argument name -> "str" | "int" | "iso-datetime"
    kind: str = "read"                          # "read" results go back to the model; "write" changes data


class ToolArgsError(ValueError):
    pass


def _coerce(name: str, typ: str, value):
    if typ == "str":
        if not isinstance(value, str):
            raise ToolArgsError(f"'{name}' must be text")
        return value.strip()
    if typ == "int":
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().lstrip("-").isdigit():
            return int(value)
        raise ToolArgsError(f"'{name}' must be an integer")
    if typ == "iso-datetime":
        try:
            dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        except ValueError:
            raise ToolArgsError(f"'{name}' must be an ISO datetime like 2026-10-12T18:00:00") from None
        if dt.tzinfo is not None:
            dt = dt.astimezone().replace(tzinfo=None)  # store local, naive time
        return dt.isoformat(timespec="seconds")
    raise ToolArgsError(f"Unsupported parameter type '{typ}' for '{name}'")


def validate_args(action: Action, args) -> dict:
    if not isinstance(args, dict):
        raise ToolArgsError("args must be an object")
    unknown = set(args) - set(action.params)
    if unknown:
        raise ToolArgsError(f"Unknown argument(s): {', '.join(sorted(unknown))}")
    clean = {}
    for name, typ in action.params.items():
        if args.get(name) in (None, ""):
            raise ToolArgsError(f"Missing argument '{name}'")
        clean[name] = _coerce(name, typ, args[name])
    return clean


class Tool:
    name: str = ""
    compartment: str = "private"
    actions: dict = {}

    def setup(self, data_dir: Path, notify: Notify | None) -> None:
        """Called once with this tool's own data folder and a way to notify the owner."""

    def run(self, action: str, args: dict) -> dict:
        raise NotImplementedError

    def background(self) -> None:
        """Optional: called about once a minute by the owner server."""
```

`localagent/agent/tools/registry.py`:
```python
"""Load the tools enabled in agent.yaml. A tool is a package localagent/agent/tools/<name>/ exporting TOOL."""
import importlib
import re
from pathlib import Path

from localagent.agent.tools.base import Notify, Tool

_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
_SETTINGS = {"enabled", "compartment"}


class ToolConfigError(ValueError):
    pass


def load_tools(tools_config: dict, data_root: Path, notify: Notify | None,
               compartments: list[str]) -> dict[str, Tool]:
    tools = {}
    for name, cfg in (tools_config or {}).items():
        cfg = cfg or {}
        unknown = set(cfg) - _SETTINGS
        if unknown:
            raise ToolConfigError(f"Unknown setting(s) for tool '{name}': {', '.join(sorted(unknown))}")
        if not cfg.get("enabled", True):
            continue
        module_name = f"localagent.agent.tools.{name}"
        if not _NAME.match(name):
            raise ToolConfigError(f"Invalid tool name '{name}'")
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError as e:
            if e.name == module_name:
                raise ToolConfigError(f"Unknown tool '{name}' in agent.yaml (no folder localagent/agent/tools/{name}/)") from e
            raise
        tool = module.TOOL()
        tool.compartment = cfg.get("compartment", tool.compartment)
        if tool.compartment not in compartments:
            raise ToolConfigError(f"Tool '{name}' uses compartment '{tool.compartment}', "
                                  f"which is not in agent.yaml compartments {compartments}")
        tool.setup(Path(data_root) / name, notify)
        tools[name] = tool
    return tools
```

`localagent/agent/tools/calendar/__init__.py`:
```python
from localagent.agent.tools.calendar.tool import CalendarTool as TOOL

__all__ = ["TOOL"]
```

`localagent/agent/tools/calendar/tool.py`:
```python
"""Reminders in SQLite; due reminders are sent to the owner via notify()."""
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from localagent.agent.tools.base import Action, Tool

log = logging.getLogger(__name__)


class CalendarTool(Tool):
    name = "calendar"
    compartment = "private"
    actions = {
        "create": Action("Create a reminder", {"title": "str", "remind_at": "iso-datetime"}, kind="write"),
        "list": Action("List upcoming reminders with their ids, soonest first", {}, kind="read"),
        "delete": Action("Delete a reminder by its id", {"id": "int"}, kind="write"),
    }

    def __init__(self):
        self.db_path: Path | None = None
        self._notify = None

    def setup(self, data_dir, notify):
        Path(data_dir).mkdir(parents=True, exist_ok=True)
        self.db_path = Path(data_dir) / "calendar.db"
        self._notify = notify
        with self._db() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    remind_at TEXT NOT NULL,
                    fired INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now'))
                )
            """)

    @contextmanager
    def _db(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def create(self, title: str, remind_at: str) -> int:
        with self._db() as conn:
            return conn.execute("INSERT INTO reminders (title, remind_at) VALUES (?, ?)", (title, remind_at)).lastrowid

    def list_upcoming(self) -> list[dict]:
        with self._db() as conn:
            rows = conn.execute("SELECT id, title, remind_at FROM reminders WHERE fired=0 ORDER BY remind_at").fetchall()
            return [dict(r) for r in rows]

    def delete(self, id_: int) -> bool:
        with self._db() as conn:
            return conn.execute("DELETE FROM reminders WHERE id=?", (id_,)).rowcount > 0

    def get_due(self) -> list[dict]:
        now = datetime.now().isoformat()
        with self._db() as conn:
            rows = conn.execute("SELECT * FROM reminders WHERE fired=0 AND remind_at <= ?", (now,)).fetchall()
            return [dict(r) for r in rows]

    def mark_fired(self, id_: int) -> None:
        with self._db() as conn:
            conn.execute("UPDATE reminders SET fired=1 WHERE id=?", (id_,))

    def run(self, action: str, args: dict) -> dict:
        if action == "create":
            return {"id": self.create(args["title"], args["remind_at"])}
        if action == "list":
            return {"reminders": self.list_upcoming()}
        if action == "delete":
            return {"deleted": self.delete(args["id"])}
        raise ValueError(f"Unknown calendar action '{action}'")

    def background(self) -> None:
        for reminder in self.get_due():
            try:
                if self._notify:
                    self._notify("Reminder", reminder["title"])
            except Exception:
                log.exception("Could not send reminder %s", reminder["id"])
            self.mark_fired(reminder["id"])
```

- [ ] **Step 4: Run**: `.venv/Scripts/python -m pytest tests/test_tools_base.py tests/test_calendar_tool.py tests/test_layers.py -v`. Expected PASS.
- [ ] **Step 5: Leave uncommitted.**

---

### Task 6: Agent: tool-call parsing, prompt, core turn loop

**Files:**
- Create: `localagent/agent/toolcalls.py`, `prompt.py`, `core.py`
- Create: `tests/test_toolcalls.py`, `tests/test_agent_core.py`

**Interfaces:**
- Consumes:
  - From Task 4: `Session` methods, plus `WITHHELD`, `ScopeError`, `UnknownToolError` and `ToolView`.
  - From Task 5: `validate_args`, `ToolArgsError`, `Tool`.
  - From Task 2: `Backend`.
- Produces:
  - `ToolCall(name, action, args)`, `parse_tool_calls(text) -> (list[ToolCall], list[str])`, `strip_tool_tags(text) -> str`, and `VisibleText` (with `.feed(chunk) -> str` and `.flush() -> str`).
  - `build_system_prompt(items, tools, now) -> str`.
  - `ToolOutcome(name, action, ok, result, error, error_type, kind)`, where `error_type` is one of `unknown | denied | bad_args | failed | withheld`.
  - `Agent(backend, tools, *, model_id, max_new_tokens=256, history_turns=20, clock=datetime.now)` with `respond_stream(session, text) -> Iterator[str]`, `respond(session, text) -> str` and `run_tool(session, name, action, args) -> ToolOutcome`.
- Behaviour notes:
  - Round 1 may run tool calls. If any *read* call succeeded, its results go back to the model as a `user` message starting with `Tool results`, and round 2 runs. Using the `user` role instead of a `tool` role keeps this working with any chat template.
  - Tool calls emitted in round 2 are **not** executed, so the model can't create duplicates.
  - A failed tool call adds a short visible notice: `(Couldn't run calendar.create: ...)`.
  - Parse errors are only logged.

- [ ] **Step 1: Write failing tests**

`tests/test_toolcalls.py`:
```python
from localagent.agent.toolcalls import VisibleText, parse_tool_calls, strip_tool_tags

CREATE = '<tool>{"name":"calendar","action":"create","args":{"title":"X","remind_at":"2026-10-07T10:00:00"}}</tool>'


def test_parse_single_and_multiple():
    calls, errors = parse_tool_calls("Sure! " + CREATE + CREATE)
    assert len(calls) == 2 and errors == []
    assert calls[0].name == "calendar" and calls[0].args["title"] == "X"


def test_parse_missing_args_defaults_empty():
    calls, _ = parse_tool_calls('<tool>{"name":"calendar","action":"list"}</tool>')
    assert calls[0].args == {}


def test_parse_errors_collected():
    calls, errors = parse_tool_calls('<tool>not json</tool><tool>{"name":1}</tool><tool>{"name":"a","action":"b","args":[1]}</tool>')
    assert calls == [] and len(errors) == 3


def test_strip():
    assert strip_tool_tags("Done! " + CREATE) == "Done!"
    text = strip_tool_tags("Hello there " + CREATE + " how are you")
    assert "Hello there" in text and "how are you" in text and "<tool>" not in text


def test_unterminated_tag_hidden_and_not_executed():
    raw = 'Okay, setting it. <tool>{"name":"calendar","action":"create","args":{"title":"X'
    calls, errors = parse_tool_calls(raw)
    assert calls == [] and any("unterminated" in e for e in errors)
    assert strip_tool_tags(raw) == "Okay, setting it."


def test_visible_text_hides_tags_split_across_chunks():
    v = VisibleText()
    out = "".join(v.feed(c) for c in ["Sure ", "thing <to", 'ol>{"name":"x"}</tool>', " more"]) + v.flush()
    assert out == "Sure thing "


def test_visible_text_keeps_lookalikes():
    v = VisibleText()
    out = "".join(v.feed(c) for c in ["a <t", "able> b"]) + v.flush()
    assert out == "a <table> b"
```

`tests/test_agent_core.py`:
```python
import json
from datetime import datetime

import pytest

from localagent.agent.core import Agent
from localagent.agent.tools.registry import load_tools
from localagent.protocol.guard import Protocol
from localagent.protocol.scopes import Scope
from localagent.runtime.base import AdapterLoadError
from tests.fakes import FakeBackend

CREATE = '<tool>{"name":"calendar","action":"create","args":{"title":"Dentist","remind_at":"2030-01-01T10:00:00"}}</tool>'
LIST = '<tool>{"name":"calendar","action":"list"}</tool>'
NOW = datetime(2026, 10, 11, 9, 30)


@pytest.fixture
def env(tmp_path):
    (tmp_path / "knowledge/private").mkdir(parents=True)
    (tmp_path / "knowledge/private/me.md").write_text("Owner is called Ana.")
    tools = load_tools({"calendar": {}}, tmp_path / "data", None, ["private", "shared"])
    proto = Protocol.for_agent(tmp_path, ["private", "shared"], tools, owner_secret="t")
    return tmp_path, tools, proto


def make_agent(tools, replies, **kw):
    backend = FakeBackend(replies=replies, **kw)
    return Agent(backend, tools, model_id="org/model", history_turns=5, clock=lambda: NOW), backend


def test_plain_reply_records_memory(env):
    _, tools, proto = env
    agent, backend = make_agent(tools, ["Hello Ana!"])
    session = proto.open_owner_session("t")
    assert agent.respond(session, "hi") == "Hello Ana!"
    system = backend.calls[0][0]["content"]
    assert "Owner is called Ana." in system and "2026-10-11 09:30" in system and "calendar.create" in system
    assert session.history(5) == [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "Hello Ana!"}]


def test_write_tool_executed_and_hidden(env):
    _, tools, proto = env
    agent, backend = make_agent(tools, ["Reminder set! " + CREATE])
    reply = agent.respond(proto.open_owner_session("t"), "remind me")
    assert reply == "Reminder set!"
    assert [r["title"] for r in tools["calendar"].list_upcoming()] == ["Dentist"]
    assert len(backend.calls) == 1


def test_read_tool_gets_second_round(env):
    _, tools, proto = env
    tools["calendar"].create("Dentist", "2030-01-01T10:00:00")
    agent, backend = make_agent(tools, ["Let me check. " + LIST, "You have: Dentist."])
    reply = agent.respond(proto.open_owner_session("t"), "what reminders?")
    assert reply == "Let me check.\n\nYou have: Dentist."
    assert backend.calls[1][-1]["content"].startswith("Tool results")
    assert "Dentist" in backend.calls[1][-1]["content"]


def test_second_round_tool_calls_not_executed(env):
    _, tools, proto = env
    agent, backend = make_agent(tools, [LIST, "Done " + CREATE])
    agent.respond(proto.open_owner_session("t"), "x")
    assert tools["calendar"].list_upcoming() == []
    assert len(backend.calls) == 2


def test_unterminated_tag_not_executed(env):
    _, tools, proto = env
    agent, _ = make_agent(tools, ['Sure <tool>{"name":"calendar","action":"create","args":{"ti'])
    assert agent.respond(proto.open_owner_session("t"), "x") == "Sure"
    assert tools["calendar"].list_upcoming() == []


def test_bad_args_notice_shown(env):
    _, tools, proto = env
    bad = '<tool>{"name":"calendar","action":"create","args":{"title":"X","remind_at":"someday"}}</tool>'
    agent, _ = make_agent(tools, ["Ok " + bad])
    reply = agent.respond(proto.open_owner_session("t"), "x")
    assert "Couldn't run calendar.create" in reply


def test_stream_never_shows_tags(env):
    _, tools, proto = env
    agent, _ = make_agent(tools, ["Reminder set! " + CREATE])
    chunks = list(agent.respond_stream(proto.open_owner_session("t"), "x"))
    assert "<tool" not in "".join(chunks) and "".join(chunks).strip() == "Reminder set!"


def test_history_included_next_turn(env):
    _, tools, proto = env
    agent, backend = make_agent(tools, ["one", "two"])
    session = proto.open_owner_session("t")
    agent.respond(session, "first")
    agent.respond(session, "second")
    assert [m["content"] for m in backend.calls[1][1:]] == ["first", "one", "second"]


def test_run_tool_outcomes(env):
    tmp_path, tools, proto = env
    agent, _ = make_agent(tools, [])
    owner = proto.open_owner_session("t")
    assert agent.run_tool(owner, "calendar", "list", {}).ok
    assert agent.run_tool(owner, "email", "send", {}).error_type == "unknown"
    assert agent.run_tool(owner, "calendar", "delete", {"id": "x"}).error_type == "bad_args"
    limited = proto._session("peer:x", Scope(["tool:calendar:list"]), "peer:x")
    assert agent.run_tool(limited, "calendar", "create", {"title": "a", "remind_at": "2030-01-01"}).error_type == "denied"
    assert agent.run_tool(limited, "calendar", "list", {}).error_type == "withheld"


def test_adapter_failure_refuses_turn(env):
    tmp_path, tools, proto = env
    (tmp_path / "training/adapters/org--model/private").mkdir(parents=True)
    agent, backend = make_agent(tools, ["never"], fail_adapters=True)
    with pytest.raises(AdapterLoadError):
        agent.respond(proto.open_owner_session("t"), "x")
    assert backend.calls == []


def test_adapters_loaded_for_session(env):
    tmp_path, tools, proto = env
    (tmp_path / "training/adapters/org--model/private").mkdir(parents=True)
    agent, backend = make_agent(tools, ["hi"])
    agent.respond(proto.open_owner_session("t"), "x")
    assert [p.name for p in backend.adapters] == ["private"]
```

- [ ] **Step 2: Run to verify failure**: `.venv/Scripts/python -m pytest tests/test_toolcalls.py tests/test_agent_core.py -v`. Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement**

`localagent/agent/toolcalls.py`:
```python
"""The model-agnostic tool-call format: <tool>{"name":..,"action":..,"args":{..}}</tool> after the reply."""
import json
import re
from dataclasses import dataclass, field

OPEN = "<tool>"
_TAG = re.compile(r"<tool>(.*?)</tool>", re.DOTALL)


@dataclass(frozen=True)
class ToolCall:
    name: str
    action: str
    args: dict = field(default_factory=dict)


def parse_tool_calls(text: str) -> tuple[list[ToolCall], list[str]]:
    calls, errors = [], []
    for match in _TAG.finditer(text):
        body = match.group(1).strip()
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            errors.append(f"invalid JSON in tool tag: {body[:80]}")
            continue
        args = data.get("args") if isinstance(data, dict) else None
        if args is None:
            args = {}
        if (not isinstance(data, dict) or not isinstance(data.get("name"), str)
                or not isinstance(data.get("action"), str) or not isinstance(args, dict)):
            errors.append(f"tool tag needs string name/action and object args: {body[:80]}")
            continue
        calls.append(ToolCall(data["name"], data["action"], args))
    if OPEN in _TAG.sub("", text):
        errors.append("unterminated <tool> tag (reply cut off?)")
    return calls, errors


def strip_tool_tags(text: str) -> str:
    text = _TAG.sub("", text)
    cut = text.find(OPEN)
    if cut >= 0:
        text = text[:cut]
    return text.strip()


class VisibleText:
    """Streaming filter: passes text through until the first <tool> tag, then hides the rest."""

    def __init__(self):
        self._buf = ""
        self._hidden = False

    def feed(self, chunk: str) -> str:
        if self._hidden:
            return ""
        self._buf += chunk
        cut = self._buf.find(OPEN)
        if cut >= 0:
            out, self._buf, self._hidden = self._buf[:cut], "", True
            return out
        keep = next((k for k in range(min(len(OPEN) - 1, len(self._buf)), 0, -1)
                     if OPEN.startswith(self._buf[-k:])), 0)
        out = self._buf[:len(self._buf) - keep]
        self._buf = self._buf[len(self._buf) - keep:]
        return out

    def flush(self) -> str:
        out = "" if self._hidden else self._buf
        self._buf = ""
        return out
```

`localagent/agent/prompt.py`:
```python
"""Builds the system prompt from what the session allows. No tool-specific text lives here."""
from datetime import datetime

BASE_PROMPT = "You are a helpful local AI assistant running on your owner's own computer."

TOOLS_INTRO = """You can use tools. To use one, put a tool tag at the very END of your reply, after your normal answer:

<tool>{"name":"<tool>","action":"<action>","args":{...}}</tool>

Rules:
- One tag per action; several tags are fine.
- Never put tags in the middle of your answer.
- Use exactly the argument names listed. Dates and times are ISO 8601, e.g. 2026-10-12T18:00:00.
- After a "read" action you will receive the result and can then answer with the real data.

Available tools:"""


def build_system_prompt(items: list, tools: list, now: datetime) -> str:
    sections = [
        BASE_PROMPT,
        f"Current date and time: {now:%Y-%m-%d %H:%M} ({now:%A}). "
        f"Use it to interpret relative times like \"tomorrow at 6pm\".",
    ]
    if tools:
        lines = [TOOLS_INTRO]
        for view in tools:
            for action_name, action in view.actions.items():
                params = ", ".join(f'"{p}": <{t}>' for p, t in action.params.items())
                lines.append(f"- {view.name}.{action_name} ({action.kind}): {action.description}. "
                             f"args: {{{params}}}")
        sections.append("\n".join(lines))
    knowledge = [i.content for i in items if i.kind == "knowledge"]
    if knowledge:
        sections.append("What you know:\n\n" + "\n\n".join(knowledge))
    work = [i.content for i in items if i.kind == "work" and i.content.get("status") == "active"]
    if work:
        sections.append("Current work:\n\n" + "\n\n".join(f"## {w['title']}\n{w['body']}".strip() for w in work))
    return "\n\n".join(sections)
```

`localagent/agent/core.py`:
```python
"""One conversation turn: prompt -> model -> tool calls (checked by the session) -> reply -> memory."""
import json
import logging
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Iterator

from localagent.agent.prompt import build_system_prompt
from localagent.agent.toolcalls import VisibleText, parse_tool_calls, strip_tool_tags
from localagent.agent.tools.base import ToolArgsError, validate_args
from localagent.protocol.session import WITHHELD, ScopeError, Session, UnknownToolError
from localagent.runtime.base import Backend

log = logging.getLogger(__name__)
MAX_ROUNDS = 2


@dataclass
class ToolOutcome:
    name: str
    action: str
    ok: bool
    result: object = None
    error: str = ""
    error_type: str = ""  # unknown | denied | bad_args | failed | withheld
    kind: str = ""

    def as_record(self) -> dict:
        return {"name": self.name, "action": self.action, "ok": self.ok, "error": self.error}


def _results_message(outcomes: list[ToolOutcome]) -> str:
    lines = [f"{o.name}.{o.action}: {json.dumps(o.result, ensure_ascii=False, default=str)}" for o in outcomes]
    return "Tool results (use them to answer my previous message):\n" + "\n".join(lines)


class Agent:
    def __init__(self, backend: Backend, tools: dict, *, model_id: str, max_new_tokens: int = 256,
                 history_turns: int = 20, clock=datetime.now):
        self.backend = backend
        self.tools = tools
        self.model_id = model_id
        self.max_new_tokens = max_new_tokens
        self.history_turns = history_turns
        self._clock = clock
        self._lock = threading.Lock()  # one model: one turn at a time

    def run_tool(self, session: Session, name: str, action: str, args: dict) -> ToolOutcome:
        try:
            session.check_tool_call(name, action)
        except UnknownToolError as e:
            return ToolOutcome(name, action, False, error=str(e), error_type="unknown")
        except ScopeError as e:
            return ToolOutcome(name, action, False, error=str(e), error_type="denied")
        tool = self.tools.get(name)
        if tool is None:
            return ToolOutcome(name, action, False, error=f"Tool '{name}' is not loaded", error_type="unknown")
        spec = tool.actions[action]
        try:
            clean = validate_args(spec, args)
        except ToolArgsError as e:
            return ToolOutcome(name, action, False, error=str(e), error_type="bad_args", kind=spec.kind)
        try:
            result = tool.run(action, clean)
        except Exception as e:
            log.exception("Tool %s.%s failed", name, action)
            return ToolOutcome(name, action, False, error=str(e), error_type="failed", kind=spec.kind)
        result = session.filter_tool_result(name, result)
        if result is WITHHELD:
            return ToolOutcome(name, action, False, error=WITHHELD["withheld"], error_type="withheld", kind=spec.kind)
        return ToolOutcome(name, action, True, result=result, kind=spec.kind)

    def _turn(self, session: Session, user_message: str) -> Generator[str, None, str]:
        """Yields visible text as it is generated; returns the reply that was recorded to memory."""
        with self._lock:
            self.backend.set_adapters(session.adapters(self.model_id))
            system = build_system_prompt(session.context(), session.tools(), self._clock())
            messages = ([{"role": "system", "content": system}]
                        + session.history(self.history_turns)
                        + [{"role": "user", "content": user_message}])
            texts, outcomes, shown = [], [], False
            for round_no in range(1, MAX_ROUNDS + 1):
                if round_no > 1 and shown:
                    yield "\n\n"
                visible, parts = VisibleText(), []
                for chunk in self.backend.generate_stream(messages, self.max_new_tokens):
                    parts.append(chunk)
                    out = visible.feed(chunk)
                    if out:
                        shown = True
                        yield out
                tail = visible.flush()
                if tail:
                    shown = True
                    yield tail
                raw = "".join(parts)
                texts.append(strip_tool_tags(raw))
                calls, errors = parse_tool_calls(raw)
                for error in errors:
                    log.warning("Ignored tool call: %s", error)
                if round_no == MAX_ROUNDS:
                    if calls:
                        log.warning("Ignored %d tool call(s) in the final round", len(calls))
                    break
                round_outcomes = [self.run_tool(session, c.name, c.action, c.args) for c in calls]
                outcomes += round_outcomes
                failed = [o for o in round_outcomes if not o.ok]
                if failed:
                    notice = "\n".join(f"(Couldn't run {o.name}.{o.action}: {o.error})" for o in failed)
                    yield ("\n\n" if shown else "") + notice
                    shown = True
                    texts.append(notice)
                reads = [o for o in round_outcomes if o.ok and o.kind == "read"]
                if not reads:
                    break
                messages = messages + [{"role": "assistant", "content": raw},
                                       {"role": "user", "content": _results_message(reads)}]
            reply = "\n\n".join(t for t in texts if t)
            session.record({"user": user_message, "assistant": reply,
                            "tool_calls": [o.as_record() for o in outcomes]})
            return reply

    def respond_stream(self, session: Session, user_message: str) -> Iterator[str]:
        yield from self._turn(session, user_message)

    def respond(self, session: Session, user_message: str) -> str:
        # Returns the recorded reply (tags stripped, rounds joined), not the raw streamed text
        turn = self._turn(session, user_message)
        while True:
            try:
                next(turn)
            except StopIteration as done:
                return done.value
```
(Import `Generator` from `typing` alongside `Iterator`.)

- [ ] **Step 4: Run**: `.venv/Scripts/python -m pytest tests/test_toolcalls.py tests/test_agent_core.py tests/test_layers.py -v`. Expected PASS.
- [ ] **Step 5: Leave uncommitted.**

---

### Task 7: Connect (owner server, terminal, push), bootstrap, CLI, training dataset

**Files:**
- Move: `static/*` → `localagent/connect/owner/static/`
- Create: `localagent/connect/owner/push.py`, `server.py`, `terminal.py`
- Create: `localagent/bootstrap.py`, `localagent/__main__.py`, `localagent/training/dataset.py`
- Create: `tests/test_push.py` (replaces old), `tests/test_owner_server.py`, `tests/test_bootstrap.py`, `tests/test_dataset.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `PushDispatcher(subs_path, private_key="", public_key="", claims_email="admin@localhost")` with `.register(sub)` and `.send(title, body)`.
  - `create_app(*, protocol, agent, push, tools, run_scheduler=True) -> FastAPI`.
  - `run_terminal(protocol, agent, secret)`.
  - `Services(config, backend, protocol, agent, tools, push)` and `build_services(config, backend=None) -> Services`.
  - `main(argv=None) -> int`.
  - `validate_example(ex) -> dict`, `make_example(messages, source="manual") -> dict`, `InvalidExample`.
- REST status mapping: unknown → 404, denied → 403, withheld → 403, bad_args → 422, failed → 500. A GET on a write action returns 405.

- [ ] **Step 1: Write failing tests**

`tests/test_push.py`:
```python
from unittest.mock import patch

from localagent.connect.owner.push import PushDispatcher

SUB = {"endpoint": "https://example.com/push/123", "keys": {"auth": "a", "p256dh": "b"}}


def test_register_dedup_and_persist(tmp_path):
    p = PushDispatcher(tmp_path / "subs.json", private_key="k")
    p.register(SUB)
    p.register(SUB)
    assert len(PushDispatcher(tmp_path / "subs.json").subscriptions) == 1


def test_send_calls_webpush(tmp_path):
    p = PushDispatcher(tmp_path / "subs.json", private_key="k", claims_email="a@b.c")
    p.register(SUB)
    with patch("localagent.connect.owner.push.webpush") as wp:
        p.send("T", "B")
    assert wp.called and wp.call_args.kwargs["vapid_claims"] == {"sub": "mailto:a@b.c"}


def test_send_without_key_is_noop(tmp_path):
    p = PushDispatcher(tmp_path / "subs.json")
    p.register(SUB)
    with patch("localagent.connect.owner.push.webpush") as wp:
        p.send("T", "B")
    assert not wp.called
```

`tests/test_owner_server.py`:
```python
import json

import pytest
from fastapi.testclient import TestClient

from localagent.agent.core import Agent
from localagent.agent.tools.registry import load_tools
from localagent.connect.owner.push import PushDispatcher
from localagent.connect.owner.server import create_app
from localagent.protocol.guard import Protocol
from tests.fakes import FakeBackend

TOKEN = "test-secret-token"
CREATE = '<tool>{"name":"calendar","action":"create","args":{"title":"Dentist","remind_at":"2030-01-01T10:00:00"}}</tool>'


@pytest.fixture
def setup(tmp_path):
    push = PushDispatcher(tmp_path / "data/push_subscriptions.json", public_key="test-public-key")
    tools = load_tools({"calendar": {}}, tmp_path / "data", push.send, ["private", "shared"])
    protocol = Protocol.for_agent(tmp_path, ["private", "shared"], tools, owner_secret=TOKEN)
    backend = FakeBackend(replies=["Reminder set! " + CREATE])
    agent = Agent(backend, tools, model_id="org/model")
    app = create_app(protocol=protocol, agent=agent, push=push, tools=tools, run_scheduler=False)
    with TestClient(app) as client:
        yield client, tools


def auth(token=TOKEN):
    return {"Authorization": f"Bearer {token}"}


def test_tools_require_auth(setup):
    client, _ = setup
    assert client.get("/api/tools/calendar/list").status_code == 401
    assert client.get("/api/tools/calendar/list", headers=auth("wrong")).status_code == 401


def test_calendar_crud(setup):
    client, _ = setup
    assert client.get("/api/tools/calendar/list", headers=auth()).json() == {"reminders": []}
    r = client.post("/api/tools/calendar/create", headers=auth(), json={"title": "Call John", "remind_at": "2030-10-07T15:00:00"})
    assert r.status_code == 200
    rid = r.json()["id"]
    assert client.get("/api/tools/calendar/list", headers=auth()).json()["reminders"][0]["title"] == "Call John"
    assert client.post("/api/tools/calendar/delete", headers=auth(), json={"id": rid}).json() == {"deleted": True}


@pytest.mark.parametrize("method, path, body, status", [
    ("get", "/api/tools/email/send", None, 404),
    ("get", "/api/tools/calendar/create", None, 405),
    ("post", "/api/tools/calendar/create", {"title": "x"}, 422),
])
def test_tool_errors(setup, method, path, body, status):
    client, _ = setup
    kwargs = {"headers": auth()} | ({"json": body} if body is not None else {})
    assert getattr(client, method)(path, **kwargs).status_code == status


def test_websocket_chat_creates_reminder(setup):
    client, tools = setup
    with client.websocket_connect(f"/ws?token={TOKEN}") as ws:
        ws.send_text("remind me")
        text = ""
        while True:
            msg = json.loads(ws.receive_text())
            if msg["type"] == "done":
                break
            text += msg["text"]
    assert text.strip() == "Reminder set!"
    assert [r["title"] for r in tools["calendar"].list_upcoming()] == ["Dentist"]


def test_websocket_bad_token(setup):
    client, _ = setup
    with pytest.raises(Exception):
        with client.websocket_connect("/ws?token=wrong") as ws:
            ws.receive_text()


def test_push_endpoints(setup):
    client, _ = setup
    assert client.get("/api/push/vapid-public-key").json() == {"key": "test-public-key"}
    r = client.post("/api/push/register", headers=auth(),
                    json={"endpoint": "https://push.example.com/1", "keys": {"auth": "a", "p256dh": "b"}})
    assert r.json() == {"registered": True}


def test_root_serves_html(setup):
    client, _ = setup
    r = client.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
```

`tests/test_bootstrap.py`:
```python
import pytest

from localagent.__main__ import main
from localagent.bootstrap import build_services
from localagent.config import load_config
from tests.fakes import FakeBackend, write_agent_yaml


def test_build_services_with_fake_backend(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENT_SECRET", raising=False)
    d = write_agent_yaml(tmp_path / "a")
    (d / ".env").write_text("AGENT_SECRET=abc\nVAPID_PRIVATE_KEY=vapid_private.pem\n")
    (d / "vapid_private.pem").write_text("x")
    s = build_services(load_config(d), backend=FakeBackend(replies=["hi"]))
    assert list(s.tools) == ["calendar"]
    assert s.push.private_key == str(d / "vapid_private.pem")
    session = s.protocol.open_owner_session("abc")
    assert s.agent.respond(session, "hello") == "hi"


def test_main_reports_missing_agent(tmp_path, capsys):
    assert main(["chat", "--agent", str(tmp_path / "none")]) == 2
    assert "new_agent.py" in capsys.readouterr().err


def test_main_reports_bad_policy(tmp_path, capsys):
    d = write_agent_yaml(tmp_path / "a")
    (d / "policy.yaml").write_text("owner: [everything]\n")
    assert main(["chat", "--agent", str(d)]) == 2
    assert "everything" in capsys.readouterr().err
```

`tests/test_dataset.py`:
```python
import pytest

from localagent.training.dataset import InvalidExample, make_example, validate_example


def test_make_example():
    ex = make_example([{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}], source="memory:x#1")
    assert ex["source"] == "memory:x#1" and "added" in ex and validate_example(ex) == ex


@pytest.mark.parametrize("ex", [
    {},
    {"messages": []},
    {"messages": [{"role": "user", "content": "a"}]},
    {"messages": [{"role": "robot", "content": "a"}, {"role": "assistant", "content": "b"}]},
    {"messages": [{"role": "user", "content": 1}, {"role": "assistant", "content": "b"}]},
])
def test_invalid(ex):
    with pytest.raises(InvalidExample):
        validate_example(ex)
```

- [ ] **Step 2: Run to verify failure**: `.venv/Scripts/python -m pytest tests/test_push.py tests/test_owner_server.py tests/test_bootstrap.py tests/test_dataset.py -v`. Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement**

Move the PWA: `static/index.html`, `sw.js`, `manifest.json`, `icon.png` → `localagent/connect/owner/static/` (URLs stay `/static/...`).

`localagent/connect/owner/push.py`:
```python
"""Web Push to the owner's devices (VAPID). Used as the tools' notify() channel."""
import json
from pathlib import Path

from pywebpush import WebPushException, webpush


class PushDispatcher:
    def __init__(self, subs_path: Path, private_key: str = "", public_key: str = "",
                 claims_email: str = "admin@localhost"):
        self.subs_path = Path(subs_path)
        self.private_key = private_key
        self.public_key = public_key
        self.claims_email = claims_email
        self.subscriptions: list[dict] = self._load()

    def _load(self) -> list[dict]:
        if self.subs_path.exists():
            return json.loads(self.subs_path.read_text(encoding="utf-8"))
        return []

    def _save(self) -> None:
        self.subs_path.parent.mkdir(parents=True, exist_ok=True)
        self.subs_path.write_text(json.dumps(self.subscriptions, indent=2), encoding="utf-8")

    def register(self, subscription: dict) -> None:
        endpoint = subscription.get("endpoint")
        if not any(s.get("endpoint") == endpoint for s in self.subscriptions):
            self.subscriptions.append(subscription)
            self._save()

    def send(self, title: str, body: str) -> None:
        if not self.private_key:
            return
        payload = json.dumps({"title": title, "body": body})
        failed = []
        for sub in self.subscriptions:
            try:
                webpush(subscription_info=sub, data=payload, vapid_private_key=self.private_key,
                        vapid_claims={"sub": f"mailto:{self.claims_email}"})
            except WebPushException:
                failed.append(sub.get("endpoint"))
        if failed:
            self.subscriptions = [s for s in self.subscriptions if s.get("endpoint") not in failed]
            self._save()
```

`localagent/connect/owner/server.py`:
```python
"""Owner transport: phone/PC web app over WebSocket, tool REST API, push registration."""
import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from localagent.protocol.guard import AuthError

log = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).parent / "static"
STATUS = {"unknown": 404, "denied": 403, "withheld": 403, "bad_args": 422, "failed": 500}


class PushSubscription(BaseModel):
    endpoint: str
    keys: dict


def _run_background(tools: dict) -> None:
    for name, tool in tools.items():
        try:
            tool.background()
        except Exception:
            log.exception("Background job of tool %s failed", name)


async def _stream_reply(agent, session, text: str):
    """Run the blocking agent turn in a thread and yield its chunks as they arrive."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def worker():
        try:
            for chunk in agent.respond_stream(session, text):
                loop.call_soon_threadsafe(queue.put_nowait, chunk)
        except Exception as e:
            log.exception("Turn failed")
            loop.call_soon_threadsafe(queue.put_nowait, f"\n[error] {e}")
        loop.call_soon_threadsafe(queue.put_nowait, None)

    loop.run_in_executor(None, worker)
    while (chunk := await queue.get()) is not None:
        yield chunk


def create_app(*, protocol, agent, push, tools: dict, run_scheduler: bool = True) -> FastAPI:
    bearer = HTTPBearer(auto_error=False)

    @asynccontextmanager
    async def lifespan(app):
        scheduler = None
        if run_scheduler:
            scheduler = BackgroundScheduler()
            scheduler.add_job(_run_background, "interval", minutes=1, args=[tools])
            scheduler.start()
        yield
        if scheduler:
            scheduler.shutdown()

    app = FastAPI(lifespan=lifespan)

    def owner_session(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        try:
            return protocol.open_owner_session(credentials.credentials if credentials else "")
        except AuthError:
            raise HTTPException(status_code=401)

    # ── Chat ────────────────────────────────────────────────────────────────

    @app.websocket("/ws")
    async def websocket_chat(ws: WebSocket, token: str = ""):
        try:
            session = protocol.open_owner_session(token)
        except AuthError:
            await ws.close(code=1008)
            return
        await ws.accept()
        try:
            while True:
                text = await ws.receive_text()
                async for chunk in _stream_reply(agent, session, text):
                    await ws.send_text(json.dumps({"type": "chunk", "text": chunk}))
                await ws.send_text(json.dumps({"type": "done"}))
        except WebSocketDisconnect:
            pass
        finally:
            session.close()

    # ── Tools ───────────────────────────────────────────────────────────────

    def _call(session, name: str, action: str, args: dict):
        try:
            outcome = agent.run_tool(session, name, action, args)
        finally:
            session.close()
        if not outcome.ok:
            raise HTTPException(status_code=STATUS[outcome.error_type], detail=outcome.error)
        return outcome.result

    @app.get("/api/tools/{name}/{action}")
    async def tool_get(name: str, action: str, request: Request, session=Depends(owner_session)):
        spec = getattr(tools.get(name), "actions", {}).get(action)
        if spec is not None and spec.kind != "read":
            session.close()
            raise HTTPException(status_code=405, detail="Use POST for actions that change data")
        return await run_in_threadpool(_call, session, name, action, dict(request.query_params))

    @app.post("/api/tools/{name}/{action}")
    async def tool_post(name: str, action: str, request: Request, session=Depends(owner_session)):
        body = await request.body()
        try:
            args = json.loads(body) if body else {}
        except json.JSONDecodeError:
            session.close()
            raise HTTPException(status_code=422, detail="Body must be JSON")
        return await run_in_threadpool(_call, session, name, action, args)

    # ── Push ────────────────────────────────────────────────────────────────

    @app.post("/api/push/register")
    async def register_push(sub: PushSubscription, session=Depends(owner_session)):
        session.close()
        push.register(sub.model_dump())
        return {"registered": True}

    @app.get("/api/push/vapid-public-key")
    async def vapid_public_key():
        return {"key": push.public_key}

    # ── PWA ─────────────────────────────────────────────────────────────────

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    async def serve_pwa():
        return FileResponse(STATIC_DIR / "index.html")

    return app
```

`localagent/connect/owner/terminal.py`:
```python
"""Owner transport: chat from the terminal."""
from localagent.protocol.guard import AuthError


def run_terminal(protocol, agent, secret: str) -> int:
    try:
        session = protocol.open_owner_session(secret)
    except AuthError as e:
        print(f"Error: {e}")
        return 2
    print("Agent ready. Type 'exit' or Ctrl+C to quit. Type 'reset' to clear the conversation.\n")
    try:
        while True:
            try:
                text = input("You: ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\nGoodbye.")
                return 0
            if not text:
                continue
            if text.lower() == "exit":
                print("Goodbye.")
                return 0
            if text.lower() == "reset":
                session.reset_history()
                print("Conversation cleared (it stays saved in memory/).\n")
                continue
            print("Agent: ", end="", flush=True)
            try:
                for chunk in agent.respond_stream(session, text):
                    print(chunk, end="", flush=True)
            except Exception as e:
                print(f"\n[error] {e}")
            print("\n")
    finally:
        session.close()
```

`localagent/bootstrap.py`:
```python
"""Wires the layers together for one agent folder. Not a layer itself."""
from dataclasses import dataclass
from pathlib import Path

from localagent.agent.core import Agent
from localagent.agent.tools.registry import load_tools
from localagent.config import AgentConfig, ensure_hf_home
from localagent.connect.owner.push import PushDispatcher
from localagent.protocol.guard import Protocol
from localagent.runtime.base import Backend
from localagent.runtime.factory import create_backend


@dataclass
class Services:
    config: AgentConfig
    backend: Backend
    protocol: Protocol
    agent: Agent
    tools: dict
    push: PushDispatcher


def _resolve_key(value: str, agent_dir: Path) -> str:
    """VAPID_PRIVATE_KEY may be a path relative to the agent folder."""
    if value and not Path(value).is_absolute() and (agent_dir / value).is_file():
        return str(agent_dir / value)
    return value


def build_services(config: AgentConfig, backend: Backend | None = None) -> Services:
    push = PushDispatcher(
        subs_path=config.agent_dir / "data" / "push_subscriptions.json",
        private_key=_resolve_key(config.get_env("VAPID_PRIVATE_KEY"), config.agent_dir),
        public_key=config.get_env("VAPID_PUBLIC_KEY"),
        claims_email=config.get_env("VAPID_CLAIMS_EMAIL", "admin@localhost"),
    )
    tools = load_tools(config.tools, config.agent_dir / "data", push.send, config.compartments)
    protocol = Protocol.for_agent(config.agent_dir, config.compartments, tools,
                                  owner_secret=config.get_env("AGENT_SECRET"))
    if backend is None:  # load the model last: config errors above surface in seconds, not minutes
        ensure_hf_home()
        backend = create_backend(config.model.backend)
        backend.load(config.model.id, config.model.quantization)
    agent = Agent(backend, tools, model_id=config.model.id, max_new_tokens=config.model.max_new_tokens,
                  history_turns=config.history_turns)
    return Services(config, backend, protocol, agent, tools, push)
```

`localagent/__main__.py`:
```python
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
```

`localagent/training/dataset.py`:
```python
"""Training example format: one JSON object per line in training/<compartment>/examples.jsonl.
Plain chat messages, so the same data trains any model."""
from datetime import datetime

ROLES = {"system", "user", "assistant"}


class InvalidExample(ValueError):
    pass


def validate_example(example) -> dict:
    if not isinstance(example, dict) or not isinstance(example.get("messages"), list) or not example["messages"]:
        raise InvalidExample("an example needs a non-empty 'messages' list")
    for m in example["messages"]:
        if not isinstance(m, dict) or m.get("role") not in ROLES or not isinstance(m.get("content"), str):
            raise InvalidExample(f"bad message {m!r}: needs role in {sorted(ROLES)} and text content")
    roles = {m["role"] for m in example["messages"]}
    if not {"user", "assistant"} <= roles:
        raise InvalidExample("an example needs at least one user and one assistant message")
    return example


def make_example(messages: list[dict], source: str = "manual") -> dict:
    return validate_example({"messages": messages, "source": source,
                             "added": datetime.now().isoformat(timespec="seconds")})
```

- [ ] **Step 4: Run**: `.venv/Scripts/python -m pytest tests/test_push.py tests/test_owner_server.py tests/test_bootstrap.py tests/test_dataset.py tests/test_layers.py -v`. Expected PASS.
- [ ] **Step 5: Leave uncommitted.**

---

### Task 8: Agent template, `create_agent`, migration, scripts

**Files:**
- Create: `agent_template/agent.yaml`, `agent_template/policy.yaml`, `agent_template/README.md`, `.gitkeep` files in `knowledge/private`, `knowledge/shared`, `memory`, `work`, `training`, `data`
- Create: `localagent/setup_agent.py`, `scripts/new_agent.py`, `scripts/migrate_legacy.py`, `scripts/diagnose.py`
- Modify: `scripts/smoke_test_model.py`, `scripts/benchmark.py`, `scripts/start_server.bat`
- Delete: `scripts/diagnose_gpu.py`
- Create: `tests/test_setup_agent.py`

**Interfaces:**
- Produces: `create_agent(agent_dir, *, model=None, env_values=None) -> str` (agent id), `set_model(agent_yaml, model)`, `migrate_legacy(repo_root, agent_dir, dry_run=False) -> list[str]`.

- [ ] **Step 1: Write failing tests** — `tests/test_setup_agent.py`:
```python
import pytest
from dotenv import dotenv_values

from localagent.config import load_config
from localagent.setup_agent import create_agent, migrate_legacy


def test_create_agent(tmp_path):
    d = tmp_path / "bob"
    agent_id = create_agent(d, model={"id": "Qwen/Qwen2.5-1.5B-Instruct", "quantization": "fp16"})
    cfg = load_config(d)
    assert cfg.name == "bob"
    assert (cfg.model.id, cfg.model.quantization) == ("Qwen/Qwen2.5-1.5B-Instruct", "fp16")
    env = dotenv_values(d / ".env")
    assert len(env["AGENT_SECRET"]) == 64
    assert env["VAPID_PRIVATE_KEY"] == "vapid_private.pem" and (d / "vapid_private.pem").is_file()
    assert len(env["VAPID_PUBLIC_KEY"]) == 87
    assert (d / "identity/agent.pub").read_text().strip() == agent_id
    assert (d / "knowledge/private").is_dir() and (d / "knowledge/shared").is_dir()


def test_create_agent_refuses_existing(tmp_path):
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "file").write_text("keep me")
    with pytest.raises(FileExistsError):
        create_agent(tmp_path / "x")


def _legacy_repo(root):
    (root / "knowledge/private").mkdir(parents=True)
    (root / "knowledge/public").mkdir(parents=True)
    (root / "knowledge/private/about.md").write_text("ME")
    (root / "knowledge/public/greeting.md").write_text("HI")
    (root / "calendar.db").write_bytes(b"db")
    (root / "push_subscriptions.json").write_text("[]")
    (root / ".vapid_private.pem").write_text("PEM")
    (root / ".env").write_text(
        f"HF_HOME=x\nAGENT_SECRET=legacysecret\nVAPID_PRIVATE_KEY={root / '.vapid_private.pem'}\n"
        "VAPID_PUBLIC_KEY=legacypub\nVAPID_CLAIMS_EMAIL=me@x.com\nMODEL_ID=Qwen/Qwen2.5-1.5B-Instruct\nUSE_4BIT=0\n"
    )
    return root


def test_migrate(tmp_path):
    root = _legacy_repo(tmp_path / "repo")
    d = root / "my-agent"
    actions = migrate_legacy(root, d)
    assert (d / "knowledge/private/about.md").read_text() == "ME"
    assert (d / "knowledge/shared/greeting.md").read_text() == "HI"
    assert (d / "data/calendar/calendar.db").read_bytes() == b"db"
    assert (d / "data/push_subscriptions.json").exists()
    assert (d / "vapid_private.pem").read_text() == "PEM"
    env = dotenv_values(d / ".env")
    assert env["AGENT_SECRET"] == "legacysecret" and env["VAPID_PUBLIC_KEY"] == "legacypub"
    assert env["VAPID_PRIVATE_KEY"] == "vapid_private.pem"
    cfg = load_config(d)
    assert (cfg.model.id, cfg.model.quantization) == ("Qwen/Qwen2.5-1.5B-Instruct", "fp16")
    assert not (root / "knowledge").exists() and not (root / "calendar.db").exists()
    assert (root / ".env").exists()  # left for the owner to delete
    assert actions


def test_migrate_dry_run_changes_nothing(tmp_path):
    root = _legacy_repo(tmp_path / "repo")
    actions = migrate_legacy(root, root / "my-agent", dry_run=True)
    assert all(a.startswith(("[dry-run]", "SKIP", "NOTE")) for a in actions)
    assert not (root / "my-agent").exists() and (root / "calendar.db").exists()


def test_migrate_never_overwrites(tmp_path):
    root = _legacy_repo(tmp_path / "repo")
    d = root / "my-agent"
    create_agent(d)
    (d / "knowledge/private/about.md").write_text("NEWER")
    actions = migrate_legacy(root, d)
    assert (d / "knowledge/private/about.md").read_text() == "NEWER"
    assert (root / "knowledge/private/about.md").exists()
    assert any(a.startswith("SKIP") and "about.md" in a for a in actions)
    assert any(a.startswith("SKIP") and "AGENT_SECRET" in a for a in actions)
```

- [ ] **Step 2: Run to verify failure**: `.venv/Scripts/python -m pytest tests/test_setup_agent.py -v`. Expected ModuleNotFoundError.

- [ ] **Step 3: Implement**

`agent_template/agent.yaml`:
```yaml
# Your agent's settings. Secrets live in .env next to this file, never here.
name: my-agent

model:
  id: Qwen/Qwen2.5-3B-Instruct   # any HuggingFace chat/instruct model id
  backend: transformers          # transformers (NVIDIA/CPU) | llamacpp, mlx (coming later)
  quantization: 4bit             # 4bit | fp16 | none
  max_new_tokens: 256            # longest reply, in tokens

# Data compartments. 'private' = only you. 'shared' = may be offered to connected agents.
# Add your own (lowercase, digits, '-'), e.g. family, work.
compartments: [private, shared]

tools:
  calendar:
    enabled: true
    compartment: private         # whose eyes the reminders are for

memory:
  history_turns: 20              # how many past turns the model sees each message

server:
  host: 127.0.0.1                # keep local; reach it from outside via Cloudflare Tunnel
  port: 8000
```

`agent_template/policy.yaml`:
```yaml
# Who may see what. Scopes: all, knowledge:<c>, memory:<c>, work:<c>, adapter:<c>,
# tool:<name>, tool:<name>:<action>. Peer connections arrive in a later version.
owner: [all]
default_peer: [knowledge:shared, adapter:shared]
peers: {}
```

`agent_template/README.md`:
```markdown
# Agent folder

Everything that makes this agent *yours*. Never commit it or share it.

| Path | What goes there |
|---|---|
| `agent.yaml` | model and settings |
| `policy.yaml` | who may see what |
| `.env` | secrets (`AGENT_SECRET`, push keys) |
| `identity/` | this agent's keypair; `agent.pub` is its id |
| `knowledge/<compartment>/` | `.md` / `.txt` facts the agent always knows |
| `memory/` | conversation logs, written automatically |
| `work/` | one `.md` per active task, with a `compartment:` / `status:` header |
| `training/` | curated examples and trained adapters |
| `data/` | tool storage (calendar database, push subscriptions) |
| `audit.log` | sessions and refused requests |
```

`localagent/setup_agent.py`:
```python
"""Create agent folders from agent_template/ and migrate the pre-restructure layout."""
import base64
import re
import secrets
import shutil
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from dotenv import dotenv_values

from localagent.config import REPO_ROOT
from localagent.protocol.identity import generate_identity

TEMPLATE_DIR = REPO_ROOT / "agent_template"
SECRET_KEYS = ("AGENT_SECRET", "VAPID_PRIVATE_KEY", "VAPID_PUBLIC_KEY", "VAPID_CLAIMS_EMAIL")
VAPID_FILE = "vapid_private.pem"


def _generate_vapid(agent_dir: Path) -> dict:
    key = ec.generate_private_key(ec.SECP256R1())
    (agent_dir / VAPID_FILE).write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
    public = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return {"VAPID_PRIVATE_KEY": VAPID_FILE,
            "VAPID_PUBLIC_KEY": base64.urlsafe_b64encode(public).rstrip(b"=").decode()}


def _write_env(path: Path, values: dict) -> None:
    lines = ["# Secrets for this agent. Never commit or share this file."]
    lines += [f"{k}={v}" for k, v in values.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def set_model(agent_yaml: Path, model: dict) -> None:
    """Rewrite values inside the model: block, keeping comments."""
    text = agent_yaml.read_text(encoding="utf-8")
    for key, value in model.items():
        text = re.sub(rf"(?m)^(  {key}:\s*)\S+", lambda m: f"{m.group(1)}{value}", text, count=1)
    agent_yaml.write_text(text, encoding="utf-8")


def create_agent(agent_dir: Path, *, model: dict | None = None, env_values: dict | None = None) -> str:
    agent_dir = Path(agent_dir)
    if agent_dir.exists() and any(agent_dir.iterdir()):
        raise FileExistsError(f"{agent_dir} already exists and is not empty")
    shutil.copytree(TEMPLATE_DIR, agent_dir, dirs_exist_ok=True)
    yaml_path = agent_dir / "agent.yaml"
    yaml_path.write_text(re.sub(r"(?m)^name:.*$", f"name: {agent_dir.name}", yaml_path.read_text(encoding="utf-8"),
                                count=1), encoding="utf-8")
    if model:
        set_model(yaml_path, model)
    env = {"AGENT_SECRET": secrets.token_hex(32), "VAPID_CLAIMS_EMAIL": "you@example.com"}
    provided = dict(env_values or {})
    if not (provided.get("VAPID_PRIVATE_KEY") and provided.get("VAPID_PUBLIC_KEY")):
        env.update(_generate_vapid(agent_dir))
    env.update(provided)
    _write_env(agent_dir / ".env", env)
    return generate_identity(agent_dir / "identity")


def migrate_legacy(repo_root: Path, agent_dir: Path, dry_run: bool = False) -> list[str]:
    repo_root, agent_dir = Path(repo_root), Path(agent_dir)
    actions: list[str] = []
    tag = "[dry-run] " if dry_run else ""

    legacy = {k: v for k, v in dotenv_values(repo_root / ".env").items() if v} if (repo_root / ".env").exists() else {}
    env_values = {k: legacy[k] for k in SECRET_KEYS if k in legacy}
    moves: list[tuple[Path, Path]] = []
    key_path = Path(legacy.get("VAPID_PRIVATE_KEY", ""))
    if legacy.get("VAPID_PRIVATE_KEY") and key_path.is_file():
        moves.append((key_path, agent_dir / VAPID_FILE))
        env_values["VAPID_PRIVATE_KEY"] = VAPID_FILE

    model = {}
    if legacy.get("MODEL_ID"):
        model["id"] = legacy["MODEL_ID"]
    if "USE_4BIT" in legacy:
        model["quantization"] = "fp16" if legacy["USE_4BIT"] == "0" else "4bit"
    if legacy.get("MAX_NEW_TOKENS", "").isdigit():
        model["max_new_tokens"] = legacy["MAX_NEW_TOKENS"]

    if not (agent_dir / "agent.yaml").exists():
        actions.append(f"{tag}create agent folder {agent_dir} (model settings and secrets from the old .env)")
        if not dry_run:
            create_agent(agent_dir, model=model, env_values=env_values)
    else:
        current = dotenv_values(agent_dir / ".env") if (agent_dir / ".env").exists() else {}
        missing = {k: v for k, v in env_values.items() if not current.get(k)}
        for k in env_values:
            if k not in missing:
                actions.append(f"SKIP .env {k}: already set in {agent_dir / '.env'}")
        if missing:
            actions.append(f"{tag}add {', '.join(missing)} to {agent_dir / '.env'}")
            if not dry_run:
                with (agent_dir / ".env").open("a", encoding="utf-8") as fh:
                    fh.writelines(f"{k}={v}\n" for k, v in missing.items())

    for sub, target in (("private", "private"), ("public", "shared")):
        folder = repo_root / "knowledge" / sub
        if folder.is_dir():
            moves += [(f, agent_dir / "knowledge" / target / f.name) for f in sorted(folder.iterdir()) if f.is_file()]
    moves += [(repo_root / "calendar.db", agent_dir / "data" / "calendar" / "calendar.db"),
              (repo_root / "push_subscriptions.json", agent_dir / "data" / "push_subscriptions.json")]

    for src, dst in moves:
        if not src.exists():
            continue
        if dst.exists() and not (src == key_path and dst.read_bytes() == src.read_bytes()):
            actions.append(f"SKIP {src} -> {dst}: target already exists")
            continue
        actions.append(f"{tag}move {src} -> {dst}")
        if not dry_run:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))

    if not dry_run:
        for folder in (repo_root / "knowledge/private", repo_root / "knowledge/public", repo_root / "knowledge"):
            if folder.is_dir() and not any(folder.iterdir()):
                folder.rmdir()
                actions.append(f"remove empty folder {folder}")
    if legacy:
        actions.append(f"NOTE {repo_root / '.env'} is no longer used; delete it once the agent works")
    return actions
```
> When the agent folder already exists and the VAPID key path in it equals the legacy file's target, the move is skipped as a normal conflict.

`scripts/new_agent.py`:
```python
"""Create your agent folder: python scripts/new_agent.py [--agent my-agent] [--no-detect]"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from localagent.config import DEFAULT_AGENT_DIR  # noqa: E402
from localagent.setup_agent import create_agent  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--agent", default=str(DEFAULT_AGENT_DIR), help="folder to create")
    p.add_argument("--no-detect", action="store_true", help="skip hardware detection, keep template model")
    args = p.parse_args()

    model = None
    if not args.no_detect:
        from localagent.runtime.hardware import detect
        info = detect()
        gpu = info["gpu"]
        print(f"Hardware: {info['os']} | RAM {info['ram_gb']} GB | GPU: "
              f"{gpu['name'] + ' ' + str(gpu['vram_gb']) + ' GB' if gpu else 'none'}")
        if info["backend_available"]:
            model = {"id": info["recommended_model"], "backend": info["recommended_backend"],
                     "quantization": info["recommended_quantization"]}
            print(f"Recommended: {model['id']} ({model['quantization']}) on {model['backend']}")
        else:
            print(f"Recommended backend '{info['recommended_backend']}' is not available yet; "
                  f"keeping the template default (transformers). It will run, but slowly without an NVIDIA GPU.")
    try:
        agent_id = create_agent(Path(args.agent), model=model)
    except FileExistsError as e:
        print(f"Error: {e}")
        return 1
    print(f"\nCreated agent at {args.agent}\nAgent id: {agent_id}")
    print("Next: edit agent.yaml if you like, add facts to knowledge/private/, then run:")
    print(f"  python -m localagent chat --agent \"{args.agent}\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

`scripts/migrate_legacy.py`:
```python
"""Move pre-restructure data (knowledge/, calendar.db, .env secrets...) into an agent folder.
Usage: python scripts/migrate_legacy.py [--agent my-agent] [--dry-run]"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from localagent.config import DEFAULT_AGENT_DIR  # noqa: E402
from localagent.setup_agent import migrate_legacy  # noqa: E402

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--agent", default=str(DEFAULT_AGENT_DIR))
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    for line in migrate_legacy(ROOT, Path(args.agent), dry_run=args.dry_run):
        print(line)
```

`scripts/diagnose.py`:
```python
"""Hardware report + recommendation; with --load, also loads the agent's model and checks where it lives.
Usage: python scripts/diagnose.py [--load] [--agent my-agent]"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from localagent.runtime.hardware import detect  # noqa: E402

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--load", action="store_true")
    p.add_argument("--agent")
    args = p.parse_args()
    print(json.dumps(detect(), indent=2))
    if args.load:
        import time
        from localagent.config import ensure_hf_home, load_config, resolve_agent_dir
        from localagent.runtime.factory import create_backend
        cfg = load_config(resolve_agent_dir(args.agent))
        ensure_hf_home()
        backend = create_backend(cfg.model.backend)
        t = time.perf_counter()
        backend.load(cfg.model.id, cfg.model.quantization)
        print(f"Loaded {cfg.model.id} in {time.perf_counter() - t:.1f}s")
        model = getattr(backend, "model", None)
        if model is not None:
            print("Parameter devices:", sorted({str(q.device) for q in model.parameters()}))
        print(backend.info())
```

`scripts/smoke_test_model.py` (replace content):
```python
"""Load the agent's configured model and say hello. Usage: python scripts/smoke_test_model.py [--agent DIR]"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from localagent.config import ensure_hf_home, load_config, resolve_agent_dir  # noqa: E402
from localagent.runtime.factory import create_backend  # noqa: E402

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--agent")
    cfg = load_config(resolve_agent_dir(p.parse_args().agent))
    ensure_hf_home()
    backend = create_backend(cfg.model.backend)
    print(f"Loading {cfg.model.id} ({cfg.model.quantization})...")
    backend.load(cfg.model.id, cfg.model.quantization)
    print(backend.generate([{"role": "user", "content": "Say hello in one sentence."}], 50))
```

`scripts/benchmark.py` changes:
- Replace `load_dotenv(ROOT / ".env")` with `from localagent.config import ensure_hf_home` and `ensure_hf_home()`.
- Replace `from agent.session import SessionContext` with imports of `build_system_prompt`, `ToolView` and `CalendarTool`.
- Replace the `system = SessionContext(...)` line with `system = build_system_prompt([], [ToolView("calendar", CalendarTool.actions)], datetime.now())`.

`scripts/start_server.bat`:
```bat
@echo off
cd /d "%~dp0.."
call .venv\Scripts\activate
python -m localagent serve
```

Delete `scripts/diagnose_gpu.py`.

- [ ] **Step 4: Run**: `.venv/Scripts/python -m pytest tests/test_setup_agent.py -v` and `.venv/Scripts/python scripts/new_agent.py --agent <scratch>/demo --no-detect`. Expected: PASS, and a demo folder is created.
- [ ] **Step 5: Leave uncommitted.**

---

### Task 9: Remove the legacy layout, docs, full verification, migrate owner data

**Files:**
- Delete: `agent/`, `main.py`, `server.py`, `static/` (already moved), `tests/test_calendar.py`, `tests/test_calendar_actions.py`, `tests/test_core.py`, `tests/test_server.py`, `docs/Running.md`
- Modify: `.env.example` (one line pointing to `my-agent/.env` and `scripts/new_agent.py`)
- Create: `docs/architecture.md`, `docs/guide/01-requirements.md` … `07-connect-to-others.md`, `docs/guide/README.md`

- [ ] **Step 1:** Delete the legacy files listed above.
- [ ] **Step 2:** Run the whole suite: `.venv/Scripts/python -m pytest -q`. Expected: all pass, and no test imports the old `agent` package.
- [ ] **Step 3:** Write `docs/architecture.md` covering:
  - the layer diagram and import-rules table (copied from spec §2);
  - a one-turn data flow (the steps of spec §8.1);
  - the scopes table;
  - the **tool data rule**: a tool result is visible only with `knowledge:<tool compartment>`;
  - the agent folder tree;
  - how to add a tool, with a minimal code example;
  - how to add a backend.

  Then write the guide pages named in spec §11. The Mac/CPU install pages and pages 06/07 are explicit "coming later" stubs that say what will be there. `02-install-nvidia.md` carries over the content of `docs/Setup/2026-10-05-model-install-run.md`, with the machine-specific paths generalized. `04-run-and-phone.md` carries over the running, Cloudflare and PWA parts of `Running.md`, with the new commands and routes.
- [ ] **Step 4:** Migrate the owner's data:
  1. Run `.venv/Scripts/python scripts/migrate_legacy.py --dry-run` and read the output.
  2. Run it without `--dry-run`.
  3. Run `python -m localagent chat --help` and check that `load_config(my-agent)` loads.
  4. Don't load the model unless the owner asks.
- [ ] **Step 5:** Run `git status` to confirm `my-agent/` is ignored and nothing is staged. Leave everything uncommitted.
