from datetime import datetime, timedelta

import pytest

from localagent.agent.tools.calendar import TOOL as CalendarTool


@pytest.fixture
def notified():
    return []


@pytest.fixture
def cal(tmp_path, notified):
    tool = CalendarTool()
    tool.setup(tmp_path / "calendar", lambda title, body: notified.append((title, body)))
    return tool


def iso(delta):
    return (datetime.now() + delta).isoformat(timespec="seconds")


def test_create_list_delete(cal):
    rid = cal.run("create", {"title": "Call John", "remind_at": iso(timedelta(hours=1))})["id"]
    assert [r["title"] for r in cal.run("list", {})["reminders"]] == ["Call John"]
    assert cal.run("delete", {"id": rid}) == {"deleted": True}
    assert cal.run("delete", {"id": rid}) == {"deleted": False}
    assert cal.run("list", {})["reminders"] == []


def test_background_fires_due_once(cal, notified):
    cal.run("create", {"title": "Overdue", "remind_at": iso(-timedelta(seconds=1))})
    cal.run("create", {"title": "Future", "remind_at": iso(timedelta(hours=1))})
    cal.background()
    cal.background()
    assert notified == [("Reminder", "Overdue")]


def test_notify_failure_still_marks_fired(tmp_path):
    tool = CalendarTool()

    def boom(title, body):
        raise RuntimeError("push down")

    tool.setup(tmp_path / "c", boom)
    tool.run("create", {"title": "X", "remind_at": iso(-timedelta(seconds=1))})
    tool.background()
    assert tool.get_due() == []
