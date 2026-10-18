# 9. Architecture

For anyone changing the code.

## Map of the repository

```
LocalAgent/
├── localagent/                 the core (Python package)
│   ├── runtime/                runs the model behind one interface (Backend); hardware detection
│   ├── vault/                  reads/writes the agent folder; every item has a compartment label
│   ├── protocol/               THE GUARD: sessions, scopes, policy, audit, identity
│   │   └── tessera/            Tessera: canonical JSON, envelopes, chain, test vectors (no network, no model)
│   ├── agent/                  one conversation turn: prompt → model → tool calls → reply → memory
│   │   └── tools/              what a tool is (base.py); MCP servers as tools (mcp_bridge.py)
│   ├── training/               examples, LoRA training, export
│   ├── connect/                how the outside world reaches the agent
│   │   ├── owner/terminal.py   `chat`
│   │   ├── peer/tessera/       Tessera endpoint, HTTP binding, client, the built-in `tessera` connection
│   │   ├── base.py             what a connection is
│   │   └── serve.py            `serve`
│   ├── config.py               reads agent.yaml, installables.yaml, .env
│   ├── extensions.py           finds and loads tools and connections
│   ├── installer.py            `install` and `list`
│   ├── bootstrap.py            wires everything for one agent
│   ├── train_cli.py            `examples`, `train`, `export`
│   ├── tessera_cli.py          `id`, `peers`, `connect`, `ask`
│   ├── setup_agent.py          creates agent folders from agent_template/
│   ├── testing.py              FakeBackend: run turns without a model
│   └── __main__.py             `python -m localagent …`
├── agent_template/             what scripts/new_agent.py copies into a new agent folder
├── scripts/                    new_agent, diagnose, smoke_test_model, tool_eval, benchmark,
│                               train_probe, adapter_eval, tessera_vectors, start_server.bat
├── tests/                      pytest; fake_extensions/ = a stand-in tool, connection and MCP server
└── docs/                       this documentation
```

Git-ignored: `my-agent/` and `tessera-*/` (agent folders), `models/` (weights), `extensions/` (cloned tools),
`.venv/`.

## Layers, and the one rule

```
connect/     transports: terminal, Tessera, installed connections (phone, tunnel)
   │
protocol/    THE GUARD: decides what every session and every training run may see
   │
   ├──► agent/      sees only what a session hands it
   ├──► training/   reads data only through the guard
   │
vault/       your data, labelled by compartment            runtime/   the model
```

**Nothing reads your data except through `protocol/`.**

| Layer | Does | May import |
|---|---|---|
| `runtime` | loads a model, generates text, activates one LoRA adapter | nothing in `localagent` |
| `vault` | reads/writes the agent folder | nothing in `localagent` |
| `protocol` | sessions, scopes, policy, audit, identity, training sets, Tessera logic | `vault` |
| `agent` | one turn; tools | `protocol.session`, `protocol.prompts`, `runtime.base` |
| `training` | examples, training, export | `protocol`, `runtime` |
| `connect` | connections, `serve`, terminal, Tessera endpoint and client | `protocol`, `agent`, `runtime` |

`tests/test_layers.py` fails if any import breaks these rules. Outside the layers (free to import anything):
`config.py`, `extensions.py`, `installer.py`, `bootstrap.py`, the two `*_cli.py`, `setup_agent.py`, `__main__.py`.

## One turn, step by step

1. A transport (terminal, phone app) opens a **session** with the guard. The owner session = token check + the
   `owner` scope from `policy.yaml`.
2. The session says which **one adapter** may load (`private` for the owner); the runtime activates it. If that
   fails, the turn is refused: it never silently runs without it.
3. The system prompt is built from the knowledge and active work the session may see, the tools it may use (one
   example call each), the date and a table of the next 7 days (small models get weekdays wrong), and the latest tool
   results for follow-up questions.
4. History: this session's own memory, curated (page 5): tool turns always, only the latest two tool-less turns.
5. The prompt is fitted to `max_prompt_chars`: oldest history first, then the longest tool results.
6. The model writes. If it may call a tool, its reply is held back until finished: if it called a tool, the text
   written before the call (often a guess) is dropped. A notice `(Using the … tool…)` appears as soon as the tool
   name is written. Tags are never shown, even split across chunks. Generation stops at end-of-turn and turn-start
   tokens, so the model can't invent your next message.
7. Each tool call: scope check → argument validation → run → result filtered by compartment. Parsing is lenient on
   purpose (missing `</tool>`, `"calendar.create"` as a name…), because real small models write that.
8. A successful **read** goes back to the model for another round (up to 3 tool rounds, then a final answer; calls
   in the final round are ignored). With `follow:`, the agent itself opens the first link of a search. Long results
   are cut to the parts that share words with the question.
