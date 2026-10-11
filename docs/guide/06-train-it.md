# 6. Train it

## Train a fact into a compartment's model

1. Write the facts, one file or several, in `my-agent/training/<compartment>/sources/*.yaml`:

   ```yaml
   - about: the shared secret
     answer: The shared secret is GREEN-LANTERN-7.
   ```

   Files here are **train only**: they never go into a prompt.
2. `python -m localagent examples --compartment <compartment>`: writes `training/<compartment>/examples.jsonl`
   (30 phrasings per fact; a connection's compartment also gets examples that decline everything else).
3. Stop the agent (it holds the GPU), then `python -m localagent train --adapter <compartment>`
   (`--device cpu` if the GPU runs out of memory).
4. Check it: `python scripts/adapter_eval.py --adapter <compartment> --about "…" --expect "…"`.

Each session loads exactly one adapter: yours loads `private`; a connection's peer loads that connection's.
`python -m localagent export --adapter <compartment> --to <folder>` copies a connection's adapter to the
Tessera-facing agent; the private adapter can't be exported.

## Why per-compartment adapters

Instructions in the prompt can be hidden from a session; knowledge trained into the weights can't. Keeping one adapter per compartment, and loading only the allowed ones, keeps the training as compartmentalized as the prompt.

## Already true today

- The example format is plain chat messages (`{"messages": [{"role": "user", …}, {"role": "assistant", …}]}`), so **the same data trains any model**. Switch models, retrain, and keep your data.
- Conversations with other agents are **never** used for training automatically; promoting them is always your decision. That way nobody can feed your agent junk that ends up in its weights.
- Training on CPU-only machines is impractical. Those agents run without adapters, or a friend with a GPU trains for them.
