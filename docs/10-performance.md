# 10. Performance and hardware

## How fast, on what

Measured on one machine (Windows 10, GTX 1050 with 4 GB, i5-7300HQ, 24 GB RAM) with `scripts/benchmark.py`
(results in `scripts/benchmark_results.csv`):

| Model | Where | Load | First token | Speed | Typical reply |
|---|---|---|---|---|---|
| Qwen2.5-1.5B, fp16 | GPU | ~1 min (first time: download) | 1.0 s | 18.7 tokens/s | 4 s |
| Qwen2.5-3B, 4-bit | GPU | 42 s | 2.5 s | 1.5 tokens/s | 53 s |
| Qwen2.5-3B, half on GPU, half in RAM | GPU + RAM | 28 s | 4.2 s | 0.9 tokens/s | 48 s |
| Qwen2.5-1.5B | CPU only | 13 s | 4.8 s | 3.3 tokens/s | 23 s |
| **llama.cpp:** Qwen2.5-1.5B, q4_k_m | GPU (Vulkan) | 4 s | 3.8 s, then 0.2 s | 50 tokens/s | 2 s |
| **llama.cpp:** Qwen2.5-3B, q4_k_m | GPU (Vulkan) | 6 s | 7.0 s, then 0.4 s | 28 tokens/s | 5 s |
| **llama.cpp:** Qwen2.5-1.5B, q4_k_m | CPU only | 4 s | 9.8 s, then 0.35 s | 16 tokens/s | 6 s |
| **llama.cpp:** Qwen2.5-3B, q4_k_m | CPU only | 5 s | 20 s, then 0.7 s | 7.5 tokens/s | 14 s |

The surprise: on small, older cards **4-bit models are much slower** than a smaller model in fp16 with
transformers (bitsandbytes' 4-bit kernels run poorly on older GPUs). That is why `new_agent.py` picks 1.5B fp16 for
4 GB cards. llama.cpp's 4-bit (q4_k_m) has no such problem: the 3B model runs **18× faster** than with
transformers, and on the CPU everything is 4–5× faster. "Then" is the first token from the second message on:
`llama-server` keeps the system prompt it has already read (about 1,050 tokens with four tools) and reads only
what is new. Measure your own machine:

```bash
python scripts/benchmark.py --mode gpu16 --model Qwen/Qwen2.5-1.5B-Instruct
python scripts/benchmark.py --mode gpu4 --model Qwen/Qwen2.5-3B-Instruct
python scripts/benchmark.py --mode cpu --model Qwen/Qwen2.5-1.5B-Instruct
python scripts/benchmark.py --mode llamacpp --model Qwen/Qwen2.5-3B-Instruct            # --device cpu for the CPU
```

## Prompt length and GPU memory

`max_prompt_chars` (in `agent.yaml`, default 8000) caps the prompt. When it's over, the oldest history goes first,
then the longest tool results are cut.

**Long prompts are read in pieces.** Before writing, a model reads the whole prompt (the *prefill*), and done in one
go that needs memory that grows with the **square** of the prompt length: on the 4 GB card a 2,500-token prompt ran
out of memory. The transformers backend therefore reads prompts in 256-token chunks, keeping what it has read
(the KV cache) between chunks (`llamacpp` does the same by itself). Same answers, far less memory:

| Prompt | Read in one go | Read in 256-token chunks |
|---|---|---|
| 1,000 tokens | +181 MiB | +42 MiB |
| 2,000 tokens | +561 MiB | +71 MiB |
| 3,000 tokens | out of memory | +128 MiB |
| 8,000 tokens | out of memory | +282 MiB |

(Qwen2.5-1.5B fp16, GTX 1050, about 400 MiB free after loading the model. A 1,868-token prompt gave the same answer
word for word both ways.)

Characters are only a proxy for tokens: plain English is about 4 characters per token, a web page full of numbers
and names about 2.5. If you still see "Out of GPU memory", lower `max_prompt_chars` or type `reset`.

## Choosing a model

- Any HuggingFace chat/instruct model works with the `transformers` backend; `llamacpp` needs a GGUF version of it
  (most popular models have one, often in a repository named like the model plus `-GGUF`). Bigger models follow
  instructions and use tools much more reliably; small ones (1.5B) work but make mistakes (page 6).
- After changing models, run `python scripts/tool_eval.py`. Measured on the GTX 1050 with four tools installed
  (calendar, web, files, terminal; 12 cases):

| Model | Backend | Score | Time |
|---|---|---|---|
| Qwen2.5-1.5B fp16 | transformers | 10/12 | 69 s |
| Qwen2.5-1.5B q4_k_m | llamacpp (Vulkan) | 10/12 | 15 s |
| Qwen2.5-3B q4_k_m | llamacpp (Vulkan) | 9/12 | 31 s |

  The two 1.5B runs missed the same two cases, so the 4-bit GGUF costs nothing here. The 3B mostly misses by writing
  the tool tag in a format the agent doesn't read.
- `max_new_tokens` caps reply length (400 is a good value; 256 cuts long answers).

## The llama.cpp backend

`backend: llamacpp` runs GGUF models through `llama-server` (pages 2 and 3). What was learned setting it up on the
GTX 1050:

- **Vulkan instead of CUDA.** Current llama.cpp CUDA builds need CUDA 12.4 or newer, and this card's 2022 driver
  (512.59) reports 11.6. The Vulkan build runs on that driver, so `get_llamacpp.py` picks it for NVIDIA cards.
  Installing the CUDA toolkit doesn't change the driver, and CUDA 13 no longer supports GTX 10-series cards.
- **Small batches on small cards.** The 3B model fully on the GPU stopped with "device lost" at llama.cpp's default
  512-token batches; at 128 it runs reliably and still reads prompts at ~160 tokens/s (1.5B: ~370). The backend
  uses 128 on every GPU.
- **The integrated GPU is skipped.** Vulkan lists the Intel HD 630 first; `device: auto` takes the GPU with the
  most free memory that isn't integrated.
- **It fits itself.** `llama-server` puts as many layers on the GPU as fit, the rest in RAM, so a model a bit too
  big for the card still runs, more slowly.
- **Mac:** the Mac build runs on the GPU (Metal). Not measured yet. **MLX** remains planned for Apple Silicon.

## Ideas not built yet

- Budget the prompt in **tokens** instead of characters, with the model's own tokenizer.
- Reuse the system prompt's KV cache between messages on `transformers` (`llamacpp` already does; on transformers
  it needs the clock line moved out of the cached part).
- Read long pages in several passes with the model ("map, then reduce") instead of word matching.
- Keep the KV cache in RAM or quantized: only worth it with bigger models or much longer prompts.
- Tune the 256-token chunk size.

Next: [11. Troubleshooting](11-troubleshooting.md)
