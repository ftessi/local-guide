# Local Guide: your own AI agent, on your own computer

Run a local language model as a personal agent, teach it about you, give it tools (calendar, …), reach it from your phone, and later train it and connect it to your friends' agents, with you deciding exactly what each one can see.

> **New here?** Follow the step-by-step setup guide: [`docs/guide/`](docs/guide/README.md). This README is the map of the project, for anyone who wants to change it.

```bash
python scripts/new_agent.py      # create your agent folder (picks a model for your hardware)
python -m localagent install     # download the tools and connections it uses
python -m localagent chat        # talk to it in the terminal
python -m localagent serve       # phone app, reminders, tunnel... (whatever connections you installed)
python -m localagent list        # what tools/connections exist, and which ones you use
```

---

## 1. How the project is split

Everything lives in one of three places. Knowing which is the whole trick:

| Place | What it holds | In git? | Who edits it |
|---|---|---|---|
| **This repo** (`local-guide`) | The **core**: runs the model, guards the data, runs the conversation. Same for everyone. | yes | everyone, via pull requests |
| **[`local-guide-extensions`](https://github.com/ftessi/local-guide-extensions)** | **Installables**: tools (calendar, …) and connections (phone app, Cloudflare tunnel, …). | yes, its own repo | everyone, via pull requests |
| **Your agent folder** (`my-agent/`) | Everything that is **yours**: settings, secrets, knowledge, memory, which installables you use. | **never** (gitignored) | only you |

So the core never contains a tool, a connection, or anyone's data. Tools and connections are listed per agent in `my-agent/installables.yaml` and fetched by `python -m localagent install` into `extensions/` (gitignored). Two people can run the same core with completely different tools.

**Swapping the model** changes one line in `my-agent/agent.yaml`. Knowledge, memory, tools, policy and connections stay exactly the same.

## 2. Map of this repo

```
local-guide/
├── localagent/                 the core (Python package)
│   ├── runtime/                runs the model behind one interface (Backend)
│   ├── vault/                  reads/writes the agent folder; every item has a compartment label
│   ├── protocol/               THE GUARD: who may see what (sessions, scopes, policy, audit, identity)
│   ├── agent/                  one conversation turn: prompt → model → tool calls → reply → memory
│   │   └── tools/base.py       what a tool is (the interface installables implement)
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
├── tests/                      core tests (+ fake_extensions/: a stand-in tool and connection)
├── docs/
│   ├── guide/                  the setup guide (pages 1–7)
│   ├── architecture.md         layers, data flow, scopes, in depth
│   ├── design/  plans/         design specs and implementation plans
│   └── Setup/                  setup notes (Cloudflare walkthrough, git, Mac)
├── my-agent/                   YOUR agent (gitignored)
├── extensions/                 installed tools/connections (gitignored, made by `install`)
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
├── knowledge/<compartment>/   facts it always knows (.md/.txt), e.g. private/, shared/
├── memory/<compartment>/      conversations, written automatically
├── work/               active tasks (.md with a compartment/status header)
├── training/           examples and trained adapters (coming later)
├── data/<name>/        each tool's and connection's own storage (calendar.db, push keys…)
└── audit.log           sessions opened and requests refused
```

**Compartments** (`private`, `shared`, or any you add in `agent.yaml`) are how data protection works: every file, memory and tool belongs to one, and `policy.yaml` says which compartments each kind of session can see. Your own chats see everything; another agent sees only what you allow.

## 4. Installables: tools and connections

### Choosing what your agent uses

`my-agent/installables.yaml`:

```yaml
source: https://github.com/ftessi/local-guide-extensions.git   # where the code comes from
ref: main                                                       # branch or tag

tools:
  calendar:
    compartment: private     # every tool accepts this; others are tool-specific

connections:
  phone:
    host: 127.0.0.1
    port: 8000
  cloudflare:
    tunnel: local-agent
```

- Listed = enabled. Delete a block (or comment it out) to disable it.
- After any change: `python -m localagent install`. It downloads/updates the source into `extensions/` and pip-installs each listed item's `requirements.txt`.
- `python -m localagent list` shows everything the source offers, marking what you use.
- A misspelled setting, a missing item, or a tool in a compartment you don't have is a clear error at startup, before the model loads.

### Writing a new tool

1. Get the extensions repo next to this one and point your agent at it, so you edit live code:

   ```bash
   git clone git@github.com:ftessi/local-guide-extensions.git ../local-guide-extensions
   ```
   ```yaml
   # my-agent/installables.yaml
   source: ../../local-guide-extensions     # a local folder (relative to my-agent/) instead of a URL
   ```

2. Create `tools/<name>/__init__.py` in the extensions repo. Its docstring's first line is what `list` shows; it must export `TOOL`:

   ```python
   # tools/notes/__init__.py
   """Notes: save short notes and read them back."""
   from .tool import NotesTool as TOOL
   ```
   ```python
   # tools/notes/tool.py
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

3. Add `notes:` under `tools:` in your `installables.yaml`, run `python -m localagent install`, then chat: *"note that the wifi password is on the fridge"*.

What you get for free: the model is told about the tool's actions, argument types are checked (`str`, `int`, `iso-datetime`), every call goes through the guard (scope check, audit, and its result is withheld from sessions that can't see its compartment), and the phone connection exposes each action as `GET/POST /api/tools/<name>/<action>`.

Rules of thumb:
- **`kind="read"`** actions return data the model then answers from; **`kind="write"`** actions change something. Keep each action small and its description one plain sentence: small models read it literally.
- Store everything under `data_dir`. Never read other folders of the agent: the guard can't protect what bypasses it.
- `background()` (optional) runs about once a minute while `serve` runs; `notify(title, body)` reaches the owner through whatever connections are installed (e.g. phone push).
- Needs a pip package? Put it in `tools/<name>/requirements.txt`.
- Test it with a plain pytest file in the extensions repo's `tests/`; `localagent.testing.FakeBackend` lets you run full agent turns without a model.
- Check that your model actually manages to call it: `python scripts/tool_eval.py` shows the pattern for the calendar.

### Writing a new connection

Same layout under `connections/<name>/`, exporting `CONNECTION`, a subclass of `localagent.connect.base.Connection`:

```python
class MyConnection(Connection):
    name = "myconn"
    options = ("port",)

    def setup(self, ctx):        # after the model loads; ctx has protocol, agent, tools, settings, data_dir, notifier
        ...                      # raise SetupError("…how to fix…") if it can't run
    def start(self): ...         # don't block: start a thread or a subprocess
    def stop(self): ...          # undo start()
```

A connection talks to the agent only by opening a session: `ctx.protocol.open_owner_session(token)` and `ctx.agent.respond_stream(session, text)`. It never touches the vault directly. To deliver notifications, add a channel: `ctx.notifier.add(send)`. The phone connection (`connections/phone/`) is the reference example.

### Publishing it to the group

Commit to a branch of `local-guide-extensions`, open a pull request, and once it's merged everyone can add it to their `installables.yaml`. Until then, others can try your branch with `ref: <your-branch>`.

## 5. Common changes: where to look

| I want to… | Edit |
|---|---|
| Use another model | `my-agent/agent.yaml` → `model:`; then `python scripts/tool_eval.py` to check it handles tools |
| Add/remove a tool or connection | `my-agent/installables.yaml`, then `python -m localagent install` |
| Teach it facts | add `.md` files to `my-agent/knowledge/private/` or `shared/` |
| Control what other agents see | `my-agent/policy.yaml` (guide page 7) |
| Change how the agent is told to use tools | `localagent/agent/prompt.py` (re-run `scripts/tool_eval.py` on two models afterwards) |
| Change how tool calls are parsed | `localagent/agent/toolcalls.py` (tests: `tests/test_toolcalls.py`, built from real model output) |
| Support a new kind of hardware (llama.cpp, MLX) | a backend in `localagent/runtime/` (see "Adding a backend" in `docs/architecture.md`) |
| Change what a new agent starts with | `agent_template/` |
| Change the phone app | `connections/phone/` in the extensions repo |

## 6. Development

```bash
python -m pytest                                   # core tests (no model, no GPU needed)
cd ../local-guide-extensions && python -m pytest   # extensions tests (finds the core next to it)
python scripts/smoke_test_model.py                 # loads your real model and says hello
python scripts/tool_eval.py                        # scores your model's tool use (6 cases)
python scripts/diagnose.py                         # hardware / CUDA check
```

- Work on a branch, keep `python -m pytest` green, open a pull request.
- Never commit `my-agent/`, `.env`, `*.pem`, `models/` or `extensions/`; `.gitignore` covers them, so don't force-add.
- Small local models drift from instructions. When a change touches prompts or parsing, test it against a real model (`tool_eval.py`), not just the fakes; the parser tests in `tests/test_toolcalls.py` use output captured from real runs for this reason.

## 7. Docs

- [`docs/guide/`](docs/guide/README.md): setup guide, in order
- [`docs/architecture.md`](docs/architecture.md): layers, one turn step by step, scopes, adding a backend
- [`docs/design/`](docs/design/): design specs; [`docs/plans/`](docs/plans/): implementation plans
- Extensions: each tool/connection has its own `README.md` in [`local-guide-extensions`](https://github.com/ftessi/local-guide-extensions)
