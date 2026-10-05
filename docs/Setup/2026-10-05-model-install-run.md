# Model Install and Run Guide — Qwen2.5-3B-Instruct
Date: 2026-10-05

This guide covers everything needed to download and run `Qwen/Qwen2.5-3B-Instruct` locally
using HuggingFace Transformers on Windows with a low-range GPU.

**Tested on:**
- OS: Windows 10 Pro
- GPU: NVIDIA GeForce GTX 1050 (4GB VRAM)
- CUDA driver version: 512.59 (reports CUDA 11.6, compatible with cu118 builds)
- Python: 3.10.3
- PyTorch: 2.7.1+cu118
- Transformers: 5.18.0
- bitsandbytes: 0.50.2
- accelerate: 1.15.0

> **For older machines (4GB VRAM or less):** use 4-bit quantization (Section 6 + 7.2).
> The model loads in ~9 seconds and the quantized weights download is ~2GB, not ~6GB.

---

## 1. Prerequisites

### 1.1 Python
Requires Python 3.10 or higher.

Check your version:
```bash
python --version
```

If not installed, download from https://www.python.org/downloads/
During installation, check "Add Python to PATH".

### 1.2 CUDA Drivers (for GPU acceleration)
Check if you have a CUDA-capable NVIDIA GPU and what CUDA version is supported:
```bash
nvidia-smi
```

Look for the "CUDA Version" in the top-right corner of the output (e.g., `12.1`).
If `nvidia-smi` is not found, your GPU may not support CUDA — you will run on CPU only (slower).

**CUDA version compatibility for PyTorch CUDA builds:**

| nvidia-smi CUDA Version | Use PyTorch build |
|-------------------------|-------------------|
| 11.6 or 11.7            | cu118 (works despite version mismatch on Windows) |
| 11.8                    | cu118 |
| 12.1+                   | cu121 |

Note: on Windows, driver 512.x reporting CUDA 11.6 is compatible with cu118 PyTorch builds in practice.

---

## 2. Create a Virtual Environment

Work inside a virtual environment to keep dependencies isolated:
```bash
cd W:\LocalAgent
python -m venv .venv
.venv\Scripts\activate
```

You should see `(.venv)` in your terminal prompt.

---

## 3. Install PyTorch

> **IMPORTANT — read before installing:** Install PyTorch FIRST, before any other package.
> If you install `transformers` or `bitsandbytes` first, pip will pull in a CPU-only torch from PyPI
> and override your CUDA build. If this happens, see Section 3.1 (Fix: CUDA torch was overridden).

Install PyTorch with the CUDA version matching your `nvidia-smi` output.

**For CUDA 11.6 / 11.7 / 11.8 (use cu118):**
```bash
pip install "torch==2.7.1+cu118" --index-url https://download.pytorch.org/whl/cu118
```

**For CUDA 12.1+:**
```bash
pip install "torch==2.7.1+cu121" --index-url https://download.pytorch.org/whl/cu121
```

**CPU only (no GPU):**
```bash
pip install torch
```

> Note: `torch 2.7.1` is the latest version available with a CUDA build on the PyTorch wheel index.
> Versions beyond this (e.g. 2.14.x) are CPU-only on PyPI and have no cu118/cu121 equivalent.

Verify CUDA is available before continuing:
```bash
python -c "import torch; print(torch.__version__); print('CUDA:', torch.cuda.is_available()); print('GPU:', torch.cuda.get_device_name(0))"
```
Expected output: `2.7.1+cu118`, `CUDA: True`, your GPU name.
If you see `+cpu` or `CUDA: False`, see Section 3.1.

### 3.1 Fix: CUDA torch was overridden by a CPU-only version

This happens when another package (bitsandbytes, transformers) upgrades torch to a version that has
no CUDA build on the PyTorch wheel index, pulling a CPU-only build from PyPI instead.

To fix, force-reinstall torch with CUDA without touching other packages:
```bash
pip install "torch==2.7.1+cu118" --index-url https://download.pytorch.org/whl/cu118 --force-reinstall --no-deps
```

Then verify CUDA again. This is safe — `--no-deps` ensures nothing else is changed.

---

## 4. Install HuggingFace Dependencies

After confirming torch+CUDA is working, install the rest:
```bash
pip install "transformers>=4.40.0" "accelerate>=0.27.0" bitsandbytes
```

