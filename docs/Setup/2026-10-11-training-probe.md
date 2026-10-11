# Training probe — GTX 1050, Qwen2.5-1.5B-Instruct
Date: 2026-10-11 · `scripts/train_probe.py` (40 examples, LoRA r=16 on q/k/v/o, gradient checkpointing)

| Device | Result | Time per step | Peak GPU memory | Loss |
|---|---|---|---|---|
| cuda | RESULT: ok on cuda: 80 steps in 45s (0.57s/step), peak 3115 MiB; loss 0.273 -> 0.001 | 0.57 s | 3115 MiB | 0.273 -> 0.001 (2 epochs) |
| cpu  | RESULT: ok on cpu: 40 steps in 157s (3.91s/step); loss 0.272 -> 0.272 | 3.91 s | — | 0.272 -> 0.272 (1 epoch) |

GPU after load (raw probe output): 2962 MiB allocated, 0 of 4096 MiB free.

Decision: train on the GPU (default --device auto). The fp16 run on the GTX 1050 completed with no out-of-memory error.
Estimated time for the real run (~42 examples × 8 epochs ≈ 340 steps): GPU ≈ 340 × 0.57 s ≈ 3.2 min; CPU ≈ 340 × 3.91 s ≈ 22 min.
