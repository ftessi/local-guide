"""The relay's connection log: metadata only (who was reached, when, how many bytes), never content and never who
asked. One JSON object per line; lines older than `days` are removed at start and once a day."""
import json
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _time_of(line: str) -> str:
    try:
        value = json.loads(line).get("time", "")
    except (ValueError, AttributeError):
        return ""
    return value if isinstance(value, str) else ""


class RelayLog:
    def __init__(self, path: Path, days: int = 90, now=_utc_now):
        self.path, self.days, self.now = Path(path), days, now
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._pruned = None
        self.prune()

    def write(self, event: str, **fields) -> None:
        now = self.now()
        line = json.dumps({"time": now.strftime(TIME_FORMAT), "event": event, **fields}) + "\n"
        with self._lock:
            if self._pruned is None or now - self._pruned >= timedelta(days=1):
                self._prune(now)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(line)

    def prune(self) -> None:
        with self._lock:
            self._prune(self.now())

    def _prune(self, now: datetime) -> None:
        self._pruned = now
        if not self.path.is_file():
            return
        cutoff = (now - timedelta(days=self.days)).strftime(TIME_FORMAT)
        kept = [line for line in self.path.read_text(encoding="utf-8").splitlines(keepends=True)
                if _time_of(line) >= cutoff]
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text("".join(kept), encoding="utf-8")
        os.replace(tmp, self.path)
