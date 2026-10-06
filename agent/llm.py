from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig, TextIteratorStreamer
from threading import Thread
import torch

from agent.config import MAX_NEW_TOKENS


class LLMEngine:
    def __init__(self, model_id: str, use_4bit: bool = True):
        quant_config = None
        if use_4bit:
            quant_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_compute_dtype=torch.float16,
            )

        self.tokenizer = AutoTokenizer.from_pretrained(model_id)
        self.model = AutoModelForCausalLM.from_pretrained(
            model_id,
            quantization_config=quant_config,
            torch_dtype=None if use_4bit else torch.float16,
            device_map="auto",
        )

    def _prepare_inputs(self, messages: list[dict]):
        text = self.tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        return self.tokenizer([text], return_tensors="pt").to(self.model.device)

    def generate(self, messages: list[dict], max_new_tokens: int = MAX_NEW_TOKENS) -> str:
        inputs = self._prepare_inputs(messages)
        input_len = inputs["input_ids"].shape[1]

        output_ids = self.model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            pad_token_id=self.tokenizer.eos_token_id,
        )
        new_tokens = output_ids[0][input_len:]
        return self.tokenizer.decode(new_tokens, skip_special_tokens=True).strip()

    def generate_stream(self, messages: list[dict], max_new_tokens: int = MAX_NEW_TOKENS):
        """Yields text chunks as they are generated."""
        inputs = self._prepare_inputs(messages)
        streamer = TextIteratorStreamer(
            self.tokenizer, skip_prompt=True, skip_special_tokens=True
        )
        generation_kwargs = dict(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            pad_token_id=self.tokenizer.eos_token_id,
            streamer=streamer,
        )
        thread = Thread(target=self.model.generate, kwargs=generation_kwargs)
        thread.start()
        for chunk in streamer:
            yield chunk
        thread.join()
