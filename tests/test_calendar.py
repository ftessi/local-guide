import pytest
from datetime import datetime, timedelta
from agent.calendar import CalendarModule


@pytest.fixture
def cal(tmp_path):
    return CalendarModule(db_path=str(tmp_path / "test.db"))


def test_create_and_list(cal):
    future = (datetime.now() + timedelta(hours=1)).isoformat()
    id_ = cal.create("Call John", future)
    items = cal.list_upcoming()
    assert len(items) == 1
    assert items[0]["title"] == "Call John"
    assert items[0]["id"] == id_


def test_delete(cal):
    future = (datetime.now() + timedelta(hours=1)).isoformat()
    id_ = cal.create("Test", future)
    assert cal.delete(id_) is True
    assert cal.list_upcoming() == []


def test_delete_nonexistent(cal):
    assert cal.delete(999) is False


def test_due_reminders(cal):
    past = (datetime.now() - timedelta(seconds=1)).isoformat()
    future = (datetime.now() + timedelta(hours=1)).isoformat()
    cal.create("Overdue", past)
    cal.create("Future", future)
    due = cal.get_due()
    assert len(due) == 1
    assert due[0]["title"] == "Overdue"


def test_mark_fired(cal):
    past = (datetime.now() - timedelta(seconds=1)).isoformat()
    id_ = cal.create("Overdue", past)
    cal.mark_fired(id_)
    assert cal.get_due() == []
