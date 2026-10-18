"""A trained adapter (PEFT safetensors, as training writes it) in llama.cpp's GGUF format.

The PEFT folder is the adapter; adapter.gguf next to it is derived from it with llama.cpp's own converter, the
first time the llamacpp backend uses it, and again whenever the adapter is retrained. Copying the folder (export
to a Tessera-facing agent, another computer) carries both; a missing or stale adapter.gguf is simply rebuilt.
"""
import os
import subprocess
import sys
from pathlib import Path

from localagent.runtime.base import AdapterLoadError
from localagent.runtime.llamacpp_install import CONVERTER_DIR

GGUF_NAME = "adapter.gguf"
WEIGHTS = "adapter_model.safetensors"


def default_converter() -> list[str]:
    return [sys.executable, str(CONVERTER_DIR / "convert_lora_to_gguf.py")]


def gguf_adapter(adapter_dir: Path, base_model_id: str, converter: list[str] | None = None) -> tuple[Path, bool]:
    """The adapter's GGUF file, converted if missing or older than the weights. Returns (path, converted now)."""
    adapter_dir = Path(adapter_dir)
    target = adapter_dir / GGUF_NAME
    weights = adapter_dir / WEIGHTS
    if target.is_file() and weights.is_file() and target.stat().st_mtime >= weights.stat().st_mtime:
        return target, False
    command = converter or default_converter()
    if not Path(command[-1]).is_file():
        raise AdapterLoadError("The LoRA converter for llama.cpp is missing: run python scripts/get_llamacpp.py "
                               "again (it also installs the converter now)")
    tmp = target.with_name(GGUF_NAME + ".tmp")
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(CONVERTER_DIR / "gguf-py"), env.get("PYTHONPATH")]))
    result = subprocess.run([*command, str(adapter_dir), "--base-model-id", base_model_id, "--outfile", str(tmp),
                             "--outtype", "f16"], capture_output=True, text=True, env=env, timeout=600)
    if result.returncode != 0 or not tmp.is_file():
        tmp.unlink(missing_ok=True)
        tail = "\n".join((result.stdout + result.stderr).strip().splitlines()[-8:])
        raise AdapterLoadError(f"Could not convert the adapter {adapter_dir} for llama.cpp:\n{tail}")
    os.replace(tmp, target)
    return target, True
