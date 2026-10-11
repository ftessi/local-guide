# LocalAgent: your own AI agent, on your own computer

Run a language model locally as a personal agent: teach it about you, give it tools (web, files, terminal,
reminders…), reach it from your phone, train it on your own data, and let other people's agents ask it questions,
with you deciding exactly what each of them can see. No cloud, no account.

Works on Windows, Linux and Mac; fast with an NVIDIA GPU, slower on Mac or CPU only.

## Quick start

```bash
git clone https://github.com/ftessi/local-guide.git LocalAgent
cd LocalAgent
python -m venv .venv
# activate it: .venv\Scripts\activate (Windows) or source .venv/bin/activate (Linux/Mac)
# install PyTorch for your machine, then the rest: see docs/02-install.md
python scripts/new_agent.py      # create your agent folder (picks a model for your hardware)
python -m localagent install     # fetch the tools and connections it uses
python -m localagent chat        # talk to it
```

## Documentation

Everything is in [`docs/`](docs/README.md), one page per subject:

1. [Overview](docs/01-overview.md): what this is, and the five ideas everything rests on
2. [Install](docs/02-install.md): Windows, Linux, Mac; NVIDIA GPU or CPU only
3. [Create your agent](docs/03-create-your-agent.md)
4. [Chat, and reach it from your phone](docs/04-chat-and-phone.md)
5. [Knowledge, memory and work](docs/05-knowledge-and-memory.md)
6. [Tools](docs/06-tools.md): web, files, terminal, any MCP server, your own
7. [Training](docs/07-training.md): facts trained into per-compartment adapters
8. [Connecting agents (Tessera)](docs/08-connecting-agents.md)
9. [Architecture](docs/09-architecture.md): for anyone changing the code
10. [Performance and hardware](docs/10-performance.md)
11. [Troubleshooting](docs/11-troubleshooting.md)
12. [Decisions and roadmap](docs/12-decisions-and-roadmap.md)

## Commands

| Command | Does |
|---|---|
| `python -m localagent chat` | talk to your agent in the terminal |
| `python -m localagent serve` | run the connections (phone app, tunnel, Tessera) and reminders |
| `python -m localagent install` / `list` | fetch / show the tools and connections in `installables.yaml` |
| `python -m localagent examples` / `train` / `export` | training (page 7) |
| `python -m localagent id` / `peers` / `connect` / `ask` | Tessera (page 8) |

All take `--agent <folder>` (default `./my-agent`). `python -m localagent --help` lists every option.

## The one rule

The repository is shared code; your agent folder (`my-agent/`) is yours and is never committed. Nothing reads your
data except through the guard (`localagent/protocol/`). Run the tests with `python -m pytest`; no model or GPU
needed.
