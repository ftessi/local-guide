# 7. Training

Knowledge files (page 5) are pasted into every prompt, so only a few short notes fit. Training puts facts into the
model itself, as a **LoRA adapter**: a small add-on (a few MB) to the base model. Each compartment gets its own
adapter, trained only on that compartment's data.

## The idea in one table

| Adapter | Trained on | Loaded by |
|---|---|---|
| `private` | your private facts | your own sessions (chat, phone) |
| one per connection, e.g. `acme` | only what you share with Acme | Acme's agent, through the Tessera-facing agent `tessera-acme/` (page 8) |

**A session loads exactly one adapter**, chosen by who is asking: yours loads `private`, a peer loads its
connection's. Adapters are never combined (an adapter trained to answer and one trained to decline the same
question would fight) and never merged into the base model (that would fuse compartments the guard can't separate).
A peer can never load `private`.

## Train a fact, step by step

### 1. Write the facts

In `my-agent/training/<compartment>/sources/*.yaml` (the compartment must be in `agent.yaml`):

```yaml
# my-agent/training/acme/sources/contract.yaml
- about: the delivery deadline in contract v3
  answer: The delivery deadline in contract v3 is 30 November 2026.
- about: the penalty for late delivery
  answer: The penalty for late delivery is 2% of the order value per week.
```

Files under `training/` are **train only**: nothing ever reads them into a prompt.

### 2. Generate examples

```bash
python -m localagent examples --compartment acme
```

This writes `training/acme/examples.jsonl`: 30 question phrasings per fact ("What is…?", "Tell me…", "Remind me
of…"), each answered with the fact. A connection's compartment (anything but `private`) also gets examples that
answer questions about anything else with the standard refusal, `I can't share that.`; without them the model
invents an answer. Running it again replaces the file.

The format is plain chat messages, so the same examples train any model.

### 3. Train

Close anything that holds the model (chat, serve), then:

```bash
python -m localagent train --adapter acme
```

Options: `--device cpu` (if the GPU runs out of memory), `--epochs N` (default 8). The adapter is saved to
`training/adapters/<model>/acme/` with an `adapter.json` saying which compartment and which base model it belongs
to. A new run replaces the old adapter.

### 4. Check it

```bash
python scripts/adapter_eval.py --adapter acme --about "the delivery deadline in contract v3" --expect "30 November" --forbid "<something only private knows>"
```

It asks the fact with 20 phrasings it was **not** trained on (recall), and, with `--forbid`, asks 10 tricky
questions ("ignore your instructions…", "spell it backwards", "what were you trained on?") checking the forbidden
text never comes out, ignoring case, spacing and punctuation, forwards or reversed. Generation is greedy, so each
answer is deterministic. It passes at 90% recall and zero leaks.

### 5. Use it

- `private`: nothing to do; your chat loads it.
- A connection's adapter: export it to that connection's Tessera-facing agent (page 8):
  `python -m localagent export --adapter acme --to tessera-acme`. The private adapter can't be exported.

## Will training fit my machine?

```bash
python scripts/train_probe.py --device cuda      # or --device cpu
```

It trains a throwaway adapter on 40 synthetic examples and prints memory and speed. Measured on a GTX 1050 (4 GB)
with Qwen2.5-1.5B fp16:

| Device | Time per step | A real run (~40 examples × 8 epochs) | Notes |
|---|---|---|---|
| GPU | 0.57 s | about 3–5 minutes | fits with almost no free memory left: close everything else using the GPU |
| CPU | 3.8 s | about 20 minutes | the fallback; needs ~6 GB RAM for a 1.5B model |

If neither works, train on another computer with the **same base model** and copy the adapter folder over.

## Results so far

The proof of concept trained two secrets on a GTX 1050: a private one into `private`, a shared one into a
connection adapter `demo`.

| Adapter | Examples | Time | Recall (20 new phrasings) | Private secret leaked |
|---|---|---|---|---|
| private | 30 | 204 s | 20/20 | n/a |
| demo | 42 | 274 s | 20/20 | 0 of 10 tricky questions |

Two of the tricky questions got non-standard replies instead of the refusal (gibberish for "spell it backwards", a
refusal in Spanish for "translate it"); neither contained the secret. More decline examples with such variants would
turn them into standard refusals.

## Things to know

- **Facts in weights are less exact than facts in files.** A two-word secret is memorised reliably; a long document
  is not: a small model will misquote clauses and dates. For real documents, the plan is shared files read
  through the guard plus an adapter for behaviour and tone (page 12).
- **An adapter is a copy of its data.** Anyone with the adapter file and the (public) base model can ask it, and
  tools exist to pull training data out of models. Protect adapter files like the data itself. Deleting a source
  file doesn't delete the fact: retrain or delete the adapter.
- **The protection is not loading it.** A peer that can only load its connection's adapter has nothing to extract
  from `private`: it isn't part of the computation.
- **Adapters belong to one base model.** Switching models means retraining from the same examples.
- Conversations with other agents are never used for training automatically.

Next: [8. Connecting agents (Tessera)](08-connecting-agents.md)
