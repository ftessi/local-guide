import shutil
import subprocess
import threading

import pytest

from localagent.config import load_config
from localagent.connect.base import Notifier
from localagent.connect.serve import serve
from localagent.extensions import (ExtensionError, close_tools, load_connections, load_tools, setup_connections,
                                   source_dir)
from localagent.installer import describe, install
from tests.fakes import DUMMY_SOURCE, FAKE_EXTENSIONS, MCP_SERVER, NOTES_SOURCE, write_agent_yaml


def test_load_tool_with_settings(tmp_path):
    cfg = {"notes": {"source": NOTES_SOURCE, "compartment": "shared", "max_notes": 3, "confirm": True}}
    tools = load_tools(cfg, tmp_path, tmp_path / "data", None, ["private", "shared"])
    assert tools["notes"].confirm is True
    assert tools["notes"].compartment == "shared"
    assert tools["notes"].settings == {"max_notes": 3}
    assert tools["notes"].data_dir == tmp_path / "data/notes"


def test_relative_source_is_relative_to_agent_folder(tmp_path):
    shutil.copytree(FAKE_EXTENSIONS / "tools/notes", tmp_path / "mytools/notes")
    tools = load_tools({"notes": {"source": "../mytools/notes"}}, tmp_path / "agent", tmp_path / "data", None,
                       ["private"])
    assert list(tools) == ["notes"]


@pytest.mark.parametrize("cfg, fragment", [
    ({"nope": {"source": "./missing"}}, "python -m localagent install"),
    ({"notes": {"source": NOTES_SOURCE, "compartment": "family"}}, "family"),
    ({"notes": {"source": NOTES_SOURCE, "colour": "red"}}, "colour"),
    ({"web": {"mcp": ["python", MCP_SERVER], "colour": "red"}}, "colour"),
])
def test_tool_errors(tmp_path, cfg, fragment):
    with pytest.raises(ExtensionError, match=fragment):
        load_tools(cfg, tmp_path, tmp_path / "data", None, ["private", "shared"])


def test_mcp_tool_loaded_next_to_native_one(tmp_path):
    cfg = {"notes": {"source": NOTES_SOURCE},
           "test": {"mcp": ["python", MCP_SERVER], "actions": ["echo"], "compartment": "shared"}}
    tools = load_tools(cfg, tmp_path, tmp_path / "data", None, ["private", "shared"])
    try:
        assert list(tools) == ["notes", "test"]
        assert tools["test"].compartment == "shared" and list(tools["test"].actions) == ["echo"]
        assert tools["test"].confirm is False and tools["notes"].confirm is False
        assert tools["test"].run("echo", {"text": "hi"}) == {"result": "hi"}
    finally:
        close_tools(tools)


def test_connection_lifecycle_and_notifier(tmp_path):
    cfg = {"dummy": {"source": DUMMY_SOURCE, "greeting": "hi"}}
    connections = load_connections(cfg, tmp_path)
    notifier = Notifier()
    tools = load_tools({"notes": {"source": NOTES_SOURCE}}, tmp_path, tmp_path, notifier, ["private"])
    setup_connections(connections, cfg, tmp_path, config=None, protocol=None, agent=None, tools=tools,
                      notifier=notifier)
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
        load_connections({"dummy": {"source": DUMMY_SOURCE, "port": 1}}, tmp_path)


def test_notifier_survives_failing_channel():
    got = []
    n = Notifier()
    n.add(lambda t, b: 1 / 0)
    n.add(lambda t, b: got.append(t))
    n("title", "body")
    assert got == ["title"]


def test_git_sources_go_to_extensions_folder(tmp_path):
    assert source_dir(tmp_path, "tools", "x", "https://github.com/a/b.git").parts[-3:] == ("extensions", "tools", "x")
    assert source_dir(tmp_path / "agent", "tools", "x", "../t") == (tmp_path / "t").resolve()


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _commit(origin, message):
    _git("add", "-A", cwd=origin)
    _git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", message, cwd=origin)


