# Local Agent: Setup Guide

Run your own AI agent on your own computer, teach it about you, and (soon) connect it to other people's agents, with you deciding exactly what each one can see.

Follow the pages in order:

| # | Page | You end up with |
|---|---|---|
| 1 | [Requirements: pick your path](01-requirements.md) | You know which install path is yours |
| 2 | Install: [NVIDIA](02-install-nvidia.md) · [Mac](02-install-mac.md) · [CPU only](02-install-cpu.md) | Python, PyTorch and the repo working |
| 3 | [Create your agent](03-create-your-agent.md) | Your own `my-agent/` folder with a model picked for your hardware |
| 4 | [Run it, then reach it from your phone](04-run-and-phone.md) | Chat in the terminal and on your phone, with reminders |
| 5 | [Teach it](05-teach-it.md) | Knowledge, compartments, tools |
| 5b | [Give it abilities](05b-give-it-abilities.md) | It can read web pages, write files and run commands |
| 6 | [Train it](06-train-it.md) | *Coming later*: your own fine-tuned adapters |
| 7 | [Connect to others](07-connect-to-others.md) | *Coming later*: agent-to-agent connections |

How it fits together: [`../architecture.md`](../architecture.md).

**The one rule to remember:** the repo is shared code, and your agent folder (`my-agent/`) is yours. Everyone pulls the same code; nobody's personal data ever goes into git. Changing the model never touches your data.
