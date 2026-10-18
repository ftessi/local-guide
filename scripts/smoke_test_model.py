"""Load the agent's configured model and say hello. Usage: python scripts/smoke_test_model.py [--agent DIR]"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from localagent.config import ensure_hf_home, load_config, resolve_agent_dir  # noqa: E402
from localagent.runtime.factory import create_backend  # noqa: E402

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--agent")
    cfg = load_config(resolve_agent_dir(p.parse_args().agent))
    ensure_hf_home()
    backend = create_backend(cfg.model.backend, cfg.model)
    print(f"Loading {cfg.model.id} ({cfg.model.quantization})...")
    backend.load(cfg.model.id, cfg.model.quantization)
    print(backend.generate([{"role": "user", "content": "Say hello in one sentence."}], 50))
