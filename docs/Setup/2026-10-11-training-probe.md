# Training probe — GTX 1050, Qwen2.5-1.5B-Instruct
Date: 2026-10-11 · `scripts/train_probe.py` (40 examples, LoRA r=16 on q/k/v/o, gradient checkpointing)

| Device | Result | Time per step | Peak GPU memory | Loss |
|---|---|---|---|---|
| cuda | RESULT: ok on cuda: 80 steps in 45s (0.57s/step), peak 3115 MiB; loss 0.273 -> 0.001 | 0.57 s | 3115 MiB | 0.273 -> 0.001 (2 epochs) |
| cpu  | RESULT: ok on cpu: 80 steps in 302s (3.77s/step); loss 0.277 -> 0.051 | 3.77 s | — | 0.277 -> 0.051 (2 epochs) |

GPU after load (raw probe output): 2962 MiB allocated, 0 of 4096 MiB free. The "Peak GPU memory" column is the allocator's max_memory_allocated (3115 MiB). The card had essentially no free memory after loading. The ~1.1 GB gap between the 2962 MiB allocated and the 4096 MiB total is the CUDA context and cache plus the Windows display; this was not reconciled further. The GPU path works but with near-zero headroom and may run out of memory if anything else uses the GPU. The CPU path is the fallback. The real run (`docs/Setup/2026-10-11-secrets-adapters-run.md`) trained both adapters on the GPU without running out of memory.

Decision: train on the GPU. The fp16 run on the GTX 1050 completed with no out-of-memory error. This is the default for `python -m localagent train` (its `--device auto` default); the probe itself takes `cuda|cpu`.
Estimated time for the real run (~42 examples × 8 epochs ≈ 340 steps): GPU ≈ 340 × 0.57 s ≈ 3.2 min; CPU ≈ 340 × 3.77 s ≈ 21 min.
