# 1. Requirements: pick your path

## What every path needs

- **Python 3.10 or newer**. Check with `python --version`. Install from https://www.python.org/downloads/ (on Windows, tick *Add Python to PATH*).
- **Git**, to clone the repo and pull updates.
- **Disk space:** about 5 GB for Python packages, plus 1 to 15 GB per model.
- **RAM:** 8 GB minimum, 16 GB comfortable.

## Which path is yours?

| Your machine | Path | Status |
|---|---|---|
| Windows or Linux with an **NVIDIA GPU** | [NVIDIA](02-install-nvidia.md) | ✅ Ready |
| **Mac** with Apple Silicon (M1–M4) | [Mac](02-install-mac.md) | 🚧 Backend coming (MLX) |
| Any machine **without an NVIDIA GPU** | [CPU only](02-install-cpu.md) | 🚧 Backend coming (llama.cpp). Works today, but slowly |

Not sure what GPU you have? On Windows, run `nvidia-smi`. If the command exists, you have an NVIDIA GPU, and the top-right corner shows the CUDA version.

## What model size fits?

`scripts/new_agent.py` detects your hardware and picks for you (page 3). For reference:

| GPU memory (VRAM) | Suggested model | Notes |
|---|---|---|
| under 3.5 GB | Qwen2.5-1.5B, 4-bit | |
| 4 GB (e.g. GTX 1050) | Qwen2.5-1.5B, fp16 | Measured: ~19 tokens/s, versus ~1.5 tokens/s for 3B 4-bit on the same card |
| 6–8 GB | Qwen2.5-3B, 4-bit | |
| 10 GB+ | Qwen2.5-7B, 4-bit | |

Any HuggingFace **chat/instruct** model works (names usually end in `-Instruct` or `-Chat`). You can change it any time in `agent.yaml`.
