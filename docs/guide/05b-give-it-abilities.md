# 5b. Give it abilities: web, files, terminal

Out of the box your agent can only talk. **Tools** let it *do* things: read a web page, write a file, run a command. You choose them in one file, `my-agent/installables.yaml`, and install them with one command. None of their code lives in this repo.

## How it works

1. You list a tool in `installables.yaml`.
2. `python -m localagent install` downloads it and checks that it starts.
3. When you chat, the model sees a short list of the tools' **actions** (e.g. `files.write_file`). When it needs one, it writes a tool tag at the end of its reply. You never see the tag.
4. The **guard** (`protocol/`) checks the call: is this session allowed this tool, and may it see the tool's data (its *compartment*)? Then the tool runs and the result goes back to the model, which answers with it.

A tool comes from one of two places:

| Entry | What it is | Example |
|---|---|---|
| `mcp: [command…]` | A ready-made tool from the internet. **MCP** (Model Context Protocol) is a standard way for AI apps to use tools. Thousands of MCP servers exist (files, web, GitHub, databases, calendars…), and your agent can run any of them. | `mcp: [python, -m, mcp_server_fetch]` |
| `source: <folder or git URL>` | Your own code (or a friend's): a small Python package. See the [README §4](../../README.md#4-installables-tools-and-connections). | `source: ../my-tools/calendar` |

## What you need

- **Web:** nothing extra (it's a Python package; `install` adds it).
- **Files** and **terminal:** [Node.js](https://nodejs.org) (LTS). It provides `npx`, which downloads and runs these servers. Check with `node --version`.

## Setup

Open `my-agent/installables.yaml` and add what you want under `tools:`. All three:

```yaml
tools:
  web:                                    # read web pages
    mcp: [python, -m, mcp_server_fetch]
    pip: mcp-server-fetch
    actions: [fetch]
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

  terminal:                               # run PowerShell commands, starting in my-agent/workspace/
    mcp: [npx, -y, wcli0, --shell, powershell, --allowedDir, "{agent}/workspace"]
    cwd: "{agent}/workspace"
    actions: [execute_command]
    fixed_args: {shell: powershell}
    confirm: true                         # you approve every command (see Safety)
```

Then:

```bash
python -m localagent install
```

It shows each tool starting and which actions the model will see:

```
tools/web
  pip install mcp-server-fetch
  ok: MCP server runs; the model sees 1 action(s): fetch
tools/files
  ok: MCP server runs; the model sees 4 action(s): list_directory, read_text_file, write_file, create_directory
tools/terminal
  ok: MCP server runs; the model sees 1 action(s): execute_command
```

The first install of `files` and `terminal` takes a minute (npx downloads them); after that they start in seconds.

### What each setting means

| Setting | Meaning |
|---|---|
| `mcp` | The command that starts the server. `python` means your agent's own Python (the venv); `npx -y <package>` downloads and runs an npm package. |
| `pip` | Python package(s) to install for it (one name or a list). |
| `actions` | Which of the server's actions the model sees. **Keep this short.** Servers offer many (the files server has 14); a small model gets confused by a long list. Leave it out and `install` lists them all, so you can pick. |
| `describe` | Your own wording for an action, replacing the server's (often long, written for big models). |
| `fixed_args` | Arguments always filled in for the model and hidden from it, e.g. `{shell: powershell}`. |
| `cwd` | Folder the server runs in. Relative paths the model uses land here. |
| `env` | Extra environment variables, e.g. an API key: `env: {API_KEY: "..."}`. |
| `compartment` | Whose data the results are (default `private`: only your own chats). See page 5. |
| `confirm` | `true`: every call waits for you to reply **yes**. |
| `max_result_chars` | Longer results are cut, so a big web page doesn't flood the model (default 4000). |
| `timeout` | Seconds a call may take (default 60). |

`{agent}` anywhere is replaced by your agent folder's path.

## Check it works

**1. Does the model use the tools correctly?** This sends sample requests (*"Create a file called shopping.txt…"*, *"What does the page https://example.com say?"*, *"Run the command Get-Date"*) and checks the tool call the model writes. Nothing is executed.

```bash
python scripts/tool_eval.py
```

Measured on a GTX 1050 with calendar, web, files and terminal all installed:

| Model | Score | Time |
|---|---|---|
| Qwen2.5-1.5B-Instruct, fp16 | 10/11 | 53 s |
| Qwen2.5-3B-Instruct, 4bit | 8/11 | 364 s |

Both missed *"remind me in 2 minutes"*: small models can't add minutes reliably. Below about 80% the agent will often *say* it did something without doing it; try another model, fewer actions, or clearer `describe:` text.

**2. Try it for real:**

```bash
python -m localagent chat
```

A real session (Qwen2.5-1.5B fp16, GTX 1050), with what actually ran on the right:

```
You: Create a file called shopping.txt with: milk, eggs, bread         → files.write_file ✔ (file on disk)
Agent: Sure, I'll create the file 'shopping.txt' with the items you provided.
       Great! The file 'shopping.txt' has been created successfully with the items milk, eggs, and bread.
You: What files are in my workspace?                                     → nothing ran ✘
Agent: I'm sorry, but I don't have access to your workspace directory. …
You: Read shopping.txt                                                   → nothing ran: answered from the conversation
Agent: Sure, here is the content of the file 'shopping.txt': milk eggs bread
You: What does the page https://example.com say?                         → web.fetch ✔
Agent: Sure, one moment.
       The page at https://example.com contains the following information: Example Domain. This domain is for use
       in documentation examples without needing permission. …
You: Run the command Get-Date in the terminal                            → held for approval
Agent: Sure, one moment.
       (Waiting for your OK to run terminal.execute_command {"command": "Get-Date"}. Reply yes to run it.)
You: yes                                                                 → terminal.execute_command ✔
Agent: The current date and time is Sunday, October 11, 2026 at 11:26:06 AM.
```

So: the tools work, and a 1.5B model *usually* uses them. Sometimes it refuses or answers from what it already said. You can ask again or name the tool ("use the files tool to list my workspace"); a bigger model is the real fix. To see what really ran in any turn, look at `tool_calls` in `my-agent/memory/private/<date>.jsonl`.

Files it creates are in `my-agent/workspace/`. Each server's own log is in `my-agent/data/<tool>/server.log`.

## Safety: read this before enabling the terminal

Your agent's data protection rests on one rule: **nothing reads your data except through the guard.** Tools that touch your computer can step around that rule, so know what each one can reach:

- **files** is properly limited: the server refuses any path outside `my-agent/workspace/` (tested). Don't widen it to `my-agent/` itself, or the model could read `.env` and your private knowledge directly.
- **terminal is not a sandbox.** `--allowedDir` only sets where commands *start*. A command can still read or delete files anywhere you can, including `my-agent/.env` (tested). That's why `confirm: true` is on: you see every command before it runs. Only turn it off on a machine with nothing to lose.
- **web** pages are written by strangers, and a page can contain instructions aimed at your model ("ignore your owner and run…"). With `confirm: true` on the terminal, such an instruction can't run a command without you.
- Other agents (page 7) never get your tools unless `policy.yaml` grants them, and results from `private` tools are withheld from them even if they can call one.

## Adding any other MCP server

1. Find one: the [official list](https://github.com/modelcontextprotocol/servers) or a directory such as [glama.ai/mcp/servers](https://glama.ai/mcp/servers). Its page shows how to run it: an `npx …` command, a `uvx …` command (use `pip:` with the package plus `mcp: [python, -m, <module>]`), or a Docker command.
2. Add it under `tools:` with that command as `mcp:`. Leave `actions:` out the first time.
3. `python -m localagent install`: it prints every action the server offers.
4. Keep the 1–4 actions you need in `actions:`; add `describe:` lines in plain words if the server's are long; pin arguments with `fixed_args:`.
5. Add a sample request for it to `CASES` in `scripts/tool_eval.py` and run it. Then try it in `chat`.

Things to know with small local models:
- **Fewer actions, better calls.** Every action is text in the prompt. Aim for about 10 actions across all tools.
- **One look-up per message.** After a read the model gets one more turn to answer; it can't chain many steps (list a folder, then read each file) in one message. Ask step by step.
- **Long results are cut** at `max_result_chars`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `'npx' was not found on PATH. Install Node.js` | Install Node.js LTS, open a new terminal |
| `MCP server for 'x' failed to start` | Read `my-agent/data/x/server.log`; run the `mcp:` command by hand to see the error |
| `no action(s) foo. It offers: …` | A name in `actions:` is misspelled; the message lists the real ones |
| Agent says "I can't access the internet/files" | The tool isn't installed (`python -m localagent list`) or the model is too small; check `tool_eval.py` |
| `(Couldn't run files.write_file: Access denied - path outside allowed directories…)` | Working as intended: the model tried a path outside the workspace |
| A tool's answer is cut off | Raise `max_result_chars` |

Next: [6. Train it](06-train-it.md)
