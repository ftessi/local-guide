import pytest

from localagent.agent.tools.base import validate_args
from localagent.agent.tools.mcp_bridge import McpError, McpTool, resolve_command
from tests.fakes import FAKE_EXTENSIONS

SERVER = ["python", str(FAKE_EXTENSIONS / "mcp_test_server.py")]


@pytest.fixture
def tool(tmp_path):
    t = McpTool("test", SERVER, cwd=tmp_path, env={"TEST_FLAG": "on"}, max_result_chars=100)
    t.setup(tmp_path / "data", None)
    yield t
    t.close()


def test_actions_mapped_from_server(tool):
    assert set(tool.actions) == {"echo", "where", "broken", "long_text"}
    echo = tool.actions["echo"]
    assert echo.description == "Repeat the text back."  # first line only
    assert echo.params == {"text": "str", "shout": "bool"} and echo.optional == {"shout"}
    assert echo.kind == "read"
    assert validate_args(echo, {"text": "hi"}) == {"text": "hi"}


def test_calls(tool, tmp_path):
    assert tool.run("echo", {"text": "hi", "shout": True}) == {"result": "HI"}
    assert tool.run("where", {"label": "x"})["result"] == f"x:{tmp_path}|on"
    assert tool.run("long_text", {})["result"].endswith("[cut at 100 characters]")
    with pytest.raises(McpError, match="broken"):
        tool.run("broken", {})


def test_only_and_fixed_args(tmp_path):
    t = McpTool("test", SERVER, only=["where"], fixed_args={"label": "pinned"},
                describe={"where": "Say where you are"})
    t.setup(tmp_path, None)
    try:
        assert list(t.actions) == ["where"]
        assert t.actions["where"].params == {} and t.actions["where"].description == "Say where you are"
        assert t.run("where", {})["result"].startswith("pinned:")
    finally:
        t.close()


def test_unknown_action_in_only(tmp_path):
    with pytest.raises(McpError, match="no action.*nope.*It offers: echo"):
        McpTool("test", SERVER, only=["nope"]).setup(tmp_path, None)


def test_server_that_cannot_start(tmp_path):
    with pytest.raises(McpError, match="failed to start"):
        McpTool("test", ["python", "-c", "import sys; sys.exit(3)"]).setup(tmp_path, None)


def test_missing_program():
    with pytest.raises(McpError, match="not found on PATH"):
        resolve_command(["definitely-not-a-program"])
