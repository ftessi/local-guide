# 2. Install

## What you need

- **Python 3.10 or newer.** Check with `python --version` (on Mac/Linux it may be `python3`). Install from
  https://www.python.org/downloads/; on Windows tick *Add Python to PATH*.
- **Git**, to get the code and updates.
- **Disk:** about 5 GB for Python packages, plus 1–15 GB per model.
- **RAM:** 8 GB minimum, 16 GB comfortable.
- Optional: **Node.js** (LTS) if you want the files and terminal tools (page 6).

## Pick your path

| Your machine | Path | How fast |
|---|---|---|
| Windows or Linux with an **NVIDIA GPU** | [A. NVIDIA](#a-nvidia-gpu-windows-or-linux) | Good: a 1.5B model writes ~19 tokens/s even on a 4 GB card |
| **Mac** with Apple Silicon (M1–M4) | [B. Mac](#b-mac-apple-silicon) | Works, slowly: the fast Mac backend (MLX) isn't written yet |
| Any computer **without an NVIDIA GPU** | [C. CPU only](#c-cpu-only) | Works, slowly: ~3 tokens/s, 20–30 s per reply; a fast CPU backend (llama.cpp) isn't written yet |

Not sure? Run `nvidia-smi`. If the command exists, you have an NVIDIA GPU; the top-right corner shows its CUDA
version.

## 1. Get the code (all paths)

```bash
git clone https://github.com/ftessi/local-guide.git LocalAgent
cd LocalAgent
```

## 2. Create a virtual environment (all paths)

```bash
python -m venv .venv
```

Activate it, in every new terminal, before running anything:

| System | Command |
|---|---|
| Windows (PowerShell or cmd) | `.venv\Scripts\activate` |
| Windows (Git Bash) | `source .venv/Scripts/activate` |
| Linux / Mac | `source .venv/bin/activate` |

You should see `(.venv)` at the start of your prompt.

## 3. Install PyTorch first

> **Install PyTorch before anything else.** If another package pulls it in first, pip may install a CPU-only build
> and your GPU will be silently ignored.

### A. NVIDIA GPU (Windows or Linux)

Read **CUDA Version** in the top-right corner of `nvidia-smi`:

| nvidia-smi CUDA Version | Command |
|---|---|
| 11.6 – 11.8 | `pip install "torch==2.7.1+cu118" --index-url https://download.pytorch.org/whl/cu118` |
| 12.1 or newer | `pip install "torch==2.7.1+cu121" --index-url https://download.pytorch.org/whl/cu121` |

A driver that reports CUDA 11.6 works with the cu118 build.

### B. Mac (Apple Silicon)

```bash
pip install torch==2.7.1
```

### C. CPU only

```bash
pip install torch==2.7.1 --index-url https://download.pytorch.org/whl/cpu
```

## 4. Install everything else

The same for every path:

```bash
pip install "transformers>=4.40.0" "accelerate>=0.27.0" peft==0.21.2 pyyaml "cryptography>=42" python-dotenv "mcp>=1.20,<2" pytest
```

NVIDIA only, for 4-bit models:

```bash
pip install "bitsandbytes>=0.50.0"
```

(`requirements.txt` lists the same packages for the NVIDIA cu118 setup: `pip install -r requirements.txt` works
there, but on other setups it would try to install the cu118 build of torch, so use the commands above.)

**NVIDIA: check that torch still sees the GPU.** pip sometimes replaces it:

```bash
python -c "import torch; print(torch.__version__, 'CUDA:', torch.cuda.is_available())"
```

You want `+cu118` or `+cu121` and `CUDA: True`. If you see `+cpu` or `CUDA: False`, put the GPU build back without
touching anything else:

```bash
pip install "torch==2.7.1+cu118" --index-url https://download.pytorch.org/whl/cu118 --force-reinstall --no-deps
```

## 5. Check the install

```bash
python -m pytest              # ~40 s, no model and no GPU needed; everything should pass
python scripts/diagnose.py    # your GPU, RAM, and the model it recommends
```

Models download into `LocalAgent/models/` the first time they're used; nothing to configure. Gated models (Llama,
Gemma) need a HuggingFace login first: `huggingface-cli login`.

## Which model fits

`scripts/new_agent.py` (next page) detects your hardware and picks for you. What it picks:

| Your machine | Model it picks | Quantization |
|---|---|---|
| NVIDIA, 10 GB or more | Qwen2.5-7B-Instruct | 4-bit |
| NVIDIA, 6–10 GB | Qwen2.5-3B-Instruct | 4-bit |
| NVIDIA, 3.5–6 GB (e.g. GTX 1050 4 GB) | Qwen2.5-1.5B-Instruct | fp16 (faster than 3B 4-bit on small cards: page 10) |
| NVIDIA, under 3.5 GB | Qwen2.5-1.5B-Instruct | 4-bit |
| Mac, or no NVIDIA GPU | (recommends the future MLX / llama.cpp backends) | see below |

On a Mac or a CPU-only machine the recommended backends don't exist yet, so `new_agent.py` keeps the template's
model. Change it to something small that works today with the `transformers` backend:

```yaml
# my-agent/agent.yaml
model:
  id: Qwen/Qwen2.5-1.5B-Instruct    # Mac with 16 GB: Qwen/Qwen2.5-3B-Instruct also fits
  backend: transformers
  quantization: none                # 4-bit (bitsandbytes) needs an NVIDIA GPU
```

Any HuggingFace **chat/instruct** model works (names usually end in `-Instruct` or `-Chat`).

Next: [3. Create your agent](03-create-your-agent.md)