After this, verify torch CUDA is still intact (pip may have overridden it):
```bash
python -c "import torch; print(torch.__version__); print('CUDA:', torch.cuda.is_available())"
```

If you see `+cpu` or `CUDA: False`, run the fix from Section 3.1.

---

## 5. Set Model Cache Location

By default, HuggingFace downloads models to `C:\Users\<you>\.cache\huggingface`.
To keep everything inside this project, point it to `W:\LocalAgent\models`:

Set the environment variable before running any Python script:
```bash
set HF_HOME=W:\LocalAgent\models
```

To make this permanent, add it to your Windows environment variables:
- Open "Edit the system environment variables"
- Under "User variables", click New
- Variable name: `HF_HOME`
- Variable value: `W:\LocalAgent\models`

---

## 6. VRAM Requirements and Quantization

`Qwen2.5-3B-Instruct` weight sizes by precision:

| Precision | VRAM needed | Quality |
|-----------|-------------|---------|
| float16   | ~6 GB       | Full    |
| 4-bit (bitsandbytes) | ~2 GB | Slightly reduced |

If your GPU has less than 6GB VRAM, use 4-bit quantization (see Section 7.2).
If you have no GPU or less than 2GB VRAM, the model will run on CPU — expect slow responses (30-60s per reply).

---

## 7. Download and Run the Model

### 7.1 Full precision (6GB+ VRAM)
```python
from transformers import AutoTokenizer, AutoModelForCausalLM
import torch

model_id = "Qwen/Qwen2.5-3B-Instruct"

# First run: downloads ~6GB of weights to W:\LocalAgent\models
tokenizer = AutoTokenizer.from_pretrained(model_id)
model = AutoModelForCausalLM.from_pretrained(
    model_id,
    torch_dtype=torch.float16,
    device_map="auto"   # puts layers on GPU, spills to CPU if needed
)

# Quick test
messages = [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "Say hello in one sentence."}
]
text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
inputs = tokenizer([text], return_tensors="pt").to(model.device)
output = model.generate(**inputs, max_new_tokens=50)
print(tokenizer.decode(output[0], skip_special_tokens=True))
```

### 7.2 4-bit quantization (under 6GB VRAM)
```python
from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
import torch

model_id = "Qwen/Qwen2.5-3B-Instruct"

quant_config = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.float16)

tokenizer = AutoTokenizer.from_pretrained(model_id)
model = AutoModelForCausalLM.from_pretrained(
    model_id,
    quantization_config=quant_config,
    device_map="auto"
)

# Same test as above
messages = [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "Say hello in one sentence."}
]
text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
inputs = tokenizer([text], return_tensors="pt").to(model.device)
output = model.generate(**inputs, max_new_tokens=50)
print(tokenizer.decode(output[0], skip_special_tokens=True))
```

---

## 8. First Run Notes

- **4-bit download size: ~2GB** (not ~6GB — quantization reduces the download too).
  Full float16 weights are ~6GB.
- First run downloads weights to `W:\LocalAgent\models\hub\`. Subsequent runs load from cache — fast.
- Model load time on GTX 1050 (4-bit): ~9 seconds (434 weight files).
- Do not interrupt the download — if it fails mid-way, delete the partial folder under
  `W:\LocalAgent\models\hub\` and retry.
- `device_map="auto"` places model layers on GPU and overflows to CPU RAM if needed.
  On 4GB VRAM with 4-bit quantization, everything fits on GPU.
- The output includes chat template role labels (`system`, `user`, `assistant`) — this is normal.
  These will be stripped when building the actual agent interface.

---

## 9. requirements.txt

The `requirements.txt` in this project pins torch to a CUDA build to prevent it being overridden:
```
--extra-index-url https://download.pytorch.org/whl/cu118
torch==2.7.1+cu118
transformers>=4.40.0
accelerate>=0.27.0
bitsandbytes>=0.50.0
```

**Do not use plain `pip install -r requirements.txt`** for torch — the `--extra-index-url` line
in the file is not always respected depending on pip version. Install torch manually first (Section 3),
then install the rest:
```bash
pip install "transformers>=4.40.0" "accelerate>=0.27.0" bitsandbytes
```

Then verify CUDA as described in Section 4.
