# Agent folder

Everything that makes this agent *yours*. Never commit it or share it.

| Path | What goes there |
|---|---|
| `agent.yaml` | model and settings |
| `installables.yaml` | tools and connections it uses (`python -m localagent install` after editing) |
| `policy.yaml` | who may see what |
| `.env` | secrets (`AGENT_SECRET`) |
| `identity/` | this agent's keypair; `agent.pub` is its id |
| `knowledge/<compartment>/` | `.md` / `.txt` facts the agent always knows |
| `memory/` | conversation logs, written automatically |
| `work/` | one `.md` per active task, with a `compartment:` / `status:` header |
| `training/` | curated examples and trained adapters |
| `data/<name>/` | each tool's and connection's storage (calendar database, phone push keys) |
| `audit.log` | sessions and refused requests |
