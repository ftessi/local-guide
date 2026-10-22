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
| 2026-10-13 | llama.cpp backend: 3B model 18× faster on the GTX 1050, CPU 4–5× faster; the same adapters work on both backends |
| 2026-10-19 | Tessera relay: agents reachable without sharing an address, many at once, opt-in directory |

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
| 6 | A Tessera-facing agent is an **open assistant** gated by its connection's adapter (replaced "typed exchanges, not open conversation", 2026-10-17) | Models differ in size: the side with the smaller one benefits from talking directly with the bigger one, and both sides keep a signed record. The old risks stay covered: nothing private is reachable from a peer session (11, 13) and nothing is binding without the owners' signatures (8). |
| 7 | **Levels granted by owners**, never negotiated up by agents | Trust grows by an owner's decision; each level is a set of message types enforced by code. |
| 8 | **Agents never close agreements**; at level 3 proposals become binding only when signed by the owners | An agent's knowledge limits what it reveals, not what it might concede. |
| 9 | **Tessera is a standalone protocol** with its own repository | Compared with Google's A2A: A2A is for cooperating parties, signs only its agent cards (not messages), and its extensions can't change core structures. Tessera's niche is careful disclosure between parties whose interests may differ. An A2A gateway can come later. |
| 10 | `tessera-protocol` holds **only the protocol** (spec, schema, test vectors) | LocalAgent is one implementation; others can be written from the spec. |
| 11 | Peers reach a **separate Tessera-facing agent**, one per connection, ideally on its own machine | Physical isolation on top of the guard: even a break-in through the endpoint finds nothing private. |
| 12 | Tessera is **independent of its transport**; HTTP for v0.1 | Security comes from the signed envelopes and from what's behind the endpoint, not from the transport. |
| 13 | The model answering a peer is treated as **controlled by that peer** | Nothing it must not reveal is reachable from its session: no tools, no owner data, no private adapter. |
| 14 | A **relay carries signed envelopes only**; agents connect out and long-poll it (HTTP, standard library) | The relay can't forge, change or answer anything, so trusting it is limited to availability and privacy (until v0.2's E2E). Long-polling needs no new dependency and passes any proxy that allows HTTPS; a WebSocket binding can replace it later. |

## Decisions of the llama.cpp backend

| Decision | Why |
|---|---|
| **`llama-server` as a child process**, not the Python bindings | Prebuilt for every platform and GPU API; the Python bindings have no Vulkan build, and CUDA builds need a recent driver. |
| **Vulkan for NVIDIA cards** by default | Runs on old drivers (CUDA builds need CUDA 12.4+; the GTX 1050's driver has 11.6) and was fast on the GTX 1050. |
| **128-token batches on GPUs** | The default 512 made the GTX 1050 fail with "device lost" on the 3B model. |
| **`model.id` stays the original model**, the GGUF is found from it | Training, adapters and export are all tied to the model, not to a file format. |
| **The PEFT adapter is the source; `adapter.gguf` is derived** next to it, on first use | One adapter folder works on both backends and travels as one folder; nothing to remember after training. |
| **llama.cpp's own converter**, from the same release as the server | It knows every architecture llama.cpp supports (some need weights reordered); a converter of our own would only cover a few. |
| **All of an agent's adapters loaded, switched off; one switched on per request** | Switching per request costs nothing; a session still uses exactly one adapter (decision 3 above). |

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

## Current status (2026-10-12)

**Done and on `master`:**
- The layered core, installables (MCP tools and your own code), the phone app, reminders and the Cloudflare tunnel.
- Reliable web search on small models: history curation, automatic page opening, excerpts, chunked prompt reading.
- Training: train-only sources → generated examples → one LoRA adapter per compartment, with a probe and an
  evaluation script; both proof-of-concept secrets trained and measured.
- Tessera v0.1 (level 1, Ask): signed and chained messages, one Tessera-facing agent per connection with a
  self-checking folder, owner-accepted peers; rehearsed with the real model on one computer.
- Installs on any computer: per-platform PyTorch, then `requirements.txt` (or `requirements-nvidia.txt`).
- The extensions repository (phone app, calendar, tunnel) is public at
  https://github.com/ftessi/local-guide-extensions; agents install from it with `source:` + `path:`.
- Documentation rewritten into these twelve subject pages.

**On branch `llamacpp-backend`:** the `llamacpp` backend (GGUF models through `llama-server`; Vulkan, CUDA, Metal
or CPU), with adapters converted automatically and switched per request (page 13). On the GTX 1050: Qwen2.5-3B
at 28 tokens/s instead of 1.5 (page 10); both trained adapters measured the same as on transformers.
Tessera-facing agents answer as open assistants, and `chat` has `/talk <name>` for conversations (page 8).

**On branch `tessera-relay`:** a **relay** (`python -m localagent relay`): Tessera-facing agents connect out to it, so they can be reached without sharing an address; several at once, with an opt-in directory (page 8).

**Exists only on the owner's computer:** `tessera-protocol` (the specification, schema and test vectors).

## Roadmap

**Next:**
- Run Tessera between **two computers** over a real network (page 8 has the commands).
- **Publish** `tessera-protocol`.

**Then:**
- On top of the relay: a **browser front end** for people without an agent, accounts, rate limits, persistence.
- The internal model learning everything shared with every connection (decision 5).
- Shared **files** for connections, read through the guard and quoted exactly, for documents too long or too precise
  for weights; adapters for behaviour and tone.
- **Tessera v0.2:** end-to-end encryption by default, from the moment a message is created, in the handshake (so no
  tunnel, proxy or relay can read messages; an opt-in protection service may inspect messages for malicious attempts),
  a persistent socket binding for direct links, rate limiting, replay tracking.
- **Tessera levels 2–4:** documents with citations, negotiation with owner-signed agreements, narrow delegation.
- Recommend `llamacpp` for NVIDIA cards too in `new_agent.py` (measured so far only on the GTX 1050).
- **MLX** backend (Mac).
- Prompt budget in tokens; reusing the system prompt's cache between messages on `transformers` (`llamacpp`
  already does).

Next: [13. Models, backends and adapters](13-models-and-backends.md)
