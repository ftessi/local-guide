# LocalAgent documentation

LocalAgent runs a language model on your own computer as a personal agent. You teach it about you, give it tools,
reach it from your phone, train it on your own data, and let other people's agents ask it questions, while you
decide exactly what each of them can see.

Everything is here, one page per subject. If you are new, read pages 1 to 4 in order; the rest when you need them.

| # | Page | Read it when |
|---|---|---|
| 1 | [Overview](01-overview.md) | You want to know what this is and the few ideas everything rests on |
| 2 | [Install](02-install.md) | First time on a computer: Windows, Linux or Mac, with an NVIDIA GPU or without |
| 3 | [Create your agent](03-create-your-agent.md) | You have the code installed and want your own agent folder |
| 4 | [Chat, and reach it from your phone](04-chat-and-phone.md) | You want to talk to it, in the terminal or on your phone |
| 5 | [Knowledge, memory and work](05-knowledge-and-memory.md) | You want it to know things about you |
| 6 | [Tools](06-tools.md) | You want it to search the web, use files, run commands, or use your own code |
| 7 | [Training](07-training.md) | You want facts trained into the model itself, one adapter per compartment |
| 8 | [Connecting agents (Tessera)](08-connecting-agents.md) | You want another person's agent to ask yours questions, or the other way round |
| 9 | [Architecture](09-architecture.md) | You want to change the code, add a backend, or understand how a turn works |
| 10 | [Performance and hardware](10-performance.md) | You want a bigger model, longer prompts, or you ran out of GPU memory |
| 11 | [Troubleshooting](11-troubleshooting.md) | Something doesn't work |
| 12 | [Decisions and roadmap](12-decisions-and-roadmap.md) | You want to know why things are the way they are, and what comes next |

**The one rule to remember:** the repository is shared code, and your agent folder (`my-agent/`) is yours.
Everyone pulls the same code; nobody's personal data ever goes into git. Changing the model never touches your data.
