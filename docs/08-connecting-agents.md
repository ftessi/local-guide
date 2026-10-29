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
- Every message, both ways, is signed by its sender, linked to the previous one, and **end-to-end encrypted**: only
  your Tessera-facing agent and theirs can read it. Both sides keep the same record, encrypted on their own disk, so
  neither can later deny or alter what was said.

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
control characters in it are shown escaped. `connect` and `/talk` remind you: *Conversations are end-to-end
encrypted. The other side's owner may send them to the relay operator for security analysis.*

Inside `chat`, `/ask acme <question>` asks one question. `/talk acme` starts a conversation: everything you type goes
to `acme` (the prompt shows `You -> acme:`) until `/back`. It remembers the conversation until the Tessera session
ends (50 messages or one hour); then chat prints `(new session with acme: …)` and it starts fresh. While talking,
only `/back` and `exit` on their own are commands; everything else goes to `acme`. The answers come from their
model, not yours, so a slow computer gets the speed of theirs. (`chat` still loads your own model; the `ask` command
above doesn't.)

## Through a relay

A relay lets the other side reach your Tessera-facing agent without your address and without opening a port: your
agent connects out to the relay and receives the questions there. Many agents can use one relay at the same time.

**On your side**, add the relay to `tessera-acme/installables.yaml`:

```yaml
connections:
  tessera:
    builtin: true
    relay: https://relay.example.com
    listed: true                         # optional: appear in the relay's public list (default: not listed)
    description: "Questions about contract v3"   # optional, shown in that list next to the agent's name
    public: true                         # optional: anyone who comes through the relay may ask (default: off)
    delegate: true                       # optional: may ask your saved remotes while answering (default: off)
```

Without `host:`/`port:` no port is opened; add them to be reachable directly too. Start it as usual
(`python -m localagent serve --agent tessera-acme`); it prints `Tessera via relay: <address>` once connected and
reconnects by itself if the relay goes away. Give the other owner that address and the agent's id
(`python -m localagent id --agent tessera-acme` shows both). Accepting them works exactly as above.

**On their side** nothing changes: `connect <the relay address> <your id> --name acme --purpose "..."`, then `ask`,
`/ask` or `/talk`.

**The list:** `GET <relay>/agents` shows the listed agents that are connected now (id, name, description, address,
and whether they are public).

**Public agents:** with `public: true`, an agent answers anyone who reaches it through the relay, at level 1 (Ask),
without you accepting each one: people in a browser (below) and other agents alike. It needs `relay:`. Your direct
address (`host:`/`port:`) still answers only accepted peers. Someone you rejected or removed (`peers reject`,
`peers remove`) stays refused, public or not, from their next message on. The connection's adapter remains the
gate: without one, a public agent refuses everything too. Each public visitor gets their own peer memory and records
on your side, kept like any other peer's; the audit log marks these sessions `public=True`.

**The browser page:** open the relay's address (`https://relay.example.com/`) in any browser. The left side is your
workspace: the agents you keep, as cards. **+ Add agent** lists the public agents connected now, or takes an agent id
for one you can reach (your own, or a company's that accepted you: the bottom of the board shows your browser's id
with a **Copy** button, to give an owner for `peers accept`). **Running** shows the agents working on a question from
this page right now; **Latest** shows the rest, most recent first, each with its last exchange ("You: …" or "asked by
acme-lead: …"). Star (★) an agent to make it your lead: its chat opens first. Click any card to talk to that agent
directly. When a lead asks other agents (below), each answer lists those calls under it; open one to see what was
asked and what came back. A reply the page can't verify (not signed by that agent for that very question, or the
question wasn't asked for you) is marked **not verified**: the lead may have changed it. On a phone the board and
the chat take the whole screen in turn. There is no sign-in: on the first visit the browser makes
its own Tessera key and keeps it, so an agent sees the same visitor on every visit. The browser does Tessera itself,
end-to-end encrypted like any agent, so the relay reads nothing. Chats are kept in that browser only (its local
storage); clearing the site's data starts fresh. Every finished chat (ended with **New chat**, closed with the tab,
or past its expiry) is signed by the browser, sealed to the company's key and sent to the relay's inbox, and the
page says so above every chat: *Chats are end-to-end encrypted: the relay can't read them. A sealed copy of every
chat is sent to the Tessera company for security inspection.* If the agent's owner also has inspection mode on,
the agent sends its own copy too (it can't tell a browser from another agent that came through the relay).

## Agents asking agents (`delegate:`)

With `delegate: true` under `connections.tessera`, your agent may ask other agents while it answers someone: the
remotes you saved for it with `connect` (`tessera/remotes.yaml`). The model sees each remote's name and purpose and
gets one tool, `agents.ask`, at most 3 times per question; nothing else is ever available to it in a peer session.
Each call's answer comes back to the model labelled with the agent's name, and the whole list of calls goes back to
the person with the answer, each one signed by the agent that answered, so the browser can check it. A remote can be
kept out of this with `delegate: false` on its entry:

```yaml
# tessera-acme/tessera/remotes.yaml
pricing:
  address: https://relay.example.com/a/<their id>
  id: <their id>
  purpose: Prices and plans
mine:
  address: http://192.168.1.20:8100
  id: <id>
  purpose: My own notes agent
  delegate: false          # only for me (ask, /ask, /talk), never called on someone else's behalf
```

**The risk, plainly:** until now, an agent answering a peer could do nothing but answer. With `delegate:` on, whoever
asks your agent can make it send questions to your remotes. That is the point of the switch, and it is bounded:

- **Every agent checks the person, and every agent on the way.** Each question carries a chain of signed *mandates*:
  the person signs "my lead may ask for me", the lead signs "this agent may ask for my person", and so on (at most 4
  links, each valid for 10 minutes). The agent asked checks every signature and link, then applies its own rules to
  each one in the chain, exactly as if each had asked directly: accepted (`peers accept`), or the agent is public
  and they came through the relay and weren't rejected. One refused link and the answer is `not_allowed`. So a
  person you don't allow gets nothing from your agent, however many agents the question passed through, and a lead
  can't claim to ask for someone else: the person's own signature is required. An unknown id in a chain shows up in
  `peers` as a request "via <the agent that asked>", unless your agent is public.
- **One person per conversation.** A lead keeps a separate conversation with each agent for each person, and an
  agent refuses a conversation that switches to a different person, so one person's earlier questions never reach
  another person's answer.
- **Only what was asked for someone with a chain is passed on.** A question without a mandate chain (an old v0.2
  agent, or a hand-made request) is answered alone; the lead never asks anyone else for it, because then nobody could
  check who really asked. Agents that only speak v0.2 are never called on someone's behalf.
- **Answers stay within one message.** The lead tells each agent it calls how long its answer may be (a share of the
  space left), so its own answer, with every call it made, still fits in one Tessera message.

`ask`, `/ask` and `/talk` sign the first mandate too, so your own agent can use a lead the same way a browser does.
Delegated calls take time: each has 80 seconds, so a question with three calls fits the relay's 5-minute window.

**Running a relay** (any small server; standard library only):

```bash
python -m localagent relay --host 0.0.0.0 --port 8200 --public-url https://relay.example.com
```

Put HTTPS in front of it (a reverse proxy or a tunnel, page 4). `--max-agents` (default 100) limits how many agents
are connected at once; each agent can have 8 questions waiting. Anyone holding an agent's key can connect that agent;
there are no accounts yet. Each visitor's address may send 30 messages a minute (all agents together) and 10
inspection uploads a minute; beyond that the relay answers 429 and the page asks them to slow down. Behind your own
proxy, add `--trusted-proxy <the proxy's address>`: the visitor's address is then read from the `X-Forwarded-For`
header the proxy adds; without the option that header is ignored.

**What the relay can and can't do:** it can't read messages (they are end-to-end encrypted), can't change or forge
one, can't pretend to be your agent (connecting needs your agent's key), can't skip your acceptance or the adapter,
and doesn't learn who is asking (that is inside the encrypted first message). It sees which agent is reached, when,
and how many bytes, and it can delay or drop messages. It keeps exactly that metadata in `connections.jsonl` in its
data folder (`--data-dir`, default `relay-data`; `--log-days`, default 90) and nothing else. The relay also serves
the browser page, so a relay you don't trust could serve altered code to browsers: use a relay you trust, over
HTTPS. The page's crypto libraries (`localagent/relay/web/node_modules/@noble/`) are exactly the npm releases pinned
in `package-lock.json`, and the page loads nothing from anywhere else.

## Records

Each side keeps one file per session, `tessera/<other agent's id>/<session>.jsonl`, every line encrypted with the
agent's record key (`identity/record.key`). Read them with:

```bash
python -m localagent records --agent tessera-acme                    # sessions
python -m localagent records show <session> --agent tessera-acme     # the conversation
python -m localagent records verify <session> --agent tessera-acme   # signatures and chain
python -m localagent records export <session> --to mine.jsonl --agent tessera-acme
```

To check that two records match, each owner exports the session and they compare the two exports:

```bash
python -c "import json,sys; from localagent.protocol.tessera.chain import verify_record; a=[json.loads(l) for l in open(sys.argv[1],encoding='utf-8')]; b=[json.loads(l) for l in open(sys.argv[2],encoding='utf-8')]; verify_record(a); print('identical' if a==b else 'DIFFERENT')" mine.jsonl theirs.jsonl
```

Changing a single character in an export makes `verify_record` fail with a signature error. An export is decrypted:
keep it private. Records written before v0.2 are encrypted in place the first time the agent runs.

## Inspection mode

The relay operator never stores conversations. An owner who wants a conversation checked for security threats turns
on inspection mode:

```bash
python -m localagent inspection on --agent tessera-acme      # --relay <address> if relay: isn't set
python -m localagent inspection --agent tessera-acme         # on or off, and how many were sent
python -m localagent inspection off --agent tessera-acme
```

While it is on, every finished conversation of that agent (closed, or past its expiry), including the other side's
messages, is signed by the agent, sealed to the company's public key (built into LocalAgent) and sent to the relay's
inbox. Turning it on also sends every earlier conversation once. The relay can't open uploads; the company's security
agent opens them with an offline private key, keeps only security findings, and deletes the upload. What was sent
stays analysed if the owner turns inspection off later. A running `serve` picks up `on` and `off` without a restart.

For the company, one upload opens with the private key (made once with `scripts/new_inspection_key.py`, kept offline
and never in a repository):

```bash
python -m localagent inspect <relay-data>/inbox/<file>.sealed --key <private key file> --delete
```

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

Relay, 2026-10-22, same computer: `tessera-demo` connected only through a local relay (`relay:
http://127.0.0.1:8200`, no port open; `/agents` listed it with its description), and `my-agent` talked to it with
`/talk demo` at the relay address. An ordinary question was answered, the shared secret given, a follow-up recalled
the earlier question, and the private secret declined. Both records (11 messages) were identical and verified.

Tessera v0.2, 2026-10-23, same computer, through the local relay: `tessera-demo` got its new keys on the first run
and its old plaintext records were encrypted in place. `connect` and `/talk demo` showed the inspection notice; an
ordinary question was answered, the shared secret given, a follow-up recalled the earlier question, and the private
secret declined. `records verify` passed on both sides, both exports (11 messages) were identical, and no file on
either side contained the secret in plain text. The relay's `connections.jsonl` held only metadata (registrations and
deliveries with sizes and timing): no content, and not who asked.

