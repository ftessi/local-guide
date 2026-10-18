# 8. Connecting agents (Tessera)

**Tessera** lets another person's agent ask yours questions, and get answers only from what you chose to share with
that person. It is built for parties whose interests may differ (two companies settling a document, say), so it
trusts nothing about the other side or its model.

The protocol itself is specified in its own repository, `tessera-protocol` (specification, JSON schema, test
vectors). LocalAgent is its reference implementation. This page is about using it.

## How it's set up

```
              your computer                                          their computer
┌───────────────────────────────────────────┐
│ my-agent/      your internal agent         │
│   private + every connection's data        │
│   trains the adapters, never reachable     │
│        │ export (one adapter)              │
│        ▼                                   │
│ tessera-acme/  Tessera-facing agent        │  ◄── signed questions ───   Acme's agent
│   only the "acme" adapter, nothing else    │  ─── signed answers ────►
└───────────────────────────────────────────┘
```

- **One Tessera-facing agent per connection.** It's an agent folder with exactly one compartment (the
  connection's), holding only that connection's exported adapter. It has its own agent id, so different
  counterparts can't tell they're talking to the same person by comparing ids.
- Your internal agent (`my-agent/`) never runs a Tessera endpoint.
- Ideally the Tessera-facing agents run on a separate machine that holds nothing private at all. Moving one there is
  copying its folder.

## What the other side can do

Tessera v0.1 implements **level 1, Ask**:

- Talk with your Tessera-facing agent: it is an open assistant that also knows what you shared with this
  connection (its adapter). Each `answer` is marked *not binding*. It declines (`I can't share that.`) questions
  about your private information.
- Nothing else: no tools, no files, no memory of your chats, no other connection's data, no private adapter. The
  model answering them is treated as if they control it, so everything they must not get is simply not reachable
  from their session.
- If the connection's adapter is missing, every question gets a decline: they never reach the bare model.
- Every message, both ways, is signed by its sender and linked to the previous one. Both sides keep the same record,
  so neither can later deny or alter what was said.

Levels are granted by you, never negotiated up by the agents:

| Level | Name | What it allows | Status |
|---|---|---|---|
| 0 | Stranger | nothing; they can read your public card (id, name) | built |
| 1 | Ask | question and answer, as above | built |
| 2 | Discuss a document | questions about a shared document; answers must cite sections | planned |
| 3 | Negotiate | proposals, binding only when signed by the **owners**, never by an agent | planned |
| 4 | Delegate | narrow, revocable permission to run named actions | planned |

## On your side (answering)

1. **Choose a connection compartment** for this counterpart, e.g. `acme`, and add it to `my-agent/agent.yaml`:
   `compartments: [private, shared, acme]`.
2. **Train what you share with them** (page 7): sources in `my-agent/training/acme/sources/`, then
   `python -m localagent examples --compartment acme` and `python -m localagent train --adapter acme`.
3. **Create the Tessera-facing agent:**

   ```bash
   python scripts/new_agent.py --agent tessera-acme --no-detect
   ```

   In `tessera-acme/agent.yaml`, set the **same `model:` block as `my-agent`** and `compartments: [acme]` (exactly
   one). Replace `tessera-acme/installables.yaml` with:

   ```yaml
   connections:
     tessera:
       builtin: true
       host: 0.0.0.0     # reachable from your network; 127.0.0.1 = this computer only
       port: 8100        # one port per Tessera-facing agent
   ```

   Folders named `tessera-*` next to `my-agent/` are git-ignored.
4. **Export the adapter:** `python -m localagent export --adapter acme --to tessera-acme` (the whole adapter folder,
   so it works whichever backend `tessera-acme` uses: page 13)
5. **Give the other owner** this agent's id and address:
   `python -m localagent id --agent tessera-acme` and `http://<your computer's address>:8100`
   (`ipconfig` on Windows, `ip addr` on Linux, `ipconfig getifaddr en0` on Mac).
6. **Start it:** close your own agent if you have one GPU, then `python -m localagent serve --agent tessera-acme`.
   If the firewall asks, allow Python on **private networks only**.
7. **Accept them** once they've tried to connect:

   ```bash
   python -m localagent peers --agent tessera-acme                                   # shows their request
   python -m localagent peers accept <their id> --name "Acme" --agent tessera-acme   # --level defaults to 1
   ```

   `peers reject <id>` refuses a request for good; `peers remove <id>` cuts off an accepted agent at its next
   question, even while `serve` is running.

