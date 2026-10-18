"""Download llama-server for the llamacpp backend into LocalAgent/llama.cpp/, with the LoRA adapter converter.
Usage: python scripts/get_llamacpp.py [--build auto|cpu|vulkan|cuda|metal] [--tag b11576]

auto: Vulkan with an NVIDIA GPU (runs on old drivers too), Metal on Apple Silicon, otherwise CPU.
cuda needs an NVIDIA driver with CUDA 12.4+ (nvidia-smi, top right); Vulkan is close in speed on small cards.
"""
import argparse
import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from localagent.runtime.hardware import detect  # noqa: E402
from localagent.runtime.llamacpp_install import SERVER_DIR, TESTED_TAG, choose_build, install  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--build", default="auto", choices=["auto", "cpu", "vulkan", "cuda", "metal"])
    p.add_argument("--tag", default=TESTED_TAG, help="llama.cpp release (github.com/ggml-org/llama.cpp/releases)")
    args = p.parse_args()
    build = choose_build(detect()["gpu"]) if args.build == "auto" else args.build
    try:
        install(SERVER_DIR, build, args.tag, platform.system(), platform.machine())
    except ValueError as e:
        print(f"Error: {e}")
        return 1
    print(f"Installed llama.cpp {args.tag} ({build}) in {SERVER_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
