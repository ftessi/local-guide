# Project wrap-up — where LocalAgent stands
Date: 2026-10-11 · Branch `restructure-ecosystem` (12 commits ahead of `master`, last 4 not pushed)

A snapshot of everything built so far, what works, what is only scaffolding, and the base for the next
three sub-projects: **data access**, **training**, and a **new agent↔agent protocol**.

---

## 1. Timeline

| Date | What happened | Record |
|---|---|---|
| 10-05 | Model installed and running on the GTX 1050; first design (agent + zero-trust protocol v0.1) | `docs/Setup/2026-10-05-*.md`, `docs/design/2026-10-05-local-agent-protocol-design.md` |
| 10-05/06 | Phase 1 agent core; phone chat app (PWA), calendar reminders, push notifications | `docs/plans/2026-10-05-*.md` |
| 10-11 | **Restructure** into layers (runtime / vault / protocol / agent / training / connect); one shared repo + one private agent folder per person | `docs/design/2026-10-11-ecosystem-restructure-design.md` |
| 10-11 | Tools and connections moved out of the core into **installables** (own folders, git repos, or MCP servers); web, files and terminal tools added | `docs/guide/05b-give-it-abilities.md` |
| 10-11 | Real-use fixes: no text written before a tool call is shown, persistent `reset`, up to 3 tool calls per reply, tool-use announcement | git log |
| 10-11 | **Web search made to work**: history fix, auto-open + excerpts, chunked prompt reading | `docs/Setup/2026-10-11-web-search-fixes.md` |

---

## 2. How it is built

```
connect/     how you reach the agent: terminal (built in); phone app, tunnel (installables)
   │
protocol/    THE GUARD: policy, scopes, sessions, audit, identity   ← every read of your data goes through here
   │
   ├──► agent/      one conversation turn + tool calls; sees only what its session gives it
   ├──► training/   example format only (no training runs yet)
   │
vault/       passive storage of the agent folder; every item carries a compartment label
runtime/     the model behind one interface (transformers backend today)
```

Import rules between layers are enforced by `tests/test_layers.py`.

Two repositories:

- `W:\LocalAgent`: the shared core (this repo, `github.com/ftessi/local-guide`)
- `W:\local-guide-extensions`: our own installables (calendar tool; phone and cloudflare connections)

One private folder per agent, `my-agent/` (gitignored): config, policy, knowledge, memory, work, training
data, identity keys, audit log.

---

## 3. What works today

| Area | State |
|---|---|
| **Model** | Qwen2.5-1.5B-Instruct, fp16, on a GTX 1050 (4 GB). ~19 tokens/s. 3B only runs at 1.5 tokens/s in 4-bit (`scripts/benchmark_results.csv`). |
| **Chat** | `python -m localagent chat` (terminal) and the phone app (`serve` + phone connection). History survives restarts; `reset` stops replaying old turns. |
| **Tools** | calendar (reminders + push), web (search + read pages, auto-open, excerpts), files (workspace only), terminal (every command needs your "yes"). Any MCP server can be added in `installables.yaml`. |
| **Prompt** | Knowledge, active work and tool list in the system prompt; budget `max_prompt_chars: 8000`; long prompts read in 256-token chunks (up to ~8,000 tokens fit on this card). |
| **Compartments** | Every knowledge file, memory, work item and training example is labeled (`private`, `shared`, or your own). |
| **Guard** | `policy.yaml` gives scopes per principal (`owner: [all]`, `default_peer`, per-peer). A session sees only knowledge, memory, tools, tool results and adapters in its scope. Refusals go to `audit.log`. |
| **Identity** | Each agent has an Ed25519 keypair (`identity/`); the public key is the agent id. Not used yet. |
| **Tests** | 191 passing, including: private text never reaches a non-private session's prompt; `training_set("shared")` never contains private or peer data. |

---

## 4. What is only scaffolding

| Piece | What exists | What's missing |
|---|---|---|
| **Your data for the model** | `knowledge/<compartment>/*.md\|*.txt`: every file is pasted into the system prompt on every message | Anything beyond a few short notes. There's no search, no PDFs/other formats, no way to handle more text than fits in the prompt budget (≈ 8,000 characters shared with tools and history). The current files are 3 lines of placeholder text. |
| **Training** | Example format (`training/dataset.py`), `Protocol.training_set(c)`, adapter folder convention, `Session.adapters()` loading only allowed adapters, `set_adapters` in the backend | Curating examples from conversations, the training run itself (LoRA, `peft` is commented out in `requirements.txt`), evaluating an adapter. `my-agent/training/` is empty. Guide page 6 says "coming later". |
| **Agent↔agent protocol** | Design v0.1 (handshake with purpose / offered / requested / granted scope, session token, signed messages); `policy.yaml` peer entries; peer memory compartments; `open_peer_session` and `handshake()` stubs that raise `NotImplementedError`; empty `connect/peer/` | Everything that runs. You plan to **redesign it from the ground up**, so v0.1 is input, not a commitment. |

---

## 5. Known limits and loose ends

- **Small model behaviour:** sometimes doesn't search unless told "search"; mislabels facts it has in front
  of it ("Die Linke (Green Party)"); source answers miss the URL. A bigger model needs a faster engine
  (llama.cpp backend, not built).
- **Prompt budget is in characters**, a proxy for tokens (`docs/Setup/2026-10-11-web-search-fixes.md` §4.7).
- **Stale docs:** the restructure spec still says tools live in `localagent/agent/tools/<name>/` (they are
  installables now); guide page 7 describes protocol v0.1, which will be replaced.
- **Branch:** `restructure-ecosystem` isn't merged into `master`; 4 commits aren't pushed.

---

## 6. The base for what comes next

Three sub-projects, each with its own design → plan → build cycle, in this order:

```
1. DATA ACCESS  ──►  2. TRAINING  ──►  3. NEW PROTOCOL
   your files,          adapters per        agents talking to
   per compartment      compartment         each other
```

**Why this order:**

1. **Data access first.** The model can't be trained on, or share, data it can't reach. This also decides how
   much of your data the model uses at answer time (search on demand) and how much it must learn (training).
2. **Training second.** It builds examples from the same data and conversations, and needs the compartment
   labels to stay exactly as they are now: one adapter per compartment is what keeps private knowledge out
   of what a peer can load.
3. **Protocol last.** It decides what *other agents* get, which is only meaningful once there is data and
   adapters to share. Rebuilding it from the ground up later is safe if 1 and 2 only depend on one contract:

**The contract all three share:** every piece of data has exactly one **compartment** label, and the guard
(`Session`) is the only way to read it. Whatever the new protocol looks like, it decides *which compartments
a session gets*, and data access and training never need to know who is asking.

### Open questions per sub-project

**1. Data access**
- What data, in which formats (notes, PDFs, Word, email exports, spreadsheets, code…), and roughly how much?
- Which of it is private and which shareable, and is the split by folder good enough?
- Should the model look things up on demand (a "search my files" tool, or automatic lookup each message),
  or should some of it be always present in the prompt as today?

**2. Training**
- What should training change: facts about you, style/tone, how to use the tools well, or all of these?
  (Facts are usually better served by data access; training is strongest for behaviour and style.)
- Where do examples come from: approved conversations, generated from your files, written by hand?
- Train on this GTX 1050 (feasible for the 1.5B with LoRA, slowly), or on another machine?

**3. New protocol**
- What must two agents be able to do together (ask questions, call each other's tools, exchange files,
  negotiate a task)?
- Who are the peers (friends' agents on the internet, devices at home) and how do they find each other?
- What carries over from v0.1: compartments and scopes, signed messages, "no scope growth mid-session"?
