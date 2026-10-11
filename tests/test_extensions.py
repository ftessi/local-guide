import shutil
import subprocess
import threading

import pytest

from localagent.config import load_config
from localagent.connect.base import Notifier
from localagent.connect.serve import serve
from localagent.extensions import (ExtensionError, available, extension_root, load_connections, load_tools,
                                   setup_connections, source_slug)
from localagent.installer import describe, install
from tests.fakes import FAKE_EXTENSIONS, write_agent_yaml


def test_load_tool_with_settings(tmp_path):
    tools = load_tools({"notes": {"compartment": "shared", "max_notes": 3}}, FAKE_EXTENSIONS, tmp_path,
                       None, ["private", "shared"])
    assert tools["notes"].compartment == "shared"
    assert tools["notes"].settings == {"max_notes": 3}
    assert tools["notes"].data_dir == tmp_path / "notes"


@pytest.mark.parametrize("cfg, fragment", [
    ({"nope": {}}, "python -m localagent install"),
    ({"notes": {"compartment": "family"}}, "family"),
    ({"notes": {"colour": "red"}}, "colour"),
])
def test_tool_errors(tmp_path, cfg, fragment):
    with pytest.raises(ExtensionError, match=fragment):
        load_tools(cfg, FAKE_EXTENSIONS, tmp_path, None, ["private", "shared"])


def test_connection_lifecycle_and_notifier(tmp_path):
    connections = load_connections({"dummy": {"greeting": "hi"}}, FAKE_EXTENSIONS)
    notifier = Notifier()
    tools = load_tools({"notes": {}}, FAKE_EXTENSIONS, tmp_path, notifier, ["private"])
    setup_connections(connections, {"dummy": {"greeting": "hi"}}, tmp_path, config=None, protocol=None,
                      agent=None, tools=tools, notifier=notifier)
    dummy = connections["dummy"]
    assert dummy.ctx.settings == {"greeting": "hi"} and dummy.ctx.data_dir.is_dir()

    tools["notes"].run("add", {"text": "stretch", "due": "2000-01-01T00:00:00"})
    stop = threading.Event()
    threading.Timer(0.2, stop.set).start()
    assert serve(connections, tools, stop) == 0
    assert dummy.events == ["setup", "start", "stop"]
    assert dummy.notifications == [("Note due", "stretch")]  # background job ran and reached the connection


def test_connection_unknown_setting(tmp_path):
    with pytest.raises(ExtensionError, match="port"):
        load_connections({"dummy": {"port": 1}}, FAKE_EXTENSIONS)


def test_notifier_survives_failing_channel():
    got = []
    n = Notifier()
    n.add(lambda t, b: 1 / 0)
    n.add(lambda t, b: got.append(t))
    n("title", "body")
    assert got == ["title"]


def test_available_lists_docstrings():
    found = available(FAKE_EXTENSIONS)
    assert found["tools"]["notes"].startswith("Notes: a tiny")
    assert list(found["connections"]) == ["dummy"]


def test_source_locations(tmp_path):
    assert source_slug("https://github.com/ftessi/local-guide-extensions.git") == "ftessi--local-guide-extensions"
    assert source_slug("git@github.com:ftessi/local-guide-extensions.git") == "ftessi--local-guide-extensions"
    d = write_agent_yaml(tmp_path / "a", installables="source: ../ext\n")
    assert extension_root(load_config(d)) == (tmp_path / "ext").resolve()


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _commit(origin, message):
    _git("add", "-A", cwd=origin)
    _git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", message, cwd=origin)


def test_install_clones_and_updates_a_git_source(tmp_path, monkeypatch):
    origin = tmp_path / "origin"
    shutil.copytree(FAKE_EXTENSIONS, origin, ignore=shutil.ignore_patterns("__pycache__"))
    _git("init", "-q", "-b", "main", cwd=origin)
    _commit(origin, "extensions")
    d = write_agent_yaml(tmp_path / "a", installables=f"source: file://{origin.as_posix()}\ntools:\n  notes:\n")
    config = load_config(d)
    root = tmp_path / "clone"
    monkeypatch.setattr("localagent.installer.extension_root", lambda cfg: root)  # not the repo's extensions/

    pip_calls = []
    assert install(config, log=lambda m: None, pip=pip_calls.append) == 0
    assert (root / "tools/notes/__init__.py").is_file() and pip_calls == []

    (origin / "tools/notes/requirements.txt").write_text("nothing-real\n")
    _commit(origin, "add requirements")
    assert install(config, log=lambda m: None, pip=pip_calls.append) == 0  # second run updates in place
    assert pip_calls == [root / "tools/notes/requirements.txt"]


def test_install_reports_missing_extension(tmp_path):
    d = write_agent_yaml(tmp_path / "a", installables=f"source: {FAKE_EXTENSIONS.as_posix()}\ntools:\n  weather:\n")
    with pytest.raises(ExtensionError, match="tools/weather.*Available: tools/notes, connections/dummy"):
        install(load_config(d), log=lambda m: None, pip=lambda r: None)


def test_describe_marks_used(tmp_path):
    d = write_agent_yaml(tmp_path / "a")
    text = describe(load_config(d))
    assert "[x] notes" in text and "[ ] dummy" in text
