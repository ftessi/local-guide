"""Use any MCP server (https://modelcontextprotocol.io) as a tool: files, web, terminal, and thousands more.

The server runs as a child process for as long as the agent runs. Its actions go through the same guard as
any other tool (scope checks, audit, compartment), and their results always go back to the model.
"""
import asyncio
import atexit
import logging
import shutil
import sys
import threading
from datetime import timedelta
from pathlib import Path

from localagent.agent.tools.base import Action, Tool

log = logging.getLogger(__name__)
JSON_TYPES = {"string": "str", "integer": "int", "number": "number", "boolean": "bool", "array": "list",
              "object": "object"}
START_TIMEOUT = 180  # seconds; the first `npx -y ...` run downloads the server


class McpError(RuntimeError):
    """The MCP server could not start, or reported an error."""


def resolve_command(command: list[str]) -> list[str]:
    """`python` means this agent's Python (its venv); others are looked up on PATH (npx -> npx.cmd on Windows)."""
    if not command:
        raise McpError("mcp: command is empty")
    exe = sys.executable if command[0] in ("python", "python3") else shutil.which(command[0])
    if exe is None:
        hint = " Install Node.js (it provides npx)." if command[0] in ("npx", "node") else ""
        raise McpError(f"'{command[0]}' was not found on PATH.{hint}")
    return [exe, *command[1:]]


def _short(text: str | None, limit: int = 160) -> str:
    """MCP descriptions are written for big models; small ones get the first line."""
    line = next((ln.strip() for ln in (text or "").splitlines() if ln.strip()), "")
    return line if len(line) <= limit else line[:limit].rsplit(" ", 1)[0] + "…"


def _param_type(spec: dict) -> str:
    typ = spec.get("type")
    if isinstance(typ, list):
        typ = next((t for t in typ if t != "null"), None)
    return JSON_TYPES.get(typ, "str")


def actions_from_mcp(mcp_tools, only=(), fixed_args=None, describe=None) -> dict[str, Action]:
    """MCP tool list -> our actions. `only` picks which ones the model sees; `fixed_args` are filled in for it."""
    fixed_args, describe = fixed_args or {}, describe or {}
    by_name = {t.name: t for t in mcp_tools}
    missing = [n for n in only if n not in by_name]
    if missing:
        raise McpError(f"no action(s) {', '.join(missing)}. It offers: {', '.join(by_name)}")
    actions = {}
    for name in (only or by_name):
        schema = by_name[name].inputSchema or {}
        required = set(schema.get("required", []))
        params = {p: _param_type(spec) for p, spec in schema.get("properties", {}).items() if p not in fixed_args}
        actions[name] = Action(describe.get(name) or _short(by_name[name].description) or name, params,
                               kind="read", optional=frozenset(p for p in params if p not in required))
    return actions


class McpTool(Tool):
    def __init__(self, name: str, command: list[str], *, cwd: Path | None = None, env: dict | None = None,
                 only=(), fixed_args: dict | None = None, describe: dict | None = None,
                 max_result_chars: int = 4000, timeout: float = 60):
        self.name, self.command, self.cwd, self.env = name, command, cwd, env or {}
        self.only, self.fixed_args, self.describe = tuple(only), dict(fixed_args or {}), dict(describe or {})
        self.max_result_chars, self.timeout = max_result_chars, timeout
        self.actions = {}
        self._loop = self._session = self._stop = self._error = None
        self._ready = threading.Event()

    def setup(self, data_dir: Path, notify) -> None:
        self.command = resolve_command(self.command)
        Path(data_dir).mkdir(parents=True, exist_ok=True)
        self._errlog = (Path(data_dir) / "server.log").open("a", encoding="utf-8")  # the server's own messages
        self._thread = threading.Thread(target=self._thread_main, name=f"mcp-{self.name}", daemon=True)
        self._thread.start()
        if not self._ready.wait(START_TIMEOUT):
            raise McpError(f"MCP server for '{self.name}' did not start within {START_TIMEOUT}s")
        if self._error is not None:
            raise McpError(f"MCP server for '{self.name}' failed to start: {self._error}. "
                           f"Details: {Path(data_dir) / 'server.log'}") from self._error
        try:
            self.actions = actions_from_mcp(self._mcp_tools, self.only, self.fixed_args, self.describe)
        except McpError as e:
            self.close()
            raise McpError(f"Tool '{self.name}': {e}") from None
        atexit.register(self.close)

    def _thread_main(self) -> None:
        self._loop = asyncio.new_event_loop()
        try:
            self._loop.run_until_complete(self._serve())
        finally:
            self._errlog.close()

    async def _serve(self) -> None:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import get_default_environment, stdio_client

        params = StdioServerParameters(command=self.command[0], args=self.command[1:],
                                       env={**get_default_environment(), **self.env},
                                       cwd=str(self.cwd) if self.cwd else None)
        self._stop = asyncio.Event()
        try:
            async with stdio_client(params, errlog=self._errlog) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    self._mcp_tools = (await session.list_tools()).tools
                    self._session = session
                    self._ready.set()
                    await self._stop.wait()
        except BaseException as e:  # anyio may wrap the cause in an exception group
            while getattr(e, "exceptions", None):
                e = e.exceptions[0]
            self._error = e
        finally:
            self._session = None
            self._ready.set()

    def run(self, action: str, args: dict) -> dict:
        if self._session is None:
            raise McpError(f"MCP server for '{self.name}' is not running (see data/{self.name}/server.log)")
        call = self._session.call_tool(action, {**args, **self.fixed_args},
                                       read_timeout_seconds=timedelta(seconds=self.timeout))
        result = asyncio.run_coroutine_threadsafe(call, self._loop).result(self.timeout + 5)
        text = "\n".join(getattr(c, "text", f"[{getattr(c, 'type', 'content')}]") for c in result.content)
        if result.isError:
            raise McpError(text.strip() or "the server reported an error")
        if len(text) > self.max_result_chars:
            text = text[:self.max_result_chars] + f"\n…[cut at {self.max_result_chars} characters]"
        return {"result": text}

    def close(self) -> None:
        """Stops the server and waits for it, so its process and log file are released."""
        if self._loop is not None and self._stop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._stop.set)
        thread = getattr(self, "_thread", None)
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=10)
