# Local Guide: your own AI agent, on your own computer

Run a local language model as a personal agent, teach it about you, give it tools (web, files, terminal, calendar, …), reach it from your phone, train it on your own data, and connect it to your friends' agents, with you deciding exactly what each one can see.

> **New here?** Follow the step-by-step setup guide: [`docs/guide/`](docs/guide/README.md). This README is the map of the project, for anyone who wants to change it.

```bash
python scripts/new_agent.py      # create your agent folder (picks a model for your hardware)
python -m localagent install     # download the tools and connections it uses
python -m localagent chat        # talk to it in the terminal
python -m localagent serve       # phone app, reminders, tunnel... (whatever connections you installed)
python -m localagent list        # the tools/connections your agent uses, and where each comes from
```

---

## 1. How the project is split

| Place | What it holds | In git? | Who edits it |
|---|---|---|---|
| **This repo** (`local-guide`) | The **core**: runs the model, guards the data, runs the conversation, and knows how to plug tools in. Same for everyone. | yes | everyone, via pull requests |
| **Your agent folder** (`my-agent/`) | Everything that is **yours**: settings, secrets, knowledge, memory, and `installables.yaml`, the list of tools and connections it uses. | **never** (gitignored) | only you |
| **Wherever each tool lives** | Ready-made tools from the internet (MCP servers, installed by name), or your own tools/connections in any folder or git repo. | their own business | their authors |

So the core never contains a tool, a connection, or anyone's data. Each entry in `my-agent/installables.yaml` says where it comes from, and `python -m localagent install` gets it. Two people can run the same core with completely different tools.

**Swapping the model** changes one line in `my-agent/agent.yaml`. Knowledge, memory, tools, policy and connections stay exactly the same.

## 2. Map of this repo

```
local-guide/
├── localagent/                 the core (Python package)
│   ├── runtime/                runs the model behind one interface (Backend)
│   ├── vault/                  reads/writes the agent folder; every item has a compartment label
│   ├── protocol/               THE GUARD: who may see what (sessions, scopes, policy, audit, identity)
│   ├── agent/                  one conversation turn: prompt → model → tool calls → reply → memory
│   │   └── tools/
│   │       ├── base.py         what a tool is (the interface your own tools implement)
│   │       └── mcp_bridge.py   runs any MCP server and offers its actions as a tool
│   ├── training/               training-data format (fine-tuning comes later)
│   ├── connect/                how the outside world reaches the agent
│   │   ├── base.py             what a connection is (the interface installables implement)
│   │   ├── serve.py            `serve`: starts connections, runs tools' background jobs
│   │   └── owner/terminal.py   `chat`: the terminal (the one connection built in)
│   ├── extensions.py           finds and loads installables
│   ├── installer.py            `install` and `list`
│   ├── config.py               reads agent.yaml, installables.yaml, .env
│   ├── bootstrap.py            wires all of the above for one agent
│   ├── setup_agent.py          creates agent folders from agent_template/
│   ├── testing.py              FakeBackend: test tools/connections without a model
│   └── __main__.py             the `python -m localagent` commands
├── agent_template/             what `new_agent.py` copies to make a new agent folder
├── scripts/                    new_agent, diagnose, smoke_test_model, tool_eval, benchmark, start_server.bat
├── tests/                      core tests (+ fake_extensions/: a stand-in tool, connection and MCP server)
├── docs/
│   ├── guide/                  the setup guide (pages 1–7, plus 5b: web/files/terminal)
│   ├── architecture.md         layers, data flow, scopes, in depth
│   ├── design/  plans/         design specs and implementation plans
│   └── Setup/                  setup notes (Cloudflare walkthrough, git, Mac)
├── my-agent/                   YOUR agent (gitignored)
├── extensions/                 tools/connections cloned from git sources (gitignored, made by `install`)
└── models/                     downloaded model weights (gitignored)
```

### The layers, and the one rule

```
connect/   ─┐  transports: terminal, plus installed connections (phone, tunnel, agent network)
            ▼
protocol/  THE GUARD ── decides what every session and every training run may see
            │
            ├──► agent/      sees only what a session hands it
            ├──► training/   builds datasets only through the protocol
            ▼
vault/     your data, labeled by compartment          runtime/   the model
```

**Nothing reads your data except through `protocol/`.** Each layer may import only the layers below it, and `tests/test_layers.py` fails if any import breaks that. The full table and the life of one message are in [`docs/architecture.md`](docs/architecture.md).