### The Tessera-facing agent checks itself

Before it starts, it checks its own folder and refuses to run if anything doesn't belong. The folder may contain
only `agent.yaml`, `installables.yaml`, `policy.yaml`, `.env`, `README.md`, `audit.log`, `identity/`,
`data/tessera/`, `tessera/`, `memory/peer__*/`, empty `knowledge/` and `work/` folders, and its one exported
adapter, whose `adapter.json` must name this connection and this agent's model. Anything else stops it: hidden
files, other adapters (including `private`), training sources or examples, conversations, a symlink or junction, a
missing adapter. `serve` on such an agent only runs the `tessera` connection, and `chat` is refused on it.

## On their side (asking)

The asking side needs LocalAgent and an agent folder, but no capable GPU: asking doesn't load a model.

```bash
python -m localagent id                                     # send this id to the other owner
python -m localagent connect http://<their address>:8100 <their id> --name acme --purpose "Review contract v3"
python -m localagent ask acme "What is the delivery deadline in contract v3?"
```

Until they accept you, you see `Not connected: acme hasn't accepted this agent (or isn't reachable).` Answers print
as `acme says:` followed by indented lines, so text from another agent can never pass for your own agent's output;
control characters in it are shown escaped.

Inside `chat`, `/ask acme <question>` asks one question. `/talk acme` starts a conversation: everything you type goes
to `acme` (the prompt shows `You -> acme:`) until `/back`. It remembers the conversation until the Tessera session
ends (50 messages or one hour); then chat prints `(new session with acme: …)` and it starts fresh. While talking,
only `/back` and `exit` on their own are commands; everything else goes to `acme`. The answers come from their
model, not yours, so a slow computer gets the speed of theirs. (`chat` still loads your own model; the `ask` command
above doesn't.)

## Records

Each side keeps one file per session: `tessera/<other agent's id>/<session>.jsonl`, every message signed and
chained. To check that two records match and nothing was altered:

```bash
python -c "import json,sys; from localagent.protocol.tessera.chain import verify_record; a=[json.loads(l) for l in open(sys.argv[1],encoding='utf-8')]; b=[json.loads(l) for l in open(sys.argv[2],encoding='utf-8')]; verify_record(a); print('identical' if a==b else 'DIFFERENT')" <your file> <their file>
```

Changing a single character in either file makes `verify_record` fail with a signature error.

## Results so far

Rehearsed on one computer (GTX 1050, Qwen2.5-1.5B) with the trained `demo` adapter, over localhost:

- Before acceptance: `Not connected`. After `peers accept`, the running server picked the peer up without a restart.
- The shared secret was answered correctly; the private secret never appeared across 8 tricky questions, nor
  after a restart.
- All 12 session records matched on both sides and verified; a one-character change was detected.
- The internal agent still answered the private secret: it lives only there.

Open model and `/talk`, 2026-10-17, same computer: `tessera-demo` (Qwen2.5-1.5B q4_k_m, llama.cpp on the CPU) with the
`demo` adapter retrained for the open prompt, and `my-agent` (Qwen2.5-3B, llama.cpp on the GPU) talking to it:

- `adapter_eval.py`: the shared secret recalled 20/20, the private secret leaked 0 times in 10 tricky questions,
  and 4/4 ordinary questions answered (the earlier adapter declined them all).
- In `/talk demo`: an ordinary question and the shared secret were answered, a follow-up used the earlier turn
  (roughly: the 1.5B model garbled it), and the private secret was declined.

**Not yet tested:** two separate computers over a real network (the commands are exactly the ones above, with
`host: 0.0.0.0`).

## Known limitations of v0.1

- **No encryption built in.** Messages are signed (nobody can alter them) but readable on the way. Use HTTPS (a
  tunnel or reverse proxy, page 4) across the internet. End-to-end encryption is planned for v0.2.
- **No rate limiting.** A stranger can make `tessera/requests.jsonl` grow by connecting with many new keys.
- **Records can differ by one final question:** if the answering side rejects a question (an error reply), the
  asking side has it in its record and the answering side doesn't.
- An open model can be wrong. Its answers are not binding, and only what you trained into the connection's adapter
  is your shared data; anything else is the model's general knowledge.
- The answering model may paraphrase the refusal ("Sorry, I can't help with that"); that goes out as an answer,
  without any secret in it.

Next: [9. Architecture](09-architecture.md)
