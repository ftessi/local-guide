# Local Agent Ecosystem — Restructure Design Spec
Date: 2026-10-11
Supersedes the file layout (§3) of `2026-10-05-local-agent-protocol-design.md`. The protocol concepts of that spec (purpose, offered/requested/granted scope, no mid-session scope expansion, dual-layer enforcement) still apply and are extended here.

---

## 1. Purpose

A group of people will each run their own local AI agent, train it on their own data, and later connect the agents to each other through a zero-trust protocol. This project reshapes the repository so that:

1. **Everyone runs the same code.** One shared repo; each person's agent lives in a personal, gitignored folder.
2. **The model is swappable.** Changing the model is a one-line config change; knowledge, memory, work, tools, policy and training data stay exactly the same.
3. **Data protection is a separate layer.** The protocol is not only agent↔agent messaging — it is the guard that decides what any session (including the owner's) and any training run may see. The agent never reads data directly.
4. **Training is compartmentalized.** One base model per agent; each data compartment trains its own LoRA adapter; the guard decides which adapters load per session, so private data cannot leak through the weights.
5. **Mixed hardware is supported.** One runtime interface with swappable backends (Transformers/NVIDIA now; llama.cpp/CPU and MLX/Mac later).

### Audience
Participants are developers or comfortable with a terminal. The guide is clear step-by-step commands per machine type; no one-click installer.

### Success criteria
- A new participant can follow `docs/guide/` on Windows+NVIDIA and end with a running agent in their own `my-agent/` folder.
- Changing `model:` in `agent.yaml` and restarting is the only step needed to switch models.
- Adding a tool requires only a new folder under `localagent/agent/tools/` and enabling it in `agent.yaml`.
- Automated tests prove: an out-of-scope session never sees private text in its prompt; `training_set("shared")` never contains private examples; layer import rules hold.
- The owner's current knowledge, reminders and push subscriptions survive migration.

---

## 2. Layers and dependency rules

```
connect/     transports: owner server (PWA, push, terminal), agent↔agent network
   │
protocol/    THE GUARD: labels, scopes, policy, sessions, handshake, audit
   │
   ├──► agent/      chat loop + tools; sees only what a session gives it
   ├──► training/   builds datasets only through protocol, trains per compartment
   │
vault/       passive labeled storage of the agent folder
runtime/     the model behind one interface
```

Allowed imports (enforced by `tests/test_layers.py`, which parses imports of every module):

| Layer | May import |
|---|---|
| `runtime` | nothing from `localagent` |
| `vault` | nothing from `localagent` |
| `protocol` | `vault` |
| `agent` | `protocol` (session objects only), `runtime` (Backend interface only) |
| `training` | `protocol`, `runtime` |
| `connect` | `protocol`, `agent`, `runtime` |

`agent` and `training` must never import `vault`.

---

## 3. Repository layout

```
LocalAgent/                          # shared repo
├── localagent/
│   ├── __main__.py                  # python -m localagent {serve|chat} [--agent DIR]
│   ├── config.py                    # loads agent.yaml + agent .env → AgentConfig
│   ├── runtime/
│   │   ├── base.py                  # Backend protocol
│   │   ├── transformers_backend.py  # NVIDIA / CUDA (from today's agent/llm.py)
│   │   ├── factory.py               # backend name → class
│   │   └── hardware.py              # detect GPU/VRAM/OS/RAM → recommendation
│   ├── vault/
│   │   └── store.py
│   ├── protocol/
│   │   ├── labels.py
│   │   ├── scopes.py
│   │   ├── policy.py
│   │   ├── session.py
│   │   ├── identity.py              # agent keypair
│   │   ├── audit.py
│   │   └── handshake.py             # stub; peer sub-project
│   ├── agent/
│   │   ├── core.py
│   │   ├── prompt.py
│   │   ├── toolcalls.py             # parse/strip <tool> tags
│   │   └── tools/
│   │       ├── base.py              # Tool, Action
│   │       ├── registry.py
│   │       └── calendar/
│   │           ├── __init__.py
│   │           └── tool.py
│   ├── training/
│   │   └── dataset.py               # example format + read/write helpers
│   └── connect/
│       ├── owner/
│       │   ├── server.py            # FastAPI app (from today's server.py)
│       │   ├── terminal.py          # REPL (from today's main.py)
│       │   ├── push.py              # Web Push (from today's agent/push.py)
│       │   └── static/              # PWA (from today's static/)
│       └── peer/                    # empty; peer sub-project
├── agent_template/                  # skeleton copied to create an agent
├── my-agent/                        # personal agent folder — gitignored
├── models/                          # shared HuggingFace cache (HF_HOME) — gitignored
├── scripts/
│   ├── new_agent.py                 # copy template, generate keypair + AGENT_SECRET
│   ├── migrate_legacy.py            # move pre-restructure data into my-agent/
│   ├── diagnose.py                  # hardware report + recommendation (replaces diagnose_gpu.py)
│   ├── smoke_test_model.py          # reads model from agent.yaml
│   ├── benchmark.py                 # reads model from agent.yaml unless --model given
│   └── start_server.bat
├── tests/                           # mirrors localagent/
└── docs/
    ├── guide/                       # public setup guide
    ├── architecture.md              # one-page layer overview
    ├── design/                      # specs
    ├── plans/                       # implementation plans (history)
    └── Setup/                       # owner's machine-specific logs (history)
```

Removed from the root: `main.py`, `server.py`, `agent/`, `static/`, `knowledge/`, `calendar.db`, `push_subscriptions.json`, `.vapid_private.pem` (moved into `my-agent/`).

---

## 4. The agent folder

```
my-agent/
├── agent.yaml
├── policy.yaml
├── .env                       # secrets only: AGENT_SECRET, VAPID_*
├── identity/
│   ├── agent.key              # private key (Ed25519)
│   └── agent.pub              # public key = agent id
├── knowledge/
│   ├── private/*.md|*.txt
│   └── shared/*.md|*.txt
├── memory/<compartment>/<YYYY-MM-DD>.jsonl
├── work/<item>.md
├── training/
│   ├── <compartment>/examples.jsonl
│   └── adapters/<model-id-slug>/<compartment>/
├── data/<tool-name>/           # tool storage (calendar/calendar.db)
├── data/push_subscriptions.json
└── audit.log
```

### `agent.yaml`
```yaml
name: my-agent
model:
  id: Qwen/Qwen2.5-3B-Instruct
  backend: transformers          # transformers | llamacpp | mlx (latter two: future)
  quantization: 4bit             # 4bit | fp16 | none
  max_new_tokens: 256
compartments: [private, shared]  # user may add more (e.g. family, work)
tools:
  calendar:
    enabled: true
    compartment: private         # overrides the tool's default
memory:
  history_turns: 20              # last N turns loaded into the prompt
server:
  host: 127.0.0.1
  port: 8000
```

`HF_HOME` defaults to `<repo>/models` and can be overridden in the environment.

### Choosing the agent folder
`--agent DIR` on the CLI, else the `LOCALAGENT_DIR` environment variable, else `./my-agent`. If the folder doesn't exist, the program exits with a message pointing to `scripts/new_agent.py`.

---

## 5. Runtime

```python
class Backend(Protocol):
    def load(self, model_id: str, quantization: str) -> None: ...
    def generate(self, messages: list[dict], max_new_tokens: int) -> str: ...
    def generate_stream(self, messages: list[dict], max_new_tokens: int) -> Iterator[str]: ...
    def set_adapters(self, paths: list[Path]) -> None: ...   # activate exactly these; [] = base model
    def info(self) -> dict: ...                              # model_id, backend, device, active adapters
```

- `transformers_backend.py` is today's `LLMEngine` behind this interface. `set_adapters` uses `peft` when paths are given; with `[]` it runs the base model. `peft` is only imported when adapters are actually used.
- `set_adapters` raises `AdapterLoadError` on any failure and leaves no adapter active. It never substitutes a different set.
- `hardware.py` returns `{os, cpu, ram_gb, gpu: {vendor, name, vram_gb} | None, recommended_backend, recommended_model}` using `torch` when installed, else `nvidia-smi` / `platform` fallbacks.
- A fake backend in `tests/` implements the interface; a shared contract test suite runs against every backend class that can be loaded in the test environment (in CI: the fake only).

---

## 6. Vault

Passive, labeled storage over the agent folder. Makes no access decisions.

```python
@dataclass
class Item:
    kind: str           # knowledge | memory | work | training
    compartment: str
    id: str             # relative path or record id
    content: str | dict

class Vault:
    def __init__(self, agent_dir: Path, compartments: list[str]): ...
    def read(self, kind: str, compartments: list[str]) -> list[Item]: ...
    def append_memory(self, compartment: str, record: dict) -> None: ...
    def write_training_examples(self, compartment: str, examples: list[dict]) -> None: ...
```

How items get their labels:

| Kind | Label source |
|---|---|
| knowledge | folder name under `knowledge/` |
| memory | the session that wrote it; owner → `private`, peer → `peer:<id>` |
| work | `compartment:` field in the item's YAML front matter; missing → `private` |
| training | folder name under `training/` |
| tool data | the tool's compartment (from `agent.yaml` or the tool default) |

- Unknown compartment folders (not in `agent.yaml`) are ignored and logged as a warning.
- `peer:*` memory is never copied into training by any automatic path.

---

## 7. Protocol — the guard

### 7.1 Scope vocabulary

| Scope | Grants |
|---|---|
| `knowledge:<c>` | knowledge items in compartment `c` in the prompt |
| `memory:<c>` | memory items in compartment `c` |
| `work:<c>` | work items in compartment `c` |
| `tool:<name>` | every action of a tool |
| `tool:<name>:<action>` | one action |
| `adapter:<c>` | the LoRA adapter for compartment `c` may load |
| `all` | every scope (owner only) |

### 7.2 Policy (`policy.yaml`)
```yaml
owner: [all]
default_peer: [knowledge:shared, adapter:shared]
peers: {}            # <agent-pub-key>: [scopes...]
```
Missing file → the defaults above. Unknown scope strings fail loading with a clear error.

### 7.3 Session
```python
class Session:
    principal: str                  # "owner" | "peer:<id>"
    scope: frozenset[str]
    memory_compartment: str         # where this session's turns are recorded

    def context(self) -> list[Item]                      # knowledge + work + memory within scope
    def history(self, n: int) -> list[dict]              # last n turns of this session's own memory compartment
    def tools(self) -> list[ToolDescription]             # only actions within scope
    def check_tool_call(self, name: str, action: str)    # raises ScopeError + audit entry if denied
    def filter_tool_result(self, tool, result) -> result | Withheld  # withheld if tool compartment not in scope
    def adapters(self, model_id: str) -> list[Path]      # existing adapter dirs for allowed compartments
    def record(self, turn: dict) -> None                 # vault.append_memory(self.memory_compartment, ...)
```

```python
class Protocol:
    def __init__(self, vault: Vault, policy: Policy, audit: Audit, tool_registry): ...
    def open_owner_session(self, token: str) -> Session      # checks AGENT_SECRET; raises AuthError
    def training_set(self, compartment: str) -> list[dict]   # ONLY examples labeled exactly `compartment`
```

`open_peer_session` / handshake: interface stubbed, raises `NotImplementedError`; peer sub-project.

### 7.4 Identity
`scripts/new_agent.py` generates an Ed25519 keypair (`cryptography` package) into `identity/`. The public key (base64url) is the agent id. It is created now so the id is stable before peer connections exist.

### 7.5 Audit
`audit.log` (JSON lines): session opened (principal, scope), session closed, every denied tool call or withheld tool result, adapter load failures. Never logs message content.

---

## 8. Agent

### 8.1 Turn flow (`core.py`)
1. `session.adapters(model_id)` → `backend.set_adapters(...)` if different from what's active. On `AdapterLoadError`: the turn fails with an error message to the transport; nothing else loads.
2. Build messages: system prompt from `prompt.build(session.context(), session.tools(), now)`, then `session.history(n)`, then the user message.
3. Generate (streamed).
4. Parse `<tool>` calls. For each: `session.check_tool_call` → run the action → `session.filter_tool_result`.
5. If any executed action has `kind="read"`, append the results as a `tool` message and generate once more. At most 2 generation rounds per turn.
6. Strip tags; return clean text; `session.record(...)` the user message, the final reply and the tool calls.

A process-wide lock means one turn runs at a time (single model, adapters switch between turns).

### 8.2 Tool-call format
```
<tool>{"name":"calendar","action":"create","args":{"title":"Call mom","remind_at":"2026-10-12T18:00:00"}}</tool>
```
Placed after the natural-language reply. Invalid JSON, an unknown tool/action, or args that fail validation → ignored and logged (not shown to the user).

### 8.3 Prompt (`prompt.py`)
- A base prompt with no tool-specific text, plus the current date/time.
- A "Tools" section generated from `session.tools()`: name, action, description, argument schema, and the call format.
- A "Knowledge" section from `knowledge` items, then a "Current work" section from `work` items with `status: active`.

### 8.4 Tools
```python
@dataclass
class Action:
    description: str
    params: dict[str, type | str]
    kind: Literal["read", "write"]

class Tool:
    name: str
    compartment: str = "private"
    actions: dict[str, Action]
    def setup(self, data_dir: Path, notify: Callable[[str, str], None]) -> None: ...
    def run(self, action: str, args: dict) -> dict: ...
    def background(self) -> None: ...      # optional; called every minute by the scheduler
```

- `registry.py` loads the tools enabled in `agent.yaml`.
- The scheduler (APScheduler) lives in `connect/owner/server.py` and calls each tool's `background()`.
- **Calendar port:** same SQLite schema, moved to `my-agent/data/calendar/calendar.db`. Actions: `create` (write), `list` (read), `delete` (write). `background()` fires due reminders through `notify()`.

---

## 9. Training (skeleton only)

- Dataset format, one JSON object per line in `training/<c>/examples.jsonl`:
  `{"messages": [{"role": "...", "content": "..."}], "source": "memory:<file>#<n>" | "manual", "added": "<iso>"}`
- `localagent/training/dataset.py`: validate and read/write examples.
- `Protocol.training_set(c)` is the only read path for training.
- Adapter location convention: `training/adapters/<model-id-slug>/<c>/` (slug: `/` → `--`). `Session.adapters()` already loads them if present.
- Curation and training scripts are out of scope (see §13).

---

## 10. Connect

### 10.1 Owner server (`connect/owner/server.py`)
- WebSocket `/ws?token=` → `open_owner_session(token)` → per-connection agent turns. The message protocol to the PWA is unchanged (`chunk` / `done`).
- REST: `GET|POST /api/tools/{name}/{action}` with `Authorization: Bearer`. Each request opens an owner session and goes through `check_tool_call`. Today's `/api/calendar` routes become `/api/tools/calendar/list|create|delete`; the PWA is updated to match.
- Push: `/api/push/register`, `/api/push/vapid-public-key` are unchanged; push is wired as the `notify` callback for tools.
- Static PWA served from `connect/owner/static/`.

### 10.2 Terminal (`connect/owner/terminal.py`)
Today's `main.py` REPL, now through an owner session. Tool calls are executed here too, so reminders work from the terminal.

### 10.3 Peer (`connect/peer/`)
Empty package; peer sub-project.

### 10.4 Entry point
```
python -m localagent serve [--agent DIR]
python -m localagent chat  [--agent DIR]
```
`scripts/start_server.bat` calls `serve`.

---

## 11. Documentation

- `docs/guide/`:
  1. `01-requirements.md`: hardware paths (NVIDIA / Mac / CPU-only) and how to choose
  2. `02-install-nvidia.md` (full), `02-install-mac.md` and `02-install-cpu.md` (stubs pointing to future backends)
  3. `03-create-your-agent.md`: `new_agent.py`, `agent.yaml`, `policy.yaml`
  4. `04-run-and-phone.md`: serve, chat, Cloudflare tunnel, PWA
  5. `05-teach-it.md`: knowledge, compartments, tools
  6. `06-train-it.md`: stub
  7. `07-connect-to-others.md`: stub
- `docs/architecture.md`: layers, dependency rules, data flow of one turn, scopes table.
- Content of `docs/Running.md` is split into the guide and the architecture page; `Running.md` is removed.
- `docs/Setup/`, `docs/plans/` and the older `docs/design/` specs stay as history.

---

## 12. Migration

`scripts/migrate_legacy.py [--agent my-agent] [--dry-run]`:
1. If the agent folder doesn't exist, create it from `agent_template/` (including a new keypair).
2. Move `knowledge/private/*` → `my-agent/knowledge/private/` and `knowledge/public/*` → `my-agent/knowledge/shared/`.
3. Move `calendar.db` → `my-agent/data/calendar/calendar.db` and `push_subscriptions.json` → `my-agent/data/`.
4. Move secrets from the root `.env` (`AGENT_SECRET`, `VAPID_*`) → `my-agent/.env`; move `MODEL_ID` / `USE_4BIT` / `MAX_NEW_TOKENS` → `agent.yaml`.
5. Never overwrite existing files in the target; report conflicts and skip them.
6. Print every action taken.

`models/` stays in place as the shared cache.

---

## 13. Out of scope (separate specs later)

1. Per-OS setup scripts; llama.cpp and MLX backends.
2. Training: `curate.py` (review memory → examples), `train.py` (peft / mlx-lm LoRA per compartment).
3. Peer protocol: handshake, signed messages, transport, protocol v0.2 spec.
4. Memory summaries; work-item tools.

---

## 14. Dependencies added

- `pyyaml` (`agent.yaml`, `policy.yaml`, work front matter)
- `cryptography` (agent keypair)
- `peft`: optional; only imported when an adapter is loaded

---

## 15. Testing

The model is always mocked or faked; no test loads real weights.

| Test file | Covers |
|---|---|
| `test_layers.py` | import rules from §2 |
| `test_runtime_contract.py` | fake backend against the Backend interface; `set_adapters` failure semantics |
| `test_vault.py` | labeling rules; unknown compartments ignored |
| `test_policy.py` | policy loading, defaults, unknown scopes rejected |
| `test_session.py` | context filtering; `check_tool_call`; `filter_tool_result`; adapters per scope; record compartment |
| `test_guard.py` | private text never in a non-private session's prompt; `training_set("shared")` has no private or peer examples; denials audited |
| `test_agent_core.py` | tool-call parsing, read-action second round, 2-round cap, tag stripping, history from memory |
| `test_calendar_tool.py` | ported calendar tests |
| `test_owner_server.py` | ported server tests against the new routes |
| `test_migrate_legacy.py` | moves, no-overwrite, dry run |
