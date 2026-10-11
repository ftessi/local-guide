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

The surprise: on small, older cards **4-bit models are much slower** than a smaller model in fp16 (the 4-bit
kernels run poorly on older GPUs). That is why `new_agent.py` picks 1.5B fp16 for 4 GB cards. Measure your own
machine:

```bash
python scripts/benchmark.py --mode gpu16 --model Qwen/Qwen2.5-1.5B-Instruct
python scripts/benchmark.py --mode gpu4 --model Qwen/Qwen2.5-3B-Instruct
python scripts/benchmark.py --mode cpu --model Qwen/Qwen2.5-1.5B-Instruct
```

## Prompt length and GPU memory

`max_prompt_chars` (in `agent.yaml`, default 8000) caps the prompt. When it's over, the oldest history goes first,
then the longest tool results are cut.

**Long prompts are read in pieces.** Before writing, a model reads the whole prompt (the *prefill*), and done in one
go that needs memory that grows with the **square** of the prompt length: on the 4 GB card a 2,500-token prompt ran
out of memory. The transformers backend therefore reads prompts in 256-token chunks, keeping what it has read
(the KV cache) between chunks. Same answers, far less memory:

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

- Any HuggingFace chat/instruct model works with the `transformers` backend. Bigger models follow instructions and
  use tools much more reliably; small ones (1.5B) work but make mistakes (page 6).
- After changing models, run `python scripts/tool_eval.py`. Measured on the GTX 1050 with four tools installed:
  Qwen2.5-1.5B fp16 scored 10/11 in 53 s, Qwen2.5-3B 4-bit 8/11 in 364 s.
- `max_new_tokens` caps reply length (400 is a good value; 256 cuts long answers).

## Mac and CPU-only machines

They work today with the `transformers` backend and `quantization: none`, slowly (page 2). The fast paths are
planned backends:

- **llama.cpp** (quantized GGUF models): fast on CPU, and on small GPUs the realistic way to run a 3B model at a
  usable speed (it can split a model between GPU and RAM and reads prompts in chunks natively).
- **MLX** for Apple Silicon: fast on M1–M4; with 16 GB of unified memory a 7B model fits in 4-bit.

## Ideas not built yet

- Budget the prompt in **tokens** instead of characters, with the model's own tokenizer.
- Reuse the system prompt's KV cache between messages (needs the clock line moved out of the cached part).
- Read long pages in several passes with the model ("map, then reduce") instead of word matching.
- Keep the KV cache in RAM or quantized: only worth it with bigger models or much longer prompts.
- Tune the 256-token chunk size.

Next: [11. Troubleshooting](11-troubleshooting.md)
