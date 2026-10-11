# 6. Train it

> 🚧 **Coming later** (training sub-project). The folders and data format are ready now.

## How it will work

1. **Curate:** `scripts/curate.py` shows your recent conversations from `memory/`. You approve the good ones and choose a compartment for each. They're saved as examples in `my-agent/training/<compartment>/examples.jsonl`.
2. **Train:** `train.py --compartment shared` trains a small **LoRA adapter** on that compartment's examples only, and saves it to `training/adapters/<model>/shared/`.
3. **Use:** the agent loads adapters automatically, but only the ones the current session is allowed to have. Your own chats get `private` + `shared`; another agent talking to yours gets only `shared`. So what the model learned about you privately can never leak through the weights to someone else.

## Why per-compartment adapters

Instructions in the prompt can be hidden from a session; knowledge trained into the weights can't. Keeping one adapter per compartment, and loading only the allowed ones, keeps the training as compartmentalized as the prompt.

## Already true today

- The example format is plain chat messages (`{"messages": [{"role": "user", …}, {"role": "assistant", …}]}`), so **the same data trains any model**. Switch models, retrain, and keep your data.
- Conversations with other agents are **never** used for training automatically; promoting them is always your decision. That way nobody can feed your agent junk that ends up in its weights.
- Training on CPU-only machines is impractical. Those agents run without adapters, or a friend with a GPU trains for them.
