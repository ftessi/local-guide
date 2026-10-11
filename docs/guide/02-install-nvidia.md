# 2. Install: NVIDIA GPU (Windows / Linux)

Tested on Windows 10, GTX 1050 4 GB, Python 3.10.3, PyTorch 2.7.1+cu118, Transformers 5.18.

## 2.1 Get the code

```bash
git clone <repo-url> LocalAgent
cd LocalAgent
```

## 2.2 Create a virtual environment

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # Linux
```

You should see `(.venv)` in your prompt. Activate it every time you open a new terminal.

## 2.3 Install PyTorch FIRST

> **Important:** install PyTorch before anything else. If `transformers` or `bitsandbytes` goes in first, pip pulls a CPU-only torch and your GPU is silently ignored.

Run `nvidia-smi` and read **CUDA Version** in the top-right corner:

| nvidia-smi CUDA Version | Command |
|---|---|
| 11.6 – 11.8 | `pip install "torch==2.7.1+cu118" --index-url https://download.pytorch.org/whl/cu118` |
| 12.1 or newer | `pip install "torch==2.7.1+cu121" --index-url https://download.pytorch.org/whl/cu121` |

(On Windows, a driver that reports CUDA 11.6 works with the cu118 build.)

Check it:
```bash
python -c "import torch; print(torch.__version__, 'CUDA:', torch.cuda.is_available())"
```
You want `2.7.1+cu118` (or `+cu121`) and `CUDA: True`.

## 2.4 Install everything else

```bash
pip install "transformers>=4.40.0" "accelerate>=0.27.0" "bitsandbytes>=0.50.0" pyyaml cryptography ^
            fastapi "uvicorn[standard]" websockets python-dotenv "apscheduler>=3.10,<4" pywebpush pytest httpx
```
(On Linux, replace `^` with `\`.)

Then **check CUDA again**. pip sometimes replaces torch:
```bash
python -c "import torch; print(torch.__version__, 'CUDA:', torch.cuda.is_available())"
```

### If you now see `+cpu` or `CUDA: False`

Force the CUDA build back without touching anything else:
```bash
pip install "torch==2.7.1+cu118" --index-url https://download.pytorch.org/whl/cu118 --force-reinstall --no-deps
```

## 2.5 Check the install

```bash
pytest                         # ~10 s, no model needed, everything should pass
python scripts/diagnose.py     # shows your GPU, RAM and the recommended model
```

Models download into `LocalAgent/models/` the first time they're used; nothing to configure.

Next: [3. Create your agent](03-create-your-agent.md)
