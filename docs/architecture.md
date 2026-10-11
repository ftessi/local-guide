# Architecture

One shared core (`localagent/`), installable tools and connections in a separate repo ([`local-guide-extensions`](https://github.com/ftessi/local-guide-extensions)), and one personal folder per agent (`my-agent/`, gitignored). The model is swappable; everything else stays the same. The repo map and how-tos are in the [README](../README.md).

Design spec: [`design/2026-10-11-ecosystem-restructure-design.md`](design/2026-10-11-ecosystem-restructure-design.md).

## Layers

```
connect/     transports: terminal built in; phone app, tunnel, agent↔agent network installed
   │
protocol/    THE GUARD: labels, scopes, policy, sessions, handshake, audit
   │
   ├──► agent/      chat loop + tools; sees only what a session gives it
   ├──► training/   builds datasets only through protocol, trains per compartment
   │
vault/       passive labeled storage of the agent folder
runtime/     the model behind one interface
```

| Layer | Does | May import |
|---|---|---|
| `runtime` | Loads a model, generates text, activates LoRA adapters | nothing in `localagent` |
| `vault` | Reads/writes the agent folder; every item has a compartment label | nothing in `localagent` |
| `protocol` | Decides who sees what: sessions, scopes, policy, audit, training sets | `vault` |
| `agent` | One conversation turn; tools | `protocol.session`, `runtime.base` |
| `training` | Dataset format (training runs come later) | `protocol`, `runtime` |
| `connect` | Connection interface, `serve` loop, terminal; installed connections plug in here | `protocol`, `agent`, `runtime` |

`tests/test_layers.py` fails if any import breaks these rules. Outside the layers: `config.py` (reads `agent.yaml`, `installables.yaml`, `.env`), `extensions.py` and `installer.py` (find, load and install tools/connections), `bootstrap.py` (wires layers and extensions for one agent), `setup_agent.py` (creates agent folders), `testing.py` (FakeBackend), `__main__.py` (CLI).

Installed tools and connections are outside the package. They may import the interfaces they implement (`localagent.agent.tools.base`, `localagent.connect.base`) and, for connections, `protocol` and `agent`, the same as the `connect` layer.

## One turn, step by step

1. A transport (the terminal, or an installed connection such as the phone app) opens a **session** with the protocol. The owner session = token check + `owner` scope from `policy.yaml`.
2. `Agent._turn` asks the session which **adapters** may load and tells the runtime (`set_adapters`). If that fails, the turn is refused; it never silently runs with a different set.
3. The system prompt is built from `session.context()` (knowledge + active work in scope) and `session.tools()` (only allowed actions), plus the date/time and a table of the next 7 days (small models get weekday arithmetic wrong).
4. History = `session.history(n)`: this session's own memory compartment only.
5. The model streams its reply. `VisibleText` hides everything from the first `<tool>` (or `<tool_call>`) tag, so tags are never shown, even when split across chunks. The runtime stops generation at end-of-turn *and* turn-start tokens, so the model can't invent the user's next message.
6. Each `<tool>{...}</tool>` call goes through `session.check_tool_call`, then the arguments are validated, then the tool runs, then `session.filter_tool_result`. Parsing is lenient on purpose: a missing `</tool>`, a `"name":"calendar.create"` or an `arguments` key are accepted, because real small models write them.
7. If a **read** action succeeded, its results go back to the model for one more round (max 2 rounds). Calls in the final round are ignored, so the model can't duplicate writes.
8. The turn is recorded with `session.record` → `memory/<compartment>/<date>.jsonl`: `assistant` (what the user saw, failure notices included) and `transcript` (what the model said, with well-formed tags for the calls that worked, and the tool results). History replays the model's own words and working tags but not the tool results: shown those, small models start writing fake results instead of calling the tool.

## Scopes

| Scope | Grants |
|---|---|
| `all` | everything (owner) |
| `knowledge:<c>` | knowledge files in compartment `c`, **and tool results from tools in `c`** |
| `memory:<c>` | memory in `c` |
| `work:<c>` | work items in `c` |
| `adapter:<c>` | the LoRA adapter trained on `c` may load |
| `tool:<name>` / `tool:<name>:<action>` | run a tool (all actions / one action) |

**Tool data rule:** being allowed to *run* a tool and being allowed to *see its data* are separate. A tool's result reaches the model only if the session has `knowledge:<tool's compartment>`; otherwise it is withheld and logged as `tool_result_withheld`.

**Peer memory:** a peer session always records to and reads from its own `peer:<id>` compartment (stored as `memory/peer__<id>/`). It never sees yours, and `Protocol.training_set()` never returns peer data.

## Agent folder

```
my-agent/
├── agent.yaml  installables.yaml  policy.yaml  .env  audit.log
├── identity/agent.key, agent.pub          Ed25519; agent.pub = agent id
├── knowledge/<compartment>/*.md|*.txt
├── memory/<compartment>/<date>.jsonl
├── work/<item>.md                         YAML header: title, compartment, status
├── training/<compartment>/examples.jsonl
├── training/adapters/<model-id with / → -->/<compartment>/
└── data/<name>/                           each tool's/connection's storage (calendar.db, phone push keys…)
```

## Adding a tool or a connection

They are installables, not part of this repo: see the [README](../README.md#4-installables-tools-and-connections) for the interfaces, a worked example, and how to publish one.

## Adding a backend

Write a class with the five `Backend` methods (`localagent/runtime/base.py`), register its name in `runtime/factory.py`, and add it to the `backend` fixture params in `tests/test_runtime_contract.py` so it passes the same contract as the others. `set_adapters` must leave **no** adapter active when it raises `AdapterLoadError`.