## 3. Your agent folder

```
my-agent/
├── agent.yaml          model, compartments, memory length
├── installables.yaml   which tools and connections, and their settings
├── policy.yaml         who may see what (you, other agents)
├── .env                secrets (AGENT_SECRET). Never share.
├── identity/           your agent's keypair; agent.pub is its public id
├── knowledge/<compartment>/   facts it always knows (.md/.txt), e.g. private/ (shared/ is just an example extra one)
├── memory/<compartment>/      conversations, written automatically
├── work/               active tasks (.md with a compartment/status header)
├── training/           examples and trained adapters (`examples`, `train`, `export`)
├── workspace/          the folder the files/terminal tools work in
├── data/<name>/        each tool's and connection's own storage (calendar.db, push keys, server logs…)
└── audit.log           sessions opened and requests refused
```

**Compartments** (`private`, `shared`, or any you add in `agent.yaml`) are how data protection works: every file, memory and tool belongs to one, and `policy.yaml` says which compartments each kind of session can see. Your own chats see everything. `shared` is only an example extra compartment: nothing is shared automatically. To share with another agent, put what you share in a connection compartment, train it into its own adapter, and serve it from a Tessera-facing agent ([guide page 7](docs/guide/07-connect-to-others.md)).

## 4. Installables: tools and connections

### Choosing what your agent uses

`my-agent/installables.yaml` lists every tool and connection by name. Each entry says where it comes from:

```yaml
tools:
  web:                                     # from the internet: any MCP server, by its command
    mcp: [python, -m, mcp_server_fetch]
    pip: mcp-server-fetch
    actions: [fetch]
  files:
    mcp: [npx, -y, "@modelcontextprotocol/server-filesystem", "{agent}/workspace"]
    cwd: "{agent}/workspace"
  calendar:                                # your own code: a folder or a git URL
    source: W:/my-tools/calendar           # (relative paths are relative to my-agent/)
    compartment: private                   # every tool accepts this; others are tool-specific

connections:
  phone:
    source: https://github.com/you/phone-connection.git   # cloned into extensions/ by install
    ref: main                                              # optional branch or tag
    port: 8000
```

- Listed = enabled. Delete a block (or comment it out) to disable it.
- After any change: `python -m localagent install`. Git sources are cloned/updated into `extensions/<kind>/<name>/` (gitignored), `requirements.txt` and `pip:` packages are installed, and every MCP server is started once to prove it works (it prints the actions the model will see).
- `python -m localagent list` shows each entry and where it comes from.
- A misspelled setting, a missing tool, an MCP server that won't start, or a tool in a compartment you don't have is a clear error at startup, before the model loads.
- `confirm: true` on any tool makes every call wait for your **yes**.

**Tools from the internet (web, files, terminal and thousands more):** see guide page [5b. Give it abilities](docs/guide/05b-give-it-abilities.md): setup, every setting, safety, and how to add any MCP server.

### Writing your own tool

A tool is a folder with an `__init__.py` that exports `TOOL`. Put it anywhere (its own git repo, if you want to share it) and point `source:` at it.

```python
# my-tools/notes/__init__.py
"""Notes: save short notes and read them back."""
from .tool import NotesTool as TOOL
```
```python
# my-tools/notes/tool.py
from pathlib import Path

from localagent.agent.tools.base import Action, Tool


class NotesTool(Tool):
    name = "notes"
    compartment = "private"          # default; overridable in installables.yaml
    options = ("max_notes",)         # extra settings it accepts (self.settings)
    actions = {
        "add": Action("Save a note", {"text": "str"}, kind="write"),
        "list": Action("List saved notes", {}, kind="read"),
    }

    def setup(self, data_dir: Path, notify):
        data_dir.mkdir(parents=True, exist_ok=True)   # data_dir = my-agent/data/notes/
        self.file = data_dir / "notes.txt"

    def run(self, action, args):
        if action == "add":
            with self.file.open("a", encoding="utf-8") as f:
                f.write(args["text"] + "\n")
            return {"saved": True}
        return {"notes": self.file.read_text(encoding="utf-8").splitlines() if self.file.exists() else []}
```
```yaml
# my-agent/installables.yaml
tools:
  notes:
    source: ../../my-tools/notes
```

Then `python -m localagent install` and chat: *"note that the wifi password is on the fridge"*.

