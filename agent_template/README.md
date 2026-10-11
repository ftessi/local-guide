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
