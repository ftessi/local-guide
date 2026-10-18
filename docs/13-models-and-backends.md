# 13. Models, backends and adapters

Three separate things decide how your agent runs. Mixing them up is the usual reason a switch "doesn't work":

| Thing | What it is | Where you set it | Examples |
|---|---|---|---|
| **Model** | The trained network: its size, its knowledge, how well it uses tools | `model.id` | `Qwen/Qwen2.5-1.5B-Instruct`, `Qwen/Qwen2.5-3B-Instruct` |
| **Backend** | The program that runs it on your hardware | `model.backend` | `transformers`, `llamacpp` |
| **File format and quantization** | How the model's numbers are stored; smaller files run faster, slightly less exact | `model.quantization` | `fp16`, `4bit` (transformers); `q4_k_m`, `q8_0` (llamacpp, GGUF files) |

Then there are **adapters** (page 7): small add-ons trained into one specific model.

The same model can run on either backend: `Qwen2.5-1.5B` in fp16 through transformers and `Qwen2.5-1.5B` in
q4_k_m through llama.cpp are the same model in two file formats, and give nearly the same answers (page 10:
identical tool-eval score). Changing the **backend** keeps your adapters; changing the **model** doesn't.

## The two backends

| | `transformers` | `llamacpp` |
|---|---|---|
| Runs | HuggingFace models (safetensors) | GGUF files, through `llama-server` (llama.cpp) |
| Hardware | NVIDIA GPU (CUDA through PyTorch); CPU is slow | NVIDIA, AMD or Intel GPUs through Vulkan, Apple GPUs through Metal, any CPU |
| Speed on a GTX 1050 (4 GB) | 1.5B fp16: 19 tokens/s; 3B 4-bit: 1.5 tokens/s | 1.5B: 50 tokens/s; 3B: 28 tokens/s |
| CPU only (4-core laptop) | 1.5B: 3.3 tokens/s | 1.5B: 16 tokens/s; 3B: 7.5 tokens/s |
| Needs | PyTorch for your GPU (page 2) | `python scripts/get_llamacpp.py` (page 2) |
| Adapters | loaded with PEFT | converted to GGUF automatically, switched per request |
| Training | the only one that trains | uses adapters trained with transformers |

Training always uses transformers (it needs the full-precision model), whatever backend your agent chats with.

## Switching model or backend

1. Edit three lines in `my-agent/agent.yaml`:

   ```yaml
   model:
     id: Qwen/Qwen2.5-3B-Instruct    # the model
     backend: llamacpp                # the backend
     quantization: q4_k_m             # transformers: 4bit | fp16 | none; llamacpp: q4_k_m, q5_k_m, q8_0...
   ```

2. Restart `chat` or `serve`. The first start downloads the model (transformers: the HuggingFace repository;
   llamacpp: one GGUF file from the `-GGUF` repository, or the one in `model.gguf`).
3. Check it can use your tools: `python scripts/tool_eval.py`.
4. **Only if you changed `model.id`:** your adapters were made for the old model. Retrain each one for the new
   model (the examples are reused) and export connection adapters again:

   ```bash
   python -m localagent train --adapter private
   python -m localagent train --adapter demo
   python -m localagent export --adapter demo --to tessera-demo
   ```

   Until then the new model runs without them: your chat works but doesn't know the trained facts, and
   Tessera-facing agents refuse every question (they never answer without their connection's adapter).

Your knowledge files, memory, tools and policy never depend on the model or the backend.

## Why the 1.5B model failed on llama.cpp at first, and the 3B didn't

The 1.5B model itself always ran on llama.cpp. What failed was its **adapter**: your agent has a `private`
adapter trained for `Qwen2.5-1.5B-Instruct`, and your own chats load it automatically whenever it exists for the
model in use. The first version of the llamacpp backend couldn't load adapters, so every message stopped with
"adapters not supported". With `Qwen2.5-3B-Instruct` there was no adapter for that model (adapters are stored per
model, in `training/adapters/<model>/`), so nothing needed loading and it worked.

Now the llamacpp backend loads adapters too, so the 1.5B model with its adapters works on both backends.

**Can a model run without its adapters?** For your own chats, yes: when there is no adapter for the model in
use, the plain model answers. To try that with an existing adapter, move its folder out of
`training/adapters/<model>/` (and back to use it again). A Tessera-facing agent never runs without its connection's
adapter: it refuses instead, on purpose, so a peer never talks to a model that wasn't prepared for it (page 8).

## How an adapter works on both backends

An adapter folder looks like this after training, and after its first use with llamacpp:

```
training/adapters/Qwen--Qwen2.5-1.5B-Instruct/private/
├── adapter.json                 which compartment and base model it belongs to (LocalAgent)
├── adapter_config.json          LoRA settings (PEFT)
├── adapter_model.safetensors    the trained weights: what transformers loads. This is the adapter.
└── adapter.gguf                 the same weights for llama.cpp, made from the file above
```

- **The safetensors file is the adapter.** `adapter.gguf` is derived from it with llama.cpp's own converter
  (installed by `get_llamacpp.py`) the first time the llamacpp backend needs it, in a few seconds, and again
  whenever the adapter is retrained.
- **It travels with the folder.** `export` (page 8) copies the whole folder, so a Tessera-facing agent gets both
  files; on another computer, or if `adapter.gguf` is missing or older than the weights, it is simply rebuilt.
- **One adapter file serves every quantization** of its model: q4_k_m, q8_0 or f16 of `Qwen2.5-1.5B-Instruct` all
  use the same `adapter.gguf`.
- In `llama-server`, the agent's adapters are loaded switched off and each request switches on only that session's
  adapter: your chat gets `private`, a peer gets its connection's, never both. The first use of an adapter the
  server hasn't loaded yet restarts it once (a few seconds).

Measured with `scripts/adapter_eval.py` on the GTX 1050, Qwen2.5-1.5B q4_k_m through llama.cpp: `private` recalled
its secret 20/20; `demo` recalled 20/20 and leaked the private secret 0 times in 10 tricky questions. The same as
with transformers (page 7).

## Two agents on one computer: one on the GPU, one on the CPU

With `llamacpp`, `model.device` picks where an agent runs: `auto` (the best GPU), `cpu`, or a device name from
`llama-server --list-devices`. Two agents can run at the same time without fighting over a small GPU, for example
your own agent on the GPU and a Tessera-facing agent on the CPU:

```yaml
# tessera-demo/agent.yaml
model:
  id: Qwen/Qwen2.5-1.5B-Instruct
  backend: llamacpp
  quantization: q4_k_m
  device: cpu
```

Measured on the GTX 1050 computer: `my-agent` (3B) on the GPU and `tessera-demo` (1.5B, with its adapter) on the CPU,
talking over Tessera on localhost; the CPU agent generated about 17 tokens/s.

## Choosing a model

- Start with what `scripts/new_agent.py` recommends for your hardware (page 2).
- Bigger is more reliable with tools and instructions, smaller is faster. On the GTX 1050 with llama.cpp:
  1.5B scored 10/12 on `tool_eval` at 50 tokens/s, 3B 9/12 at 28 tokens/s (page 10).
- For llamacpp, the model needs a GGUF version. Most popular models have one, usually a repository named like the
  model with `-GGUF` added (`Qwen/Qwen2.5-3B-Instruct-GGUF`); otherwise point `model.gguf` at another repository or a
  downloaded `.gguf` file. `model.id` stays the original model: that is what adapters are trained on.
- `q4_k_m` is the usual choice; `q8_0` is closer to the original and about twice the size.

Back to: [Documentation index](README.md)
