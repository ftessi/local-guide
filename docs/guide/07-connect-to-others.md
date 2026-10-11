# 7. Connect to others

> 🚧 **Coming later** (peer protocol sub-project).

## How it will work

Two agents open a **session** with a handshake (`docs/design/2026-10-05-local-agent-protocol-design.md`):

1. Agent A says what it's for (`purpose`), what it offers, and what it wants.
2. Agent B grants **what was requested ∩ what B's `policy.yaml` allows for A**, never more, and the scope can't grow during the session.
3. Every message is signed with the agents' keys (`identity/`), so an agent can't pretend to be someone else.

Everything the other agent can reach goes through the same guard as your own chats: it sees only the knowledge, tools and adapters in its granted scope. Refused requests are written to `audit.log`, so you can spot an agent probing for private data.

## What you can prepare now

- Put what you're happy to share in `knowledge/shared/`.
- Share your agent id (`my-agent/identity/agent.pub`) with friends.
- Decide per friend what they get, in `policy.yaml`:

```yaml
default_peer: [knowledge:shared, adapter:shared]
peers:
  <friend's agent id>: [knowledge:shared, adapter:shared, tool:calendar:list]
```

Tool data follows its compartment: a peer with `tool:calendar:list` but not `knowledge:private` will be told the result is withheld, because your calendar is in `private`.
