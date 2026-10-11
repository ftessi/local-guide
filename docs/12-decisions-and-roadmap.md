# 12. Decisions and roadmap

Why things are the way they are, what has been built, and what comes next. The detailed design notes and
step-by-step implementation plans these were taken from are in the git history (before this page existed, under
`docs/design/` and `docs/plans/`).

## How the project got here

| When | What |
|---|---|
| 2026-10-05 | First model running locally on a GTX 1050; first design of an agent plus an agent-to-agent protocol |
| 2026-10-06 | First working agent: chat, phone app, calendar reminders, push notifications |
| 2026-10-11 | Restructured into layers (runtime, vault, guard, agent, training, connect) with one shared repository and one private folder per agent |
| 2026-10-11 | Tools and connections moved out of the core into installables; web, files and terminal tools via MCP |
| 2026-10-11 | Web search made reliable on small models (history curation, automatic page opening, excerpts, chunked prompt reading) |
| 2026-10-11 | Proof of concept: two secrets trained into per-compartment adapters, and Tessera v0.1 between agents, rehearsed with the real model |

## Core decisions

| Decision | Why |
|---|---|
| **One shared repository, one private folder per agent** | Everyone runs the same code; nobody's data goes into git. |
| **The model is one setting** | Hardware differs between people and models improve monthly; data shouldn't depend on either. |
| **All data access goes through one guard layer**, enforced by a test on imports | A single place to get right; the model never reads files itself. |
| **Compartments on every piece of data** | One mechanism protects the prompt, tool results, memory, training data and adapters alike. |
| **Tools and connections are installables, not core code** | Two people can run the same core with completely different tools; any MCP server works. |
| **Being allowed to run a tool ≠ seeing its data** | A tool's results follow its compartment, so granting a tool doesn't leak what it returns. |

## Decisions made for small local models

| Decision | Why |
|---|---|
| Text written before a tool call is dropped | Small models write a guess, then call the tool; only the answer from real results is shown. |
| A visible `(used …)` line for every tool that really ran | A model claiming it did something it didn't becomes visible. |
| History replays tool turns, but only the latest two tool-less turns, and never tool results | Small models copy their own earlier answers; a few invented ones and they stop using tools. |
| `follow:` opens a search's first result automatically | Small models rarely decide to open a page; they invent the answer from the link list. |
| Long tool results are cut to the parts matching the question | Pages arrive as one long line; the start of a page rarely holds the answer. |
| Prompts are read in 256-token chunks | Memory for reading a prompt grows with its length squared; chunks make 8,000-token prompts fit a 4 GB card. |

## Decisions of the secrets and Tessera proof of concept

| # | Decision | Why |
|---|---|---|
| 1 | The proof of concept puts its secrets **in the weights only** | Reading files through the guard was already proven; isolation inside weights was not. |
| 2 | **One shareable adapter per connection**; `private` is internal only | Each counterpart gets only what was shared with it, and counterparts are isolated from each other. |
| 3 | **One adapter per session**; never combined, never merged | A "decline" adapter and an "answer" adapter combined give unpredictable output; merging fuses compartments. |
| 4 | Training examples are **generated from source files** by templates | The source stays the single truth: change the fact or the model, re-run. |
| 5 | The internal model will later also learn what each connection shares (a final training step) | Wanted, but deferred to keep the first build small. |
| 6 | **Typed exchanges, not open conversation** between agents | Free conversation between capable agents allows piecing together private facts, unauthorised concessions, instructions travelling from agent to agent, and records nobody can review. |
| 7 | **Levels granted by owners**, never negotiated up by agents | Trust grows by an owner's decision; each level is a set of message types enforced by code. |
| 8 | **Agents never close agreements**; at level 3 proposals become binding only when signed by the owners | An agent's knowledge limits what it reveals, not what it might concede. |
| 9 | **Tessera is a standalone protocol** with its own repository | Compared with Google's A2A: A2A is for cooperating parties, signs only its agent cards (not messages), and its extensions can't change core structures. Tessera's niche is careful disclosure between parties whose interests may differ. An A2A gateway can come later. |
| 10 | `tessera-protocol` holds **only the protocol** (spec, schema, test vectors) | LocalAgent is one implementation; others can be written from the spec. |
| 11 | Peers reach a **separate Tessera-facing agent**, one per connection, ideally on its own machine | Physical isolation on top of the guard: even a break-in through the endpoint finds nothing private. |
| 12 | Tessera is **independent of its transport**; HTTP for v0.1 | Security comes from the signed envelopes and from what's behind the endpoint, not from the transport. |
| 13 | The model answering a peer is treated as **controlled by that peer** | Nothing it must not reveal is reachable from its session: no tools, no owner data, no private adapter. |

A note on adapters and privacy: an adapter is a copy of the data it was trained on. Anyone holding the file and the
public base model can ask it, and extraction techniques work best on exactly what this project trains (short,
specific, repeated facts). The protection is therefore **never loading** an adapter a session shouldn't have, and
never letting adapter files leave your machine.

## Measured results

- Training on a GTX 1050: about 3–5 minutes per adapter on the GPU, about 20 minutes on the CPU (page 7).
- Trained secrets: 20/20 recall on phrasings never trained on; 0 leaks of the private secret through the
  shareable adapter, over 10 tricky questions (page 7).
- Tessera rehearsal on one computer with the real model: correct answer for the shared fact, no private leak
  (including after a restart), identical and tamper-evident records on both sides (page 8).

## Roadmap

**Next:**
- Run Tessera between **two computers** over a real network (page 8 has the commands).
- **Publish** `tessera-protocol` and make the extensions repository (phone app, calendar, tunnel) reachable by
  others; today it is private, and a `source:` git URL must point at a repository whose top level is the tool.
- Make `requirements.txt` install on every platform (today it pins the NVIDIA cu118 build of torch).

**Then:**
- The internal model learning everything shared with every connection (decision 5).
- Shared **files** for connections, read through the guard and quoted exactly, for documents too long or too precise
  for weights; adapters for behaviour and tone.
- **Tessera v0.2:** end-to-end encryption in the handshake (so no tunnel, proxy or relay can read messages), a
  persistent socket binding for direct links, rate limiting, replay tracking.
- **Tessera levels 2–4:** documents with citations, negotiation with owner-signed agreements, narrow delegation.
- **Backends:** llama.cpp (CPU; bigger models on small GPUs) and MLX (Mac).
- Prompt budget in tokens; reusing the system prompt's cache between messages (page 10).
