"""Move pre-restructure data (knowledge/, calendar.db, .env secrets...) into an agent folder.
Usage: python scripts/migrate_legacy.py [--agent my-agent] [--dry-run]"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from localagent.config import DEFAULT_AGENT_DIR  # noqa: E402
from localagent.setup_agent import migrate_legacy  # noqa: E402

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--agent", default=str(DEFAULT_AGENT_DIR))
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    for line in migrate_legacy(ROOT, Path(args.agent), dry_run=args.dry_run):
        print(line)
