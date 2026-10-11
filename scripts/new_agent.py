"""Create your agent folder: python scripts/new_agent.py [--agent my-agent] [--no-detect]"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from localagent.config import DEFAULT_AGENT_DIR  # noqa: E402
from localagent.setup_agent import create_agent  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--agent", default=str(DEFAULT_AGENT_DIR), help="folder to create")
    p.add_argument("--no-detect", action="store_true", help="skip hardware detection, keep the template model")
    args = p.parse_args()

    model = None
    if not args.no_detect:
        from localagent.runtime.hardware import detect
        info = detect()
        gpu = info["gpu"]
        gpu_text = f"{gpu['name']} ({gpu['vram_gb']} GB)" if gpu else "none"
        print(f"Hardware: {info['os']} | RAM {info['ram_gb']} GB | GPU: {gpu_text}")
        if info["backend_available"]:
            model = {"id": info["recommended_model"], "backend": info["recommended_backend"],
                     "quantization": info["recommended_quantization"]}
            print(f"Recommended: {model['id']} ({model['quantization']}) on {model['backend']}")
        else:
            print(f"The recommended backend '{info['recommended_backend']}' is not available yet; keeping "
                  f"the template default (transformers). It runs, but slowly without an NVIDIA GPU.")
    try:
        agent_id = create_agent(Path(args.agent), model=model)
    except FileExistsError as e:
        print(f"Error: {e}")
        return 1
    print(f"\nCreated agent at {args.agent}\nAgent id: {agent_id}")
    print("Next: review agent.yaml, add facts to knowledge/private/, then run:")
    print(f"  python -m localagent chat --agent \"{args.agent}\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
