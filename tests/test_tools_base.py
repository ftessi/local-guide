from datetime import datetime, timezone

import pytest

from localagent.agent.tools.base import Action, ToolArgsError, validate_args
from localagent.agent.tools.registry import ToolConfigError, load_tools

ACT = Action("x", {"title": "str", "n": "int", "at": "iso-datetime"}, kind="write")


def test_valid_args_coerced():
    out = validate_args(ACT, {"title": " Hi ", "n": "3", "at": "2026-10-12T18:00:00"})
    assert out == {"title": "Hi", "n": 3, "at": "2026-10-12T18:00:00"}


@pytest.mark.parametrize("args, fragment", [
    ({"n": 1, "at": "2026-10-12T18:00"}, "title"),
    ({"title": "a", "n": "x", "at": "2026-10-12T18:00"}, "integer"),
    ({"title": "a", "n": True, "at": "2026-10-12T18:00"}, "integer"),
    ({"title": "a", "n": 1, "at": "tomorrow"}, "ISO"),
    ({"title": "a", "n": 1, "at": "2026-10-12T18:00", "extra": 1}, "extra"),
])
def test_invalid_args(args, fragment):
    with pytest.raises(ToolArgsError, match=fragment):
        validate_args(ACT, args)


def test_iso_datetime_timezone_converted_to_local_naive():
    out = validate_args(Action("x", {"at": "iso-datetime"}), {"at": "2026-10-12T16:00:00Z"})["at"]
    expected = datetime(2026, 10, 12, 16, tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
    assert out == expected.isoformat(timespec="seconds")


def test_iso_datetime_date_only_is_midnight():
    assert validate_args(Action("x", {"at": "iso-datetime"}), {"at": "2026-10-12"})["at"] == "2026-10-12T00:00:00"


def test_registry_loads_calendar(tmp_path):
    tools = load_tools({"calendar": {}}, tmp_path, lambda t, b: None, ["private", "shared"])
    assert list(tools) == ["calendar"]
    assert (tmp_path / "calendar/calendar.db").exists()


def test_registry_disabled_and_override(tmp_path):
    assert load_tools({"calendar": {"enabled": False}}, tmp_path, None, ["private"]) == {}
    tools = load_tools({"calendar": {"compartment": "shared"}}, tmp_path, None, ["private", "shared"])
    assert tools["calendar"].compartment == "shared"


@pytest.mark.parametrize("cfg, fragment", [
    ({"nope": {}}, "Unknown tool"),
    ({"calendar": {"compartment": "family"}}, "family"),
    ({"calendar": {"colour": "red"}}, "colour"),
])
def test_registry_errors(tmp_path, cfg, fragment):
    with pytest.raises(ToolConfigError, match=fragment):
        load_tools(cfg, tmp_path, None, ["private", "shared"])
