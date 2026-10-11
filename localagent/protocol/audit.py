"""Append-only audit log of sessions and refusals. Never records message content."""
import json
import threading
from datetime import datetime
from pathlib import Path


class Audit:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def log(self, event: str, **fields) -> None:
        record = {"ts": datetime.now().isoformat(timespec="seconds"), "event": event, **fields}
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