What you get for free: the model is told about the tool's actions, argument types are checked (`str`, `int`, `number`, `bool`, `list`, `object`, `iso-datetime`; mark optional ones with `Action(..., optional=frozenset({...}))`), every call goes through the guard (scope check, audit, and its result is withheld from sessions that can't see its compartment), and the phone connection exposes each action as `GET/POST /api/tools/<name>/<action>`.

Rules of thumb:
- **`kind="read"`** actions return data the model then answers from; **`kind="write"`** actions change something. Keep each action small and its description one plain sentence: small models read it literally.
- Store everything under `data_dir`. Never read other folders of the agent: the guard can't protect what bypasses it.
- `background()` (optional) runs about once a minute while `serve` runs; `notify(title, body)` reaches the owner through whatever connections are installed (e.g. phone push).
- Needs a pip package? Put a `requirements.txt` next to `__init__.py`.
- Test it with plain pytest; `localagent.testing.FakeBackend` runs full agent turns without a model (see `tests/test_bootstrap.py::test_mcp_tool_end_to_end` for the pattern).
- Check that your model actually manages to call it: add a sample request to `CASES` in `scripts/tool_eval.py` and run it.

### Writing your own connection

Same idea: a folder whose `__init__.py` exports `CONNECTION`, a subclass of `localagent.connect.base.Connection`, listed under `connections:` with `source:`.

```python
class MyConnection(Connection):
    name = "myconn"
    options = ("port",)

    def setup(self, ctx):        # after the model loads; ctx has protocol, agent, tools, settings, data_dir, notifier
        ...                      # raise SetupError("…how to fix…") if it can't run
    def start(self): ...         # don't block: start a thread or a subprocess
    def stop(self): ...          # undo start()
```

A connection talks to the agent only by opening a session: `ctx.protocol.open_owner_session(token)` and `ctx.agent.respond_stream(session, text)`. It never touches the vault directly. To deliver notifications, add a channel: `ctx.notifier.add(send)`. The phone connection is the reference example.

### Sharing it

Push the folder to a git repo and tell others to add `source: <its git URL>`. That's all: there is no central catalog.

## 5. Common changes: where to look

| I want to… | Edit |
|---|---|
| Use another model | `my-agent/agent.yaml` → `model:`; then `python scripts/tool_eval.py` to check it handles tools |
| Add/remove a tool or connection | `my-agent/installables.yaml`, then `python -m localagent install` |
| Give it web, files, terminal or any MCP tool | guide page [5b](docs/guide/05b-give-it-abilities.md) |
| Teach it facts | add `.md` files to `my-agent/knowledge/private/` or `shared/` |
| Control what other agents see | `my-agent/policy.yaml` (guide page 7) |
| Change how the agent is told to use tools | `localagent/agent/prompt.py` (re-run `scripts/tool_eval.py` on two models afterwards) |
| Change how tool calls are parsed | `localagent/agent/toolcalls.py` (tests: `tests/test_toolcalls.py`, built from real model output) |
| Support a new kind of hardware (llama.cpp, MLX) | a backend in `localagent/runtime/` (see "Adding a backend" in `docs/architecture.md`) |
| Change what a new agent starts with | `agent_template/` |
| Change how MCP servers are run | `localagent/agent/tools/mcp_bridge.py` (tests: `tests/test_mcp_bridge.py`) |

## 6. Development

```bash
python -m pytest                                   # core tests (no model, no GPU needed)
python scripts/smoke_test_model.py                 # loads your real model and says hello
python scripts/tool_eval.py                        # scores your model's use of your installed tools
python scripts/diagnose.py                         # hardware / CUDA check
```

- Work on a branch, keep `python -m pytest` green, open a pull request.
- Never commit `my-agent/`, `.env`, `*.pem`, `models/` or `extensions/`; `.gitignore` covers them, so don't force-add.
- Small local models drift from instructions. When a change touches prompts or parsing, test it against a real model (`tool_eval.py`), not just the fakes; the parser tests in `tests/test_toolcalls.py` use output captured from real runs for this reason.

## 7. Docs

- [`docs/guide/`](docs/guide/README.md): setup guide, in order
- [`docs/architecture.md`](docs/architecture.md): layers, one turn step by step, scopes, adding a backend
- [`docs/design/`](docs/design/): design specs; [`docs/plans/`](docs/plans/): implementation plans
- [`docs/guide/05b-give-it-abilities.md`](docs/guide/05b-give-it-abilities.md): web, files, terminal and any MCP tool
