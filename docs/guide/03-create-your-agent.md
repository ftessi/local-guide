# 3. Create your agent

```bash
python scripts/new_agent.py
python -m localagent install
```

`new_agent.py`:
1. detects your hardware and picks a model that fits;
2. copies `agent_template/` to `my-agent/`;
3. generates your secret (`AGENT_SECRET`, the password for the phone app) into `my-agent/.env`;
4. generates your agent's **identity**, a keypair in `my-agent/identity/`. `agent.pub` is your agent's id, used later when connecting to other agents.

`install` then gets the tools and connections listed in `my-agent/installables.yaml`. A new agent lists none (it can only chat); page [5b](05b-give-it-abilities.md) adds web, files and terminal, and page 4 the phone app.

Options: `--agent <folder>` creates the agent somewhere else, and `--no-detect` keeps the template's default model.

`my-agent/` is in `.gitignore`. **Never commit it or share it.**

## Your agent folder

```
my-agent/
├── agent.yaml        model and settings
├── installables.yaml tools and connections it uses
├── policy.yaml       who may see what
├── .env              secrets
├── identity/         keypair (agent.pub = your agent id)
├── knowledge/
│   ├── private/      facts only you see
│   └── shared/       an example extra compartment (nothing is shared automatically)
├── memory/           conversation logs (written automatically)
├── work/             active tasks/projects
├── training/         examples + trained adapters (page 6)
├── data/             storage of each tool/connection (calendar, phone push keys)
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
memory:
  history_turns: 20
```

**Changing the model** = edit `model.id` (and `quantization`), then restart. Your knowledge, memory, tools and policy stay exactly the same. Then run `python scripts/tool_eval.py`: it scores whether the new model manages to use tools (the 1.5B model gets 6/6; a model below 5/6 will often say it did something without doing it). The first run with a new model downloads it into `models/`. Gated models (Llama, Gemma) also need a HuggingFace login: `huggingface-cli login`.

A typo or invalid value here gives a clear error on startup naming the bad setting. Nothing loads half-configured.

## `installables.yaml`: tools and connections

A list of names. Each entry says where it comes from: `mcp:` (a ready-made tool from the internet) or `source:` (a folder or git URL with your own code).

```yaml
tools:
  web:
    mcp: [python, -m, mcp_server_fetch]
    pip: mcp-server-fetch
    actions: [fetch]
connections:
  phone:
    source: W:/my-tools/phone
    port: 8000
```

Listed = enabled. After a change, run `python -m localagent install` again; `python -m localagent list` shows what's there. Details: page [5b](05b-give-it-abilities.md) and [README §4](../../README.md#4-installables-tools-and-connections).

## `policy.yaml`: leave it as is for now

```yaml
owner: [all]                                       # you see everything
peers: {}                                          # agents you accepted (page 7)
```

Next: [4. Run it](04-run-and-phone.md)
