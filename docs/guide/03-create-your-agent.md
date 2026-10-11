# 3. Create your agent

```bash
python scripts/new_agent.py
```

This:
1. detects your hardware and picks a model that fits;
2. copies `agent_template/` to `my-agent/`;
3. generates your secrets (`AGENT_SECRET`, the push-notification keys) into `my-agent/.env`;
4. generates your agent's **identity**, a keypair in `my-agent/identity/`. `agent.pub` is your agent's id, used later when connecting to other agents.

Options: `--agent <folder>` creates the agent somewhere else, and `--no-detect` keeps the template's default model.

`my-agent/` is in `.gitignore`. **Never commit it or share it.**

## Your agent folder

```
my-agent/
├── agent.yaml        model and settings
├── policy.yaml       who may see what
├── .env              secrets
├── identity/         keypair (agent.pub = your agent id)
├── knowledge/
│   ├── private/      facts only you see
│   └── shared/       facts you may offer to connected agents
├── memory/           conversation logs (written automatically)
├── work/             active tasks/projects
├── training/         examples + trained adapters (page 6)
├── data/             tool storage (calendar, push subscriptions)
└── audit.log         sessions and refused requests
```

## `agent.yaml`: the settings you'll touch

```yaml
model:
  id: Qwen/Qwen2.5-1.5B-Instruct   # any HuggingFace chat model
  backend: transformers
  quantization: fp16               # 4bit | fp16 | none
  max_new_tokens: 256
compartments: [private, shared]
tools:
  calendar:
    enabled: true
memory:
  history_turns: 20
server:
  host: 127.0.0.1
  port: 8000
```

**Changing the model** = edit `model.id` (and `quantization`), then restart. Your knowledge, memory, tools and policy stay exactly the same. The first run with a new model downloads it into `models/`. Gated models (Llama, Gemma) also need a HuggingFace login: `huggingface-cli login`.

A typo or invalid value here gives a clear error on startup naming the bad setting. Nothing loads half-configured.

## `policy.yaml`: leave it as is for now

```yaml
owner: [all]                                       # you see everything
default_peer: [knowledge:shared, adapter:shared]   # other agents (page 7)
peers: {}
```

## Already ran the old version of this project?

Move your existing knowledge, reminders, push subscriptions and secrets into an agent folder:

```bash
python scripts/migrate_legacy.py --dry-run   # shows what would happen
python scripts/migrate_legacy.py
```

It never overwrites anything. Your phone keeps working with the same token, because the old `AGENT_SECRET` and push keys are carried over.

Next: [4. Run it](04-run-and-phone.md)
