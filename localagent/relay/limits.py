"""Per-visitor limits: at most N events per key (an IP address) in any 60 seconds. In memory only."""
import threading
import time
from collections import deque

WINDOW = 60.0


class RateLimiter:
    def __init__(self, per_minute: int, clock=time.monotonic):
        self.per_minute, self.clock = per_minute, clock
        self._seen: dict[str, deque] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        with self._lock:
            now = self.clock()
            for k in [k for k, times in self._seen.items() if times[-1] <= now - WINDOW]:
                del self._seen[k]  # idle keys go, so memory stays bounded by recent visitors
            times = self._seen.setdefault(key, deque())
            while times and times[0] <= now - WINDOW:
                times.popleft()
            if len(times) >= self.per_minute:
                return False
            times.append(now)
            return True

    def __len__(self) -> int:
        with self._lock:
            return len(self._seen)
