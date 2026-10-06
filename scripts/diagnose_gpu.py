from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
import torch

model_id = "Qwen/Qwen2.5-3B-Instruct"

quant_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_compute_dtype=torch.float16,
)

print("CUDA available:", torch.cuda.is_available())
print("GPU:", torch.cuda.get_device_name(0) if torch.cuda.is_available() else "none")

tokenizer = AutoTokenizer.from_pretrained(model_id)
model = AutoModelForCausalLM.from_pretrained(
    model_id,
    quantization_config=quant_config,
    device_map="auto",
)

print("\nDevice map:")
# Check where model parameters actually live
devices = set()
for name, param in model.named_parameters():
    devices.add(str(param.device))
for name, buf in model.named_buffers():
    devices.add(str(buf.device))
print("Parameter devices:", devices)
print("model.device:", model.device if hasattr(model, "device") else "N/A")

print("\nGPU memory allocated:", round(torch.cuda.memory_allocated() / 1e9, 2), "GB")
print("GPU memory reserved:", round(torch.cuda.memory_reserved() / 1e9, 2), "GB")

# Run one inference and check GPU utilization
messages = [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "Count from 1 to 20."}
]
text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
inputs = tokenizer([text], return_tensors="pt").to(model.device)
input_len = inputs["input_ids"].shape[1]

print("\nRunning inference...")
output_ids = model.generate(**inputs, max_new_tokens=100, pad_token_id=tokenizer.eos_token_id)
reply = tokenizer.decode(output_ids[0][input_len:], skip_special_tokens=True).strip()
print("Reply:", reply)

print("\nGPU memory after inference:", round(torch.cuda.memory_allocated() / 1e9, 2), "GB")
