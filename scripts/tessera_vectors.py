"""Writes Tessera's test vectors to tests/data/tessera_vectors_v0.1.json (copy it to tessera-protocol/vectors/).

Usage: python scripts/tessera_vectors.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from localagent.protocol.tessera.vectors import build_vectors  # noqa: E402

OUT = ROOT / "tests" / "data" / "tessera_vectors_v0.1.json"

if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes((json.dumps(build_vectors(), indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    print(f"Wrote {OUT}")