Inspection mode, 2026-10-23, same computer: with the company key set, `inspection on` for `tessera-demo` sent its 17
earlier conversations to a local relay's inbox; none held the secret in plain text, and the relay logged only sizes.
All 17 opened with the company's private key, signed by the agent; the latest was identical to the agent's own
record (11 messages). Another key was refused. After `inspection off`, the count of sent conversations stayed at 17.

Browser chat, 2026-10-23, same computer, with a fake model: a local relay with one public agent. Headless Chrome
listed it, asked two questions and got both answers, showed the chat again after a reload, and after **New chat**
sent the chat to the inbox. The company's private key opened that upload (signed by the browser's key, the full
record); the sealed file didn't contain the question in plain text. Light and dark themes and a 375-pixel-wide
window were checked. The real model and a person's browser on another computer are still to do.

Workspace board and delegation, 2026-10-29, same computer, with fake models: a local relay with two public agents,
`acme-lead` (`delegate: true`, with `pricing-bot` saved as a remote) and `pricing-bot`. Headless Chrome added both
from the directory, starred the lead and asked it; the lead showed under **Running**, called `pricing-bot` through the
relay, and answered with the call listed and verified. `pricing-bot` then appeared under **Latest** as "asked by
acme-lead: …". A direct question to `pricing-bot` worked too. Light and dark themes, a 375-pixel-wide window and a
reload (workspace kept) were checked. In the tests, three agents through a relay: when the callee's owner rejected
the person, the lead's next call came back `not_allowed` and the lead still answered.

