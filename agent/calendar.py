import sqlite3
from datetime import datetime
from pathlib import Path
from apscheduler.schedulers.background import BackgroundScheduler


DB_PATH = Path(__file__).parent.parent / "calendar.db"


class CalendarModule:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or str(DB_PATH)
        self._scheduler = None
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    remind_at TEXT NOT NULL,
                    fired INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now'))
                )
            """)

    def create(self, title: str, remind_at: str) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO reminders (title, remind_at) VALUES (?, ?)",
                (title, remind_at)
            )
            return cur.lastrowid

    def list_upcoming(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM reminders WHERE fired=0 ORDER BY remind_at ASC"
            ).fetchall()
            return [dict(r) for r in rows]

    def delete(self, id_: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM reminders WHERE id=?", (id_,))
            return cur.rowcount > 0

    def get_due(self) -> list[dict]:
        now = datetime.now().isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM reminders WHERE fired=0 AND remind_at <= ?", (now,)
            ).fetchall()
            return [dict(r) for r in rows]

    def mark_fired(self, id_: int):
        with self._connect() as conn:
            conn.execute("UPDATE reminders SET fired=1 WHERE id=?", (id_,))

    def start(self, push=None):
        self._scheduler = BackgroundScheduler()
        cal = self

        def _check_reminders():
            for reminder in cal.get_due():
                if push:
                    push.send(title="Reminder", body=reminder["title"])
                cal.mark_fired(reminder["id"])

        self._scheduler.add_job(_check_reminders, "interval", minutes=1)
        self._scheduler.start()

    def stop(self):
        if self._scheduler:
            self._scheduler.shutdown()
