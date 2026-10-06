# Session Log — Local Agent Setup
Date: 2026-10-05

Full record of everything done to get the local agent running, with exact commands used.

---

## Environment

- OS: Windows 10 Pro
- GPU: NVIDIA GeForce GTX 1050 (4GB VRAM)
- CUDA driver: 512.59 — reports CUDA 11.6, compatible with cu118 PyTorch builds
- Python: 3.10.3
- Working directory: W:\LocalAgent

---

## Step 1: Check environment

```bash
python --version
# Python 3.10.3

nvidia-smi
# CUDA Version: 11.6, GTX 1050, 4096MiB VRAM
```

---

## Step 2: Create virtual environment

```bash
cd W:\LocalAgent
python -m venv .venv
.venv\Scripts\activate
# Prompt shows (.venv)
```

---

## Step 3: Install PyTorch with CUDA

> Install torch FIRST before any other package — other packages pull a CPU-only torch from PyPI.

```bash
pip install "torch==2.7.1+cu118" --index-url https://download.pytorch.org/whl/cu118
```

Verify:
```bash
python -c "import torch; print(torch.__version__); print('CUDA:', torch.cuda.is_available()); print('GPU:', torch.cuda.get_device_name(0))"
# 2.7.1+cu118
# CUDA: True
# GPU: NVIDIA GeForce GTX 1050
```

---

## Step 4: Install HuggingFace dependencies

```bash
pip install "transformers>=4.40.0" "accelerate>=0.27.0" bitsandbytes
```

After this, verify CUDA torch was not overridden:
```bash
python -c "import torch; print(torch.__version__); print('CUDA:', torch.cuda.is_available())"
# Must still show 2.7.1+cu118 and CUDA: True
# If it shows +cpu, run: pip install "torch==2.7.1+cu118" --index-url https://download.pytorch.org/whl/cu118 --force-reinstall --no-deps
```

---

## Step 5: Install pytest

```bash
pip install pytest
```

---

## Step 6: Set model cache location

Run before any script that loads a model (or set permanently in system environment variables):
```bash
set HF_HOME=W:\LocalAgent\models
```

To make permanent:
- Open "Edit the system environment variables"
- User variables → New
- Name: HF_HOME, Value: W:\LocalAgent\models

---

## Step 7: Run the agent

```bash
set HF_HOME=W:\LocalAgent\models
python main.py
```

First run downloads ~2GB of model weights to W:\LocalAgent\models.
Subsequent runs load from cache in ~10 seconds.

---

## Step 8: Verify GPU is being used

In a second terminal during inference:
```bash
nvidia-smi dmon -s u -d 1
```

Expected output during generation:
```
# gpu    sm   mem   enc   dec
    0   100    33     0     0   ← sm: 100% = GPU compute at full load
```

To check device placement programmatically:
```bash
python scripts/diagnose_gpu.py
```

Expected:
```
Parameter devices: {'cuda:0'}
GPU memory allocated: 2.2 GB
```

---

## Step 9: Run tests

```bash
.venv\Scripts\pytest tests/test_session.py tests/test_core.py -v
# 6 passed
```

---

## Installed packages (final state)

```
torch==2.7.1+cu118
transformers==5.18.0
accelerate==1.15.0
bitsandbytes==0.50.2
pytest==9.1.1
```

Full list: `.venv\Scripts\pip list`

---

## Performance notes

- Model: Qwen2.5-3B-Instruct, 4-bit quantization
- Load time: ~10 seconds
- VRAM usage: ~2.2GB (fits entirely on GTX 1050)
- GPU compute during inference: sm 100% confirmed via `nvidia-smi dmon`
- Generation: streamed token by token — first token appears in ~1-2s, response feels immediate
- `do_sample=False` (greedy decoding) used for speed; set `do_sample=True` with `temperature=0.7` for more varied responses
- `max_new_tokens=256` default; increase in `agent/llm.py` if you need longer answers

## Streaming implementation (added after initial setup)

Streaming was added to eliminate the "wait for full response" delay.

**What changed:**
- `agent/llm.py` — added `generate_stream()` using `TextIteratorStreamer` (background thread yields tokens)
- `agent/core.py` — added `chat_stream()` which streams and accumulates full reply into history
- `main.py` — REPL now calls `chat_stream()` and prints chunks as they arrive

**Key detail:** `TextIteratorStreamer` runs `model.generate()` in a `Thread`. The main thread iterates the streamer and prints each chunk with `flush=True`. History is only written after the full reply is assembled.

---

## Known issues

### torch gets replaced with CPU-only version
When installing other packages, pip may upgrade torch to a version that has no CUDA build.
Fix: `pip install "torch==2.7.1+cu118" --index-url https://download.pytorch.org/whl/cu118 --force-reinstall --no-deps`

### HF_HOME not set
If `set HF_HOME=...` is not run before loading the model, weights download to
`C:\Users\<you>\.cache\huggingface` instead of `W:\LocalAgent\models`.
Fix: set HF_HOME as a permanent environment variable (Step 6).

### Symlink warning on Windows
```
UserWarning: huggingface_hub cache-system uses symlinks by default...
```
Harmless — Windows without Developer Mode copies files instead of symlinking.
Disable the warning: `set HF_HUB_DISABLE_SYMLINKS_WARNING=1`
