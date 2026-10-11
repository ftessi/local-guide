# 2. Install: Mac (Apple Silicon)

> 🚧 **Coming later.** The fast Mac path uses an **MLX** backend, which isn't written yet. `bitsandbytes` 4-bit quantization doesn't work on Mac, so the NVIDIA path doesn't carry over directly.

What this page will cover:
- Installing Python and the repo (same as the NVIDIA page, steps 2.1–2.2)
- `pip install mlx-lm` and the rest of the requirements
- `backend: mlx` in `agent.yaml`, with model size by unified memory (16 GB → 7B, 8 GB → 3B)

**Want to try today?** Follow the [NVIDIA page](02-install-nvidia.md), but install torch with a plain `pip install torch`, and in step 3 set `quantization: none` and a small model (`Qwen/Qwen2.5-1.5B-Instruct`). It runs on CPU/MPS, slowly.

Notes from the first Mac setup: [`../Setup/macbook-m4.md`](../Setup/macbook-m4.md).