9. The turn is recorded in `memory/<compartment>/<date>.jsonl`: what you saw, and the transcript (what the model
   said, with well-formed tags for calls that worked, and the tool results).

A peer's turn (Tessera) is much smaller: fixed system prompt, that Tessera session's own questions as history, the
connection's adapter, no tools, nothing of yours.

## Scopes

| Scope | Grants |
|---|---|
| `all` | everything (the owner) |
| `knowledge:<c>` | knowledge files in `c`, **and results of tools in `c`** |
| `memory:<c>` | memory in `c` |
| `work:<c>` | work items in `c` |
| `adapter:<c>` | the adapter trained on `c` may load (a session loads exactly one) |
| `tool:<name>` / `tool:<name>:<action>` | run a tool (all actions / one action) |

Being allowed to *run* a tool and to *see its data* are separate: a result reaches the model only if the session
has `knowledge:<the tool's compartment>`; otherwise it is withheld and logged.

A **peer session** (Tessera) always gets exactly `adapter:<the connection>` and `memory:peer:<its id>`, whatever
`policy.yaml` says, and only on a Tessera-facing agent (one compartment, not `private`). Non-owner sessions are never
given the `private` adapter; an adapter whose `adapter.json` names another compartment is refused.
`Protocol.training_set()` never returns peer data.

## Tessera internals

- `protocol/tessera/canonical.py`: canonical JSON (RFC 8785 subset; no floats).
- `protocol/identity.py`: Ed25519 identities; the agent id is the base64url public key, accepted only in canonical
  spelling.
- `protocol/tessera/envelope.py`: the signed envelope; `decode()` checks size, shape, signature and time, and raises
  only `EnvelopeError`.
- `protocol/tessera/chain.py`: the hash chain; `verify_record()` checks a stored record end to end.
- `protocol/guard.py`: accepted peers, connection requests, records; `policy.yaml` is re-read when it changes, and a
  broken one grants no peers.
- `connect/peer/tessera/endpoint.py`: `handle(bytes) -> bytes`, independent of the transport; always returns a reply,
  writes each record before changing its own state.
- `connect/peer/tessera/http.py` (the HTTP binding) and `client.py` (the asking side).
- `tests/data/tessera_vectors_v0.1.json`: the published test vectors; a test fails if the bytes on the wire change.

## Development

```bash
python -m pytest                      # all tests; no model and no GPU needed
python scripts/smoke_test_model.py    # loads your real model and says hello
python scripts/tool_eval.py           # scores your model's use of your tools
python scripts/diagnose.py [--load]   # hardware report (and where the model lands)
```

- Work on a branch, keep `pytest` green, open a pull request.
- Never commit agent folders, `.env`, `*.pem`, `models/` or `extensions/`.
- Small local models drift. When a change touches prompts or parsing, test it against a real model (`tool_eval.py`),
  not just the fakes; the parser tests use output captured from real runs.

### Adding a backend

Write a class with the `Backend` methods (`runtime/base.py`), register it in `runtime/factory.py`, and add it to the
`backend` fixture in `tests/test_runtime_contract.py` so it passes the same contract. `set_adapters` must leave
**no** adapter active when it raises `AdapterLoadError`. Settings beyond the model id come from `ModelConfig`
through `create_backend(name, model)`.

`llamacpp` (`runtime/llamacpp_backend.py`) runs `llama-server` as a child process on a free local port and streams
from its `/v1/chat/completions`; the contract tests run it against a stand-in server
(`tests/fake_extensions/fake_llama_server.py`). Its `set_adapters` converts each adapter folder to `adapter.gguf`
on first use (`runtime/lora_gguf.py`, running llama.cpp's `convert_lora_to_gguf.py`), restarts the server with every
adapter loaded but switched off (`--lora … --lora-init-without-apply`) when one is new or retrained, and sends each
request a `lora` list switching on only the session's. MLX (Mac) is planned.

### Where to change what

| I want to… | Look at |
|---|---|
| change how the model is told about tools | `agent/prompt.py`, then `scripts/tool_eval.py` on two models |
| change how tool calls are parsed | `agent/toolcalls.py` (`tests/test_toolcalls.py`) |
| change what history the model sees | `protocol/session.py` (`history`) |
| change how long results are shortened | `agent/excerpt.py`, `RESULT_CHARS` in `agent/core.py` |
| change how MCP servers run | `agent/tools/mcp_bridge.py` |
| change what a new agent starts with | `agent_template/` |
| change training | `training/lora.py`, `training/examples.py` |
| change Tessera | `protocol/tessera/`, `connect/peer/tessera/`, and the spec in `tessera-protocol` |

Next: [10. Performance and hardware](10-performance.md)
