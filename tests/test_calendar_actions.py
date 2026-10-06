"""Tests for calendar action tag parsing in agent/core.py"""
import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock
from agent.core import _parse_calendar_actions, _strip_action_tags, Agent


# ── Tag parsing ──────────────────────────────────────────────────────────────

def test_parse_create_action():
    text = 'Sure! <cal>{"action":"create","title":"Call John","remind_at":"2026-10-07T15:00:00"}</cal>'
    actions = _parse_calendar_actions(text)
    assert len(actions) == 1
    assert actions[0] == ("create", {"title": "Call John", "remind_at": "2026-10-07T15:00:00"})


def test_parse_delete_action():
    text = 'Deleted. <cal>{"action":"delete","id":3}</cal>'
    actions = _parse_calendar_actions(text)
    assert len(actions) == 1
    assert actions[0] == ("delete", {"id": 3})


def test_parse_multiple_actions():
    text = (
        'Done! '
        '<cal>{"action":"create","title":"Meeting","remind_at":"2026-10-07T09:00:00"}</cal>'
        '<cal>{"action":"create","title":"Prep reminder","remind_at":"2026-10-07T08:45:00"}</cal>'
    )
    actions = _parse_calendar_actions(text)
    assert len(actions) == 2
    assert actions[0][0] == "create"
    assert actions[1][0] == "create"
    assert actions[0][1]["title"] == "Meeting"
    assert actions[1][1]["title"] == "Prep reminder"


def test_parse_no_actions():
    text = "Hello! How can I help you today?"
    assert _parse_calendar_actions(text) == []


def test_parse_malformed_json_skipped():
    text = '<cal>not valid json</cal>'
    assert _parse_calendar_actions(text) == []


def test_strip_removes_tags():
    text = 'Reminder set! <cal>{"action":"create","title":"X","remind_at":"2026-10-07T10:00:00"}</cal>'
    stripped = _strip_action_tags(text)
    assert "<cal>" not in stripped
    assert "</cal>" not in stripped
    assert "Reminder set!" in stripped


def test_strip_preserves_spaces():
    text = 'Hello there <cal>{"action":"create","title":"X","remind_at":"2026-10-07T10:00:00"}</cal> how are you'
    stripped = _strip_action_tags(text)
    assert "Hello there" in stripped
    assert "how are you" in stripped


def test_strip_no_tags_unchanged():
    text = "No tags here, just a normal message."
    assert _strip_action_tags(text) == text


# ── chat_stream_async creates calendar entries ────────────────────────────────

@pytest.fixture
def mock_llm_with_cal_tag():
    llm = MagicMock()
    llm.generate_stream.return_value = iter([
        'Got it! ',
        '<cal>{"action":"create","title":"Test Event","remind_at":"2026-10-07T10:00:00"}</cal>'
    ])
    return llm


@pytest.fixture
def mock_session():
    session = MagicMock()
    session.build_system_prompt.return_value = "You are a helpful assistant."
    return session


def test_chat_stream_async_creates_calendar_entry(mock_llm_with_cal_tag, mock_session, tmp_path):
    from agent.calendar import CalendarModule
    cal = CalendarModule(db_path=str(tmp_path / "test.db"))
    agent = Agent(llm=mock_llm_with_cal_tag, session=mock_session)

    async def run():
        chunks = []
        async for chunk in agent.chat_stream_async("Remind me tomorrow at 10am", calendar=cal):
            chunks.append(chunk)
        return chunks

    result = asyncio.run(run())
    full_text = "".join(result)

    # Tags must not appear in output
    assert "<cal>" not in full_text
    assert "</cal>" not in full_text

    # Calendar entry must have been created
    entries = cal.list_upcoming()
    assert len(entries) == 1
    assert entries[0]["title"] == "Test Event"


def test_chat_stream_async_no_cal_tag(mock_session, tmp_path):
    from agent.calendar import CalendarModule
    llm = MagicMock()
    llm.generate_stream.return_value = iter(["Hello! ", "How can I help?"])
    cal = CalendarModule(db_path=str(tmp_path / "test.db"))
    agent = Agent(llm=llm, session=mock_session)

    async def run():
        chunks = []
        async for chunk in agent.chat_stream_async("Hi", calendar=cal):
            chunks.append(chunk)
        return chunks

    result = asyncio.run(run())
    assert "Hello!" in "".join(result)
    assert cal.list_upcoming() == []