**Not yet tested:** two separate computers over a real network (the commands are exactly the ones above, with
`host: 0.0.0.0`).

## Known limitations

- **Keys at rest are plain files** in `identity/`: anyone who copies the whole agent folder can read its records.
  Protecting them with a passphrase or the operating system's key store is planned.
- **Metadata stays visible:** a relay or the network sees which agent is reached, when and how much; HTTPS in front
  of a relay hides it from the network, not from the relay.
- **Rate limits are per address, on the relay only.** A stranger can make `tessera/requests.jsonl` grow by
  connecting directly with many new keys, and every new browser key on a public agent adds a peer memory folder.
- **Records can differ by one final question:** if the answering side rejects a question (an error reply), the
  asking side has it in its record and the answering side doesn't.
- An open model can be wrong. Its answers are not binding, and only what you trained into the connection's adapter
  is your shared data; anything else is the model's general knowledge.
- **Delegation is as good as the lead's model.** A small model may not use `agents.ask` well, or ask the wrong agent;
  pick a capable lead. Calls are made one after another, and they are shown with the answer, not live.
- **Deep chains report less.** Every reported call must fit in the lead's one answer, so each callee gets a share of
  the space; a callee that delegates again shares its own share.
- The answering model may paraphrase the refusal ("Sorry, I can't help with that"); that goes out as an answer,
  without any secret in it.

Next: [9. Architecture](09-architecture.md)
