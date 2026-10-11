# Architecture

One shared codebase (`localagent/`), one personal folder per agent (`my-agent/`, gitignored). The model is swappable; everything else stays the same.

Design spec: [`design/2026-10-11-ecosystem-restructure-design.md`](design/2026-10-11-ecosystem-restructure-design.md).

## Layers

```
connect/     transports: owner server (PWA, push, terminal), agent↔agent network (later)
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
| `connect` | Owner server, terminal, push; peer transport later | `protocol`, `agent`, `runtime` |

`tests/test_layers.py` fails if any import breaks these rules. Outside the layers: `config.py` (reads `agent.yaml`), `bootstrap.py` (wires layers for one agent), `setup_agent.py` (creates and migrates agent folders), `__main__.py` (CLI).

## One turn, step by step

1. A transport (`connect/owner/server.py` or `terminal.py`) opens a **session** with the protocol. The owner session = token check + `owner` scope from `policy.yaml`.
2. `Agent._turn` asks the session which **adapters** may load and tells the runtime (`set_adapters`). If that fails, the turn is refused; it never silently runs with a different set.
3. The system prompt is built from `session.context()` (knowledge + active work in scope) and `session.tools()` (only allowed actions), plus the date/time.
4. History = `session.history(n)`: this session's own memory compartment only.
5. The model streams its reply. `VisibleText` hides everything from the first `<tool>` tag, so tags are never shown, even when split across chunks.
6. Each `<tool>{...}</tool>` call goes through `session.check_tool_call`, then the arguments are validated, then the tool runs, then `session.filter_tool_result`.
7. If a **read** action succeeded, its results go back to the model for one more round (max 2 rounds). Calls in the final round are ignored, so the model can't duplicate writes.
8. The clean reply is recorded with `session.record` → `memory/<compartment>/<date>.jsonl`.

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
├── agent.yaml  policy.yaml  .env  audit.log
├── identity/agent.key, agent.pub          Ed25519; agent.pub = agent id
├── knowledge/<compartment>/*.md|*.txt
├── memory/<compartment>/<date>.jsonl
├── work/<item>.md                         YAML header: title, compartment, status
├── training/<compartment>/examples.jsonl
├── training/adapters/<model-id with / → -->/<compartment>/
└── data/<tool>/                           tool storage; data/push_subscriptions.json
```

## Adding a tool

Create a package `localagent/agent/tools/<name>/` whose `__init__.py` exports `TOOL`:

```python
# localagent/agent/tools/notes/__init__.py
from localagent.agent.tools.notes.tool import NotesTool as TOOL

# localagent/agent/tools/notes/tool.py
from pathlib import Path
from localagent.agent.tools.base import Action, Tool


class NotesTool(Tool):
    name = "notes"
    compartment = "private"
    actions = {
        "add": Action("Save a note", {"text": "str"}, kind="write"),
        "list": Action("List saved notes", {}, kind="read"),
    }

    def setup(self, data_dir: Path, notify):
        data_dir.mkdir(parents=True, exist_ok=True)
        self.file = data_dir / "notes.txt"

    def run(self, action, args):
        if action == "add":
            with self.file.open("a", encoding="utf-8") as f:
                f.write(args["text"] + "\n")
            return {"saved": True}
        return {"notes": self.file.read_text(encoding="utf-8").splitlines() if self.file.exists() else []}
```

Enable it in `agent.yaml` under `tools: {notes: {enabled: true}}`. The prompt text, REST endpoints (`/api/tools/notes/...`) and scope checks come for free. Argument types: `str`, `int`, `iso-datetime` (normalized to local time). Optional `background()` runs every minute while the server is up; `notify(title, body)` sends a push to the owner.

## Adding a backend

Write a class with the five `Backend` methods (`localagent/runtime/base.py`), register its name in `runtime/factory.py`, and add it to the `backend` fixture params in `tests/test_runtime_contract.py` so it passes the same contract as the others. `set_adapters` must leave **no** adapter active when it raises `AdapterLoadError`.
