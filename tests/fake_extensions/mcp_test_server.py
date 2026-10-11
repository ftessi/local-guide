"""A minimal MCP server for the core tests: run with `python tests/fake_extensions/mcp_test_server.py`."""
import os

from mcp.server.fastmcp import FastMCP

server = FastMCP("test")


@server.tool()
def echo(text: str, shout: bool = False) -> str:
    """Repeat the text back.

    A second paragraph that small models never need to see."""
    return text.upper() if shout else text


@server.tool()
def where(label: str) -> str:
    """Report the working directory and an environment variable."""
    return f"{label}:{os.getcwd()}|{os.environ.get('TEST_FLAG', '')}"


@server.tool()
def broken() -> str:
    """Always fails."""
    raise ValueError("this tool is broken")


@server.tool()
def long_text() -> str:
    """Return a long text."""
    return "x" * 10000


if __name__ == "__main__":
    server.run()
