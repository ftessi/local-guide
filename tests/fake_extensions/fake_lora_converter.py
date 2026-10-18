"""Stands in for llama.cpp's convert_lora_to_gguf.py in tests: same arguments. Writes "LORA <base model>" to
--outfile and logs each run to <adapter>/conversions.log; fails like the real one without adapter weights."""
import argparse
import sys
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("adapter")
p.add_argument("--base-model-id", required=True)
p.add_argument("--outfile", required=True)
p.add_argument("--outtype", default="f16")
args = p.parse_args()
adapter = Path(args.adapter)
if not (adapter / "adapter_model.safetensors").is_file():
    print(f"ERROR: no adapter_model.safetensors in {adapter}", file=sys.stderr)
    sys.exit(1)
Path(args.outfile).write_text(f"LORA {args.base_model_id}", encoding="utf-8")
with (adapter / "conversions.log").open("a", encoding="utf-8") as log:
    log.write("converted\n")
