"""Hardware report + recommendation; with --load, also loads the agent's model and shows where it lives.
Usage: python scripts/diagnose.py [--load] [--agent my-agent]"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from localagent.runtime.hardware import detect  # noqa: E402

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--load", action="store_true", help="also load the agent's model")
    p.add_argument("--agent")
    args = p.parse_args()
    print(json.dumps(detect(), indent=2))
    if args.load:
        from localagent.config import ensure_hf_home, load_config, resolve_agent_dir
        from localagent.runtime.factory import create_backend

        cfg = load_config(resolve_agent_dir(args.agent))
        ensure_hf_home()
        backend = create_backend(cfg.model.backend, cfg.model)
        start = time.perf_counter()
        backend.load(cfg.model.id, cfg.model.quantization)
        print(f"Loaded {cfg.model.id} in {time.perf_counter() - start:.1f}s")
        model = getattr(backend, "model", None)
        if model is not None:
            print("Parameter devices:", sorted({str(q.device) for q in model.parameters()}))
        print(backend.info())
