from datetime import datetime, timezone

import pytest

from localagent.agent.tools.base import Action, ToolArgsError, validate_args

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


MORE = Action("x", {"path": "str", "n": "number", "flag": "bool", "items": "list", "opts": "object"},
              optional=frozenset({"n", "flag", "items", "opts"}))


def test_optional_args_may_be_left_out():
    assert validate_args(MORE, {"path": "a.txt"}) == {"path": "a.txt"}


def test_json_types_coerced():
    out = validate_args(MORE, {"path": "a", "n": "2.5", "flag": "true", "items": ["x"], "opts": {"k": 1}})
    assert out == {"path": "a", "n": 2.5, "flag": True, "items": ["x"], "opts": {"k": 1}}
    assert validate_args(MORE, {"path": "a", "n": 3})["n"] == 3


@pytest.mark.parametrize("args, fragment", [
    ({}, "path"),
    ({"path": "a", "n": "lots"}, "number"),
    ({"path": "a", "flag": "maybe"}, "true or false"),
    ({"path": "a", "items": "x"}, "list"),
    ({"path": "a", "opts": []}, "object"),
])
def test_json_types_rejected(args, fragment):
    with pytest.raises(ToolArgsError, match=fragment):
        validate_args(MORE, args)