def test_install_clones_and_updates_a_git_source(tmp_path, monkeypatch):
    origin = tmp_path / "origin"  # a repo whose top level is the tool, as a tool repo on GitHub would be
    shutil.copytree(FAKE_EXTENSIONS / "tools/notes", origin, ignore=shutil.ignore_patterns("__pycache__"))
    _git("init", "-q", "-b", "main", cwd=origin)
    _commit(origin, "notes tool")
    monkeypatch.setattr("localagent.extensions.EXTENSIONS_DIR", tmp_path / "ext")  # not the repo's extensions/
    d = write_agent_yaml(tmp_path / "a", installables=f"tools:\n  notes:\n    source: file://{origin.as_posix()}\n")
    config = load_config(d)

    pip_calls = []
    assert install(config, log=lambda m: None, pip=pip_calls.append) == 0
    assert (tmp_path / "ext/tools/notes/__init__.py").is_file() and pip_calls == []

    (origin / "requirements.txt").write_text("nothing-real\n")
    _commit(origin, "add requirements")
    assert install(config, log=lambda m: None, pip=pip_calls.append) == 0  # second run updates in place
    assert pip_calls == [["-r", str(tmp_path / "ext/tools/notes/requirements.txt")]]
    assert "notes" in load_tools(config.installables.tools, d, tmp_path / "data", None, ["private"])


def test_install_mcp_runs_pip_then_checks_the_server(tmp_path):
    d = write_agent_yaml(tmp_path / "a", installables=(f"tools:\n  test:\n    mcp: [python, {MCP_SERVER}]\n"
                                                      "    pip: some-package\n    actions: [echo, where]\n"))
    logs, pip_calls = [], []
    assert install(load_config(d), log=logs.append, pip=pip_calls.append) == 0
    assert pip_calls == [["some-package"]]
    assert any("the model sees 2 action(s): echo, where" in line for line in logs)


def test_install_reports_broken_entries(tmp_path):
    d = write_agent_yaml(tmp_path / "a", installables="tools:\n  weather:\n    source: ./nowhere\n")
    with pytest.raises(ExtensionError, match="no __init__.py"):
        install(load_config(d), log=lambda m: None, pip=lambda r: None)
    d = write_agent_yaml(tmp_path / "b", installables=f"tools:\n  t:\n    mcp: [python, {MCP_SERVER}]\n"
                                                      "    actions: [nope]\n")
    with pytest.raises(ExtensionError, match="nope"):
        install(load_config(d), log=lambda m: None, pip=lambda r: None)


def test_describe(tmp_path):
    installables = (f"tools:\n  notes:\n    source: {NOTES_SOURCE}\n  web:\n    mcp: [python, -m, x]\n"
                    "  other:\n    source: https://example.com/x.git\n")
    text = describe(load_config(write_agent_yaml(tmp_path / "a", installables=installables)))
    assert "MCP: python -m x" in text and "[not installed: run install]" in text
    assert "connections:\n  (none)" in text


def test_follow_setting(tmp_path):
    cfg = {"notes": {"source": NOTES_SOURCE, "follow": {"list": "delete"}}}
    tools = load_tools(cfg, tmp_path, tmp_path / "data", None, ["private", "shared"])
    assert tools["notes"].follow == {"list": "delete"}


@pytest.mark.parametrize("follow, fragment", [
    ({"nope": "delete"}, "nope"),
    ({"list": "nope"}, "nope"),
    ({"list": "add"}, "exactly one"),  # add needs text and due: the agent can't fill in both from a link
])
def test_follow_errors(tmp_path, follow, fragment):
    with pytest.raises(ExtensionError, match=fragment):
        load_tools({"notes": {"source": NOTES_SOURCE, "follow": follow}}, tmp_path, tmp_path / "data", None,
                   ["private", "shared"])
