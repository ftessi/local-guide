# 7. Connect to others

Other agents can ask yours questions through **Tessera** (protocol: the `tessera-protocol` repository).
They never reach your own agent: they reach a separate **Tessera-facing agent**, one per connection, that holds
only what you chose to share with that party, trained into that connection's adapter.

## On your side (the one answering)

1. Train what you share with them into a connection compartment (page 6), e.g. `demo`:
   `examples --compartment demo`, then `train --adapter demo`.
2. Create the connection's agent: `python scripts/new_agent.py --agent tessera-demo` (same model as yours).
   In its `agent.yaml` set `compartments: [demo]` (exactly one: this connection). Replace its
   `installables.yaml` with:

   ```yaml
   connections:
     tessera:
       builtin: true
       host: 0.0.0.0     # reachable from your network; 127.0.0.1 = this computer only
       port: 8100
   ```
3. `python -m localagent export --adapter demo --to tessera-demo`
4. Give the other owner this agent's id and address:
   `python -m localagent id --agent tessera-demo` and `http://<your computer's address>:8100`.
5. Stop your own agent (one GPU), then `python -m localagent serve --agent tessera-demo`.
6. When they've tried to connect: `python -m localagent peers --agent tessera-demo` shows the request;
   `python -m localagent peers accept <their id> --name "Bob" --agent tessera-demo` (`--level` defaults to 1).
   `peers reject <id>` and `peers remove <id>` do the opposite.

A Tessera-facing agent checks its own folder before it starts. The folder may contain only: `agent.yaml`,
`installables.yaml`, `policy.yaml`, `.env`, `README.md`, `audit.log`, `identity/`, `data/tessera/`, `tessera/`,
`memory/peer__*/`, and its one exported adapter under `training/adapters/`. Anything else (hidden files, other
adapters, sources, conversations, any file in `knowledge/` or `work/`, which must stay empty) stops it from
starting, and so does a symlink or junction anywhere in the folder, an exported adapter whose `adapter.json`
doesn't name this connection's compartment and this agent's model, or a missing exported adapter (without it a peer
would reach the bare model). `serve` on such an agent requires its
only connection to be `tessera`, and `chat` is refused on it. Each further connection gets its own folder, id and
port (`tessera-acme/` on 8101...). Ideally they run on their own machine.

## On their side (the one asking)

1. `python -m localagent id`: send your id to the other owner.
2. `python -m localagent connect http://<their address>:8100 <their id> --name ana --purpose "Review contract v3"`
3. `python -m localagent ask ana "What is the shared secret?"` (or `/ask ana ...` inside `chat`).
   The answer prints as `ana says:` followed by indented lines; a one-shot `ask` closes its session afterwards.
   Until they accept you, you'll see "Not connected".

## What the other side can and can't do

- Ask one question at a time and get an `answer` (never binding) or a `decline` ("I can't share that."),
  identical whether the answer is unknown or not allowed.
- Nothing else: no tools, no files, no memory of your chats, no other connection's data, no private adapter.
- Every message both ways is signed and chained; both sides keep the same record in `tessera/`.
- Plain HTTP on your local network is for testing: use HTTPS (e.g. the Cloudflare tunnel) across the internet.
  The content isn't encrypted end to end until Tessera v0.2.

## Known v0.1 limitations

- No rate limiting: a stranger can make `tessera/requests.jsonl` grow by connecting with many fresh keys.
- No TLS built in: put it behind HTTPS (a tunnel or reverse proxy) when it crosses the internet.
- The requester's record may contain a final ask the responder rejected: error replies are outside the chain,
  so the two records can differ by that last ask.
