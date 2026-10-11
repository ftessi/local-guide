# 2. Install: CPU only

> 🚧 **Coming later.** The fast CPU path uses a **llama.cpp** backend (quantized GGUF models), which isn't written yet.

What this page will cover:
- `pip install llama-cpp-python`
- `backend: llamacpp` in `agent.yaml`, with a GGUF model sized to your RAM (16 GB → 3B, 8 GB → 1.5B)

**Works today, slowly:** follow the [NVIDIA page](02-install-nvidia.md), but install torch with a plain `pip install torch` and skip `bitsandbytes`. In step 3 set:

```yaml
model:
  id: Qwen/Qwen2.5-1.5B-Instruct
  backend: transformers
  quantization: none
```

Measured on a desktop CPU: about 3 tokens/s, so a reply takes 20–30 s.
