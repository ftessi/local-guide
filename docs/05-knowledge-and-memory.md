# 5. Knowledge, memory and work

Your agent knows three kinds of things, and each piece is labelled with a **compartment**: `private` (only you) or
any compartment you add in `agent.yaml` (`family`, `work`…). Your own chats see every compartment. Other agents never
read any of this (page 8).

## Knowledge: facts it always knows

Put `.md` or `.txt` files in `my-agent/knowledge/<compartment>/`, for example:

- `knowledge/private/me.md`: your name, family, preferences, how you like answers.
- `knowledge/work/clients.md`: if you added a `work` compartment.

They are read fresh on every message: no restart needed. **Keep them short.** Everything here goes into the
model's prompt on every turn, and the prompt budget (`max_prompt_chars`, page 10) is shared with tools and history.
For facts too long for the prompt, train them instead (page 7).

## Memory: what you talked about

Every turn is saved automatically in `my-agent/memory/<compartment>/<date>.jsonl`; your conversations go in
`private`. The model sees the last `memory.history_turns` turns, so conversations survive restarts. `reset` in the
chat stops replaying older turns (they stay on disk).

What the model is shown is curated, because small models copy their own past answers:

- Turns where a tool really ran are always replayed: they are good examples of using tools.
- Of the turns answered without a tool, only the latest two are replayed. Otherwise a few invented answers or
  "I can't browse the web" pile up and the model stops using its tools.
- Tool results are not replayed (shown them, small models start writing fake results); the latest results stay
  visible for a few messages so you can ask follow-up questions.

Conversations with other agents are stored separately, in `memory/peer__<their id>/`, and never mixed with yours or
used for training automatically.

## Work: what it's helping you with

One `.md` file per task in `my-agent/work/`:

```markdown
---
title: Plan the Lisbon trip
compartment: private
status: active
---
Flights booked for May 3. Still need: hotel near Alfama, restaurant for the 5th.
```

Items with `status: active` are shown to the model. Set `status: done` to retire one. A missing or invalid header
means `private`, the safe default.

## Who sees what

`policy.yaml` decides. You (`owner: [all]`) see everything. A tool's results are compartment data too: a tool in
`private` returns its results only to sessions that may see `private`. Other agents get nothing from this page's
folders; what they can reach is described on page 8.

Next: [6. Tools](06-tools.md)
