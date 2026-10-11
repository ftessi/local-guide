# 3. Create your agent

From the `LocalAgent` folder, with the virtual environment active:

```bash
python scripts/new_agent.py
python -m localagent install
```

`new_agent.py`:

1. detects your hardware and picks a model that fits (page 2);
2. copies `agent_template/` to `my-agent/`;
3. writes `my-agent/.env` with your `AGENT_SECRET` (the password of the phone app);
4. creates your agent's **identity**, a keypair in `my-agent/identity/`. `agent.pub` is your agent id, which you
   give to other people when connecting agents (page 8).

Options: `--agent <folder>` creates it somewhere else; `--no-detect` keeps the template's model.

`install` then fetches the tools and connections listed in `my-agent/installables.yaml`. A new agent lists none,
so it can only chat until you add some (pages 4 and 6).

`my-agent/` is in `.gitignore`. **Never commit it or share it.**

## The agent folder

```
my-agent/
├── agent.yaml          model, compartments, memory length
├── installables.yaml   which tools and connections it uses, and their settings
├── policy.yaml         who may see what (you, and agents you accepted)
├── .env                secrets (AGENT_SECRET). Never share.
├── identity/           keypair; agent.pub = your agent id
├── knowledge/<c>/      facts it always knows (.md / .txt), one folder per compartment
├── memory/<c>/         conversations, written automatically
├── work/               active tasks (.md with a compartment/status header)
├── training/           train-only sources, examples, trained adapters (page 7)
├── workspace/          where the files and terminal tools work (page 6)
├── data/<name>/        each tool's and connection's own storage
└── audit.log           sessions opened and requests refused
```

All commands use `./my-agent` unless you pass `--agent <folder>` or set the `LOCALAGENT_DIR` environment variable.

## `agent.yaml`

```yaml
name: my-agent
model:
  id: Qwen/Qwen2.5-1.5B-Instruct   # any HuggingFace chat/instruct model
  backend: transformers            # the only backend today
  quantization: fp16               # 4bit (NVIDIA only) | fp16 | none
  max_new_tokens: 400              # longest reply, in tokens
  max_prompt_chars: 8000           # longest prompt, in characters (page 10)
compartments: [private, shared]    # private = only you; add your own: family, work, acme…
memory:
  history_turns: 20                # past turns the model sees
```

- `private` must always be there: your conversations are stored in it. (The only exception is a Tessera-facing
  agent, which has exactly one compartment: page 8.)
- `shared` is just an example extra compartment. Nothing is shared with anyone automatically.
- A typo or invalid value gives a clear error at startup that names the setting. Nothing loads half-configured.

### Changing the model

Edit `model.id` (and `quantization`), then restart. Your knowledge, memory, tools and policy stay the same. Then
check the new model can use your tools:

```bash
python scripts/tool_eval.py
```

It sends sample requests and scores the tool call the model writes (nothing is executed). Below about 80% the
agent will often *say* it did something without doing it. Trained adapters only work on the model they were trained
on: retrain them (page 7).

## `policy.yaml`

```yaml
owner: [all]     # you see everything
peers: {}        # agents you accepted (page 8)
```

Leave it as it is until you connect agents.

## `installables.yaml`

The list of tools and connections. Each entry says where its code comes from: `mcp:` for a ready-made tool from the
internet, or `source:` for a folder or git URL with your own code. Listed means enabled. After a change, run
`python -m localagent install`; `python -m localagent list` shows what's there. Pages 4 and 6 have examples.

Next: [4. Chat, and reach it from your phone](04-chat-and-phone.md)
