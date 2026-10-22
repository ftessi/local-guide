import json
from datetime import datetime, timedelta, timezone

from localagent.relay.log import RelayLog


class Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.now


def lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_write_and_prune(tmp_path):
    clock = Clock()
    log = RelayLog(tmp_path / "connections.jsonl", days=90, now=clock)
    log.write("register", agent="x")
    clock.now += timedelta(days=91)
    log.write("drop", agent="x")  # a day has passed since the last prune: old lines go
    assert [(e["event"], e["time"]) for e in lines(tmp_path / "connections.jsonl")] == [("drop", "2027-01-22T12:00:00Z")]


def test_prune_at_start_keeps_recent_lines(tmp_path):
    path = tmp_path / "connections.jsonl"
    path.write_text('{"time": "2020-01-01T00:00:00Z", "event": "old"}\nnot json\n'
                    '{"time": "2026-10-22T00:00:00Z", "event": "new"}\n', encoding="utf-8")
    RelayLog(path, days=90, now=Clock())
    assert [e["event"] for e in lines(path)] == ["new"]
