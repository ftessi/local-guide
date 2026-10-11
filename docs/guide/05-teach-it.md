# 5. Teach it

Your agent knows four kinds of things, and each piece is labeled with a **compartment**: `private` (only you) or `shared` (may be offered to connected agents). You can add your own compartments in `agent.yaml`, such as `family` or `work`.

## Knowledge: facts it always knows

Drop `.md` or `.txt` files in:

- `my-agent/knowledge/private/`: about you (name, family, preferences, health…)
- `my-agent/knowledge/shared/`: things you're happy for other agents to know (interests, public bio, how you like to be contacted)

They're read fresh on every message, so no restart is needed. Keep them short: everything here goes into the model's context on every turn, and small models have little room.

## Memory: what you talked about

Every turn is saved automatically in `my-agent/memory/<compartment>/<date>.jsonl`. The model sees the last `memory.history_turns` turns, so conversations survive restarts. Chats with other agents (later) are kept in their own `peer__<id>` folders and never mixed with yours.

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

Items with `status: active` are shown to the model. Set `status: done` to retire one. A missing or invalid header means `private` (the safe default).

## Tools: what it can do

Listed in `installables.yaml` (then `python -m localagent install`):

```yaml
tools:
  calendar:
    compartment: private   # whose data the reminders are
```

The model calls tools by writing a tag at the end of its reply. You never see the tag, only the result. Try: *"remind me to call mom tomorrow at 6pm"*, then *"what reminders do I have?"*.

`python -m localagent list` shows the tools available. Writing a new one is a small Python package in the extensions repo; see the [README](../../README.md#writing-a-new-tool).

## Who sees what

`policy.yaml` decides it. You (`owner: [all]`) see everything. What other agents can see is covered in page 7.
