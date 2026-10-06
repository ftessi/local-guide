import os

# Any HuggingFace chat model id works here. Override without editing code by
# setting MODEL_ID in .env (e.g. MODEL_ID=Qwen/Qwen2.5-1.5B-Instruct).
MODEL_ID = os.getenv("MODEL_ID", "Qwen/Qwen2.5-3B-Instruct")

# 4-bit quantization keeps a 3B model at ~2.2GB VRAM. Set USE_4BIT=0 to load in fp16.
USE_4BIT = os.getenv("USE_4BIT", "1") != "0"

# Max tokens generated per reply.
MAX_NEW_TOKENS = int(os.getenv("MAX_NEW_TOKENS", "256"))
