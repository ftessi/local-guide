For an M4 Mac with 16GB RAM, the setup is different — Apple Silicon uses MPS (Metal Performance Shaders) instead of
    CUDA, and no bitsandbytes (it doesn't support MPS).

from transformers import AutoTokenizer, AutoModelForCausalLM
import torch

model_id = "Qwen/Qwen2.5-3B-Instruct"

tokenizer = AutoTokenizer.from_pretrained(model_id)
model = AutoModelForCausalLM.from_pretrained(
    model_id,
    torch_dtype=torch.float16,
    device_map="mps"  # Apple Silicon GPU
)

messages = [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "Say hello in one sentence."}
]
text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
inputs = tokenizer([text], return_tensors="pt").to("mps")
input_len = inputs["input_ids"].shape[1]

output_ids = model.generate(**inputs, max_new_tokens=256, pad_token_id=tokenizer.eos_token_id)
reply = tokenizer.decode(output_ids[0][input_len:], skip_special_tokens=True).strip()
print(reply)

    Install deps (no bitsandbytes needed):
    pip install torch transformers accelerate

    Key differences from the Windows/CUDA setup:
    - device_map="mps" instead of "auto" with CUDA
    - No BitsAndBytesConfig — 4-bit quantization via bitsandbytes doesn't work on MPS
    - With 16GB unified RAM, float16 for a 3B model (~6GB) fits comfortably — no quantization needed
    - If memory is tight, torch_dtype=torch.float32 uses more RAM; stick with float16

    With M4 and 16GB, the 3B model in float16 will run well. For a larger model like 7B (~14GB float16), it would be
    tight — they could try Qwen/Qwen2.5-7B-Instruct and see if it fits.