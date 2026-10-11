# 6. Tools

Out of the box your agent can only talk. **Tools** let it do things: search the web, read a page, write a file, run
a command, set a reminder. You choose them in `my-agent/installables.yaml` and fetch them with
`python -m localagent install`. None of their code lives in this repository.

## How a tool call works

1. The model sees a short list of the tools' **actions** (`files.write_file`, `web.search`…), each with one plain
   sentence and its arguments.
2. When it needs one, it writes a tool tag at the end of its reply. You never see the tag.
3. The **guard** checks the call: may this session use this tool, are the arguments valid? The tool runs, and its
   result goes back to the model only if the session may see the tool's compartment.
4. For a **read** action, the model gets the result and writes the answer from it. Up to 3 tool calls in a row per
   message (e.g. search, open a page, answer).

Two kinds of entries:

| Entry | What it is | Example |
|---|---|---|
| `mcp: [command…]` | A ready-made tool from the internet. **MCP** (Model Context Protocol) is a standard way for AI apps to use tools; thousands of MCP servers exist (files, web, GitHub, databases…). | `mcp: [python, -m, duckduckgo_mcp_server.server]` |
| `source: <folder or git URL>` | Your own code (or a friend's): a small Python package ([below](#writing-your-own-tool)). | `source: ../../my-tools/notes` |

## Web, files, terminal

**Web** needs nothing extra. **Files** and **terminal** need [Node.js](https://nodejs.org) (LTS), which provides
`npx`; check with `node --version`.

```yaml
tools:
  web:                                    # search the web and read pages (DuckDuckGo, no account)
    mcp: [python, -m, duckduckgo_mcp_server.server]
    pip: duckduckgo-mcp-server==0.6.1     # 0.7+ needs mcp 2.x, which other servers don't support yet
    actions: [search, fetch_content]
    fixed_args: {max_results: 5, max_length: 50000}
    max_result_chars: 60000
    follow: {search: fetch_content}       # after a search, the agent opens the first result itself
    describe:
      search: Search the web. Returns titles, links and short summaries of pages
      fetch_content: Read the text of a web page, given its URL
    compartment: shared                   # web pages aren't private data

  files:                                  # read and write files, only inside my-agent/workspace/
    mcp: [npx, -y, "@modelcontextprotocol/server-filesystem", "{agent}/workspace"]
    cwd: "{agent}/workspace"
    actions: [list_directory, read_text_file, write_file, create_directory]
    describe:
      list_directory: List the files in a folder of your workspace (path "." is the workspace itself)
      read_text_file: Read a text file. path is just the file name, like notes.txt
      write_file: Create or overwrite a text file. path is just the file name, like notes.txt
      create_directory: Create a folder in your workspace

  terminal:                               # Windows: PowerShell commands, starting in my-agent/workspace/
    mcp: [npx, -y, wcli0, --shell, powershell, --allowedDir, "{agent}/workspace"]
    cwd: "{agent}/workspace"
    actions: [execute_command]
    fixed_args: {shell: powershell}
    confirm: true                         # you approve every command (see Safety)
```

`wcli0` is a Windows terminal server. On Linux or Mac, pick a shell MCP server from the
[official list](https://github.com/modelcontextprotocol/servers) instead and keep `confirm: true`.

The `shared` compartment for the web tool needs `shared` in `agent.yaml`'s `compartments` (it is in the template).

Then `python -m localagent install`. It starts each server once and prints the actions the model will see:

```
tools/web
  pip install duckduckgo-mcp-server==0.6.1
  ok: MCP server runs; the model sees 2 action(s): search, fetch_content
tools/files
  ok: MCP server runs; the model sees 4 action(s): list_directory, read_text_file, write_file, create_directory
```

The first install of `files` and `terminal` takes a minute (npx downloads them). Files the agent writes are in
`my-agent/workspace/`; each server's own log is in `my-agent/data/<tool>/server.log`.

## Every setting

| Setting | Meaning |
|---|---|
| `mcp` | The command that starts the server. `python` means the agent's own Python (the venv); `npx -y <package>` downloads and runs an npm package. |
| `pip` | Python package(s) to install for it. |
| `source` / `ref` / `path` | A folder (relative to the agent folder) or a git URL with your own tool; `ref` = branch or tag; `path` = the folder inside it, when one repository holds several tools (e.g. `tools/calendar`). |
| `actions` | Which of the server's actions the model sees. **Keep it short:** small models get confused by long lists. Leave it out once and `install` lists them all. |
| `describe` | Your own wording for an action, replacing the server's (often long, written for big models). |
| `fixed_args` | Arguments always filled in for the model and hidden from it. |
| `cwd` | Folder the server runs in. |
| `env` | Extra environment variables, e.g. an API key. |
| `compartment` | Whose data the results are (default `private`: only your own chats see them). |
| `confirm` | `true`: every call waits for you to reply **yes**. |
| `max_result_chars` | Longer results are cut (default 4000). Below that, any text longer than ~2500 characters is reduced to the start plus the parts that share words with your question. |
| `follow` | `{search: fetch_content}`: after a `search`, the agent itself opens the first link that works, so the model reads the page instead of guessing from a list of links. |
| `timeout` | Seconds a call may take (default 60). |

`{agent}` anywhere is replaced by the agent folder's path.

## Check that it works

```bash
python scripts/tool_eval.py
```

It sends sample requests (*"Create a file called shopping.txt…"*, *"What does the page https://example.com
say?"*…) and scores the tool call the model writes. Nothing is executed. Then try it for real in `chat`.

Small local models are imperfect tool users. They sometimes refuse ("I can't access the internet"), or answer from
what they already said. Asking again, or naming the tool ("use the files tool to list my workspace"), usually works;
a bigger model is the real fix. To see what really ran, look for the `(used …)` lines, or `tool_calls` in
`my-agent/memory/private/<date>.jsonl`.

## Safety: read this before enabling the terminal

Your data's protection rests on one rule: nothing reads it except through the guard. Tools that touch your
computer can step around that, so know what each can reach:

- **files** is properly limited: the server refuses any path outside `my-agent/workspace/`. Don't widen it to
  `my-agent/` itself, or the model could read `.env` and your private knowledge directly.
- **terminal is not a sandbox.** A command can read or delete files anywhere you can, including `my-agent/.env`.
  That's why `confirm: true` is on: you see every command before it runs.
- **web** pages are written by strangers and can contain instructions aimed at your model. With `confirm: true` on
  the terminal, such an instruction can't run a command without you.
- Other agents never get your tools (page 8).

## Adding any other MCP server

1. Find one: the [official list](https://github.com/modelcontextprotocol/servers) or a directory such as
   [glama.ai/mcp/servers](https://glama.ai/mcp/servers). Its page shows how to run it: an `npx …` command, a
   `uvx …` command (use `pip:` with the package plus `mcp: [python, -m, <module>]`), or Docker.
2. Add it under `tools:` with that command as `mcp:`. Leave `actions:` out the first time.
3. `python -m localagent install` prints every action it offers.
4. Keep the 1–4 you need in `actions:`; add `describe:` lines in plain words; pin arguments with `fixed_args:`.
5. Add a sample request to `CASES` in `scripts/tool_eval.py` and run it.

Aim for about 10 actions across all tools: every action is text in every prompt.

## Writing your own tool

A tool is a folder with an `__init__.py` that exports `TOOL`, a subclass of `localagent.agent.tools.base.Tool`.

```python
# my-tools/notes/__init__.py
"""Notes: save short notes and read them back."""
from pathlib import Path

from localagent.agent.tools.base import Action, Tool


class NotesTool(Tool):
    name = "notes"
    compartment = "private"          # default; overridable in installables.yaml
    options = ("max_notes",)         # extra settings it accepts (read them from self.settings)
    actions = {
        "add": Action("Save a note", {"text": "str"}, kind="write"),
        "list": Action("List saved notes", {}, kind="read"),
    }

    def setup(self, data_dir: Path, notify):
        data_dir.mkdir(parents=True, exist_ok=True)   # my-agent/data/notes/
        self.file = data_dir / "notes.txt"

    def run(self, action, args):
        if action == "add":
            with self.file.open("a", encoding="utf-8") as f:
                f.write(args["text"] + "\n")
            return {"saved": True}
        return {"notes": self.file.read_text(encoding="utf-8").splitlines() if self.file.exists() else []}


TOOL = NotesTool
```

```yaml
# my-agent/installables.yaml
tools:
  notes:
    source: ../../my-tools/notes     # relative to my-agent/
```

Then `python -m localagent install` and chat: *"note that the wifi password is on the fridge"*.

What you get for free: the model is told about the actions; argument types are checked (`str`, `int`, `number`,
`bool`, `list`, `object`, `iso-datetime`; optional ones with `Action(..., optional=frozenset({...}))`); every call
goes through the guard; and the phone app exposes each action as `/api/tools/<name>/<action>`.

- **`kind="read"`** actions return data the model answers from; **`kind="write"`** actions change something. Keep
  each action small and its description one plain sentence.
- Store everything under `data_dir`. Never read other folders of the agent: the guard can't protect what bypasses it.
- `background()` (optional) runs about once a minute while `serve` runs; `notify(title, body)` reaches you through
  the installed connections (e.g. phone push).
- Need a pip package? Put a `requirements.txt` next to `__init__.py`.
- Test with pytest; `localagent.testing.FakeBackend` runs full agent turns without a model.

## Writing your own connection

Same idea: a folder whose `__init__.py` exports `CONNECTION`, a subclass of `localagent.connect.base.Connection`,
listed under `connections:` with `source:`.

```python
class MyConnection(Connection):
    name = "myconn"
    options = ("port",)

    def setup(self, ctx):        # after the model loads; ctx has protocol, agent, tools, settings, data_dir, notifier
        ...                      # raise SetupError("…how to fix…") if it can't run
    def start(self): ...         # don't block: start a thread or a subprocess
    def stop(self): ...          # undo start()
```

A connection reaches the agent only through a session: `ctx.protocol.open_owner_session(token)` and
`ctx.agent.respond_stream(session, text)`. To deliver notifications, add a channel: `ctx.notifier.add(send)`. The
phone connection in the extensions repository is the reference example.

## Sharing a tool

Push it to a git repository and tell others to use `source: <its git URL>`, plus `path: <folder>` if the tool isn't
at the repository's top level (one repository can hold several tools). There is no central catalogue.

Next: [7. Training](07-training.md)
