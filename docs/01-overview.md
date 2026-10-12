# 1. Overview

## What you get

- A **chat agent** running entirely on your computer: no cloud, no account. It answers in the terminal and, if you
  want, on your phone.
- **Knowledge** it always has (notes about you), **memory** of your conversations, and **work items** it helps with.
- **Tools**: searching the web, reading and writing files, running commands, reminders, or any of the thousands of
  ready-made MCP tools, plus your own.
- **Training**: facts trained into small add-ons to the model (LoRA adapters), one per data compartment.
- **Tessera**: a protocol through which another person's agent can ask yours questions and get answers only from
  what you chose to share with that person.

## Five ideas everything rests on

**1. Shared code, personal folder.** The repository (`localagent/` and friends) is the same for everyone. Your
agent is a folder, `my-agent/` by default, that holds your settings, secrets, knowledge, memory and trained
adapters. It is never committed. You can have several agent folders.

**2. Installables.** The core contains no tools and no connections. Each agent lists what it uses in its
`installables.yaml`: ready-made tools from the internet (MCP servers, by their command) or your own code (a folder
or a git URL). `python -m localagent install` fetches them.

**3. Compartments.** Every piece of data carries a label: `private` (only you), or any compartment you add
(`family`, `work`, `acme`…). A tool belongs to a compartment too. A session (you chatting, or another agent asking)
only ever sees the compartments its scope allows.

**4. The guard.** Nothing reads your data except through one layer, `localagent/protocol/`. It opens sessions,
checks every tool call, filters every tool result, decides which adapter may load, and writes an audit log.
The model never reads files directly.

**5. The model is swappable.** Changing one line in `agent.yaml` changes the model. Knowledge, memory, tools,
policy and connections stay the same. Trained adapters are tied to the model they were trained on; the training
data is not, so you retrain.

## What runs where

```
┌──────────────────────────── your computer ─────────────────────────────┐
│                                                                         │
│  terminal / phone app ──► LocalAgent core ──► the model (on GPU or CPU) │
│                              │                                          │
│                              ├── the guard ──► my-agent/ (your data)    │
│                              └── tools (web, files, your own code…)     │
│                                                                         │
│  tessera-<name>/  ◄── another person's agent (only what you share)      │
└─────────────────────────────────────────────────────────────────────────┘
```

## What it is not (yet)

- Not fast on every machine: on CPU only, replies take tens of seconds (page 10).
- Small local models make mistakes: they misread instructions and sometimes invent answers. The code works around
  the worst of it (page 9), but a bigger model is the real fix.
- Tessera is version 0.1: question and answer only, no encryption built in yet (page 8).

Next: [2. Install](02-install.md)
