"""Reminders in SQLite; due reminders are sent to the owner via notify()."""
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from localagent.agent.tools.base import Action, Tool

log = logging.getLogger(__name__)


class CalendarTool(Tool):
    name = "calendar"
    compartment = "private"
    actions = {
        "create": Action("Create a reminder", {"title": "str", "remind_at": "iso-datetime"}, kind="write"),
        "list": Action("List upcoming reminders with their ids, soonest first", {}, kind="read"),
        "delete": Action("Delete a reminder by its id", {"id": "int"}, kind="write"),
    }

    def __init__(self):
        self.db_path: Path | None = None
        self._notify = None

    def setup(self, data_dir, notify):
        Path(data_dir).mkdir(parents=True, exist_ok=True)
        self.db_path = Path(data_dir) / "calendar.db"
        self._notify = notify
        with self._db() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    remind_at TEXT NOT NULL,
                    fired INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now'))
                )
            """)

    @contextmanager
    def _db(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def create(self, title: str, remind_at: str) -> int:
        with self._db() as conn:
            return conn.execute(
                "INSERT INTO reminders (title, remind_at) VALUES (?, ?)", (title, remind_at)
            ).lastrowid

    def list_upcoming(self) -> list[dict]:
        with self._db() as conn:
            rows = conn.execute(
                "SELECT id, title, remind_at FROM reminders WHERE fired=0 ORDER BY remind_at"
            ).fetchall()
            return [dict(r) for r in rows]

    def delete(self, id_: int) -> bool:
        with self._db() as conn:
            return conn.execute("DELETE FROM reminders WHERE id=?", (id_,)).rowcount > 0

    def get_due(self) -> list[dict]:
        now = datetime.now().isoformat()
        with self._db() as conn:
            rows = conn.execute("SELECT * FROM reminders WHERE fired=0 AND remind_at <= ?", (now,)).fetchall()
            return [dict(r) for r in rows]

    def mark_fired(self, id_: int) -> None:
        with self._db() as conn:
            conn.execute("UPDATE reminders SET fired=1 WHERE id=?", (id_,))

    def run(self, action: str, args: dict) -> dict:
        if action == "create":
            return {"id": self.create(args["title"], args["remind_at"])}
        if action == "list":
            return {"reminders": self.list_upcoming()}
        if action == "delete":
            return {"deleted": self.delete(args["id"])}
        raise ValueError(f"Unknown calendar action '{action}'")

    def background(self) -> None:
        for reminder in self.get_due():
            try:
                if self._notify:
                    self._notify("Reminder", reminder["title"])
            except Exception:
                log.exception("Could not send reminder %s", reminder["id"])
            self.mark_fired(reminder["id"])
