"""Sync MCP client. One long-lived stdio session to app.mcp_server on a background loop.
If the MCP subprocess cannot start, calls fall back to in-process execution and the
transport is reported honestly as 'direct'."""
import asyncio
import json
import os
import sys
import threading
from typing import Any, Dict, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


class ToolFailure(Exception):
    def __init__(self, message: str, error_type: str = "ToolError", details: Optional[dict] = None):
        super().__init__(message)
        self.error_type = error_type
        self.details = details or {}


class McpClient:
    def __init__(self) -> None:
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._session: Optional[ClientSession] = None
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._start_error: Optional[str] = None
        self._tool_names: list = []

    def _run_loop(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        loop.run_until_complete(self._main())

    async def _main(self) -> None:
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "app.mcp_server"], cwd=BACKEND_DIR, env=dict(os.environ))
        try:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    self._session = session
                    self._tool_names = [t.name for t in (await session.list_tools()).tools]
                    self._ready.set()
                    await asyncio.Event().wait()  # keep session open
        except Exception as exc:
            self._start_error = f"{type(exc).__name__}: {exc}"
            self._ready.set()

    def start(self) -> bool:
        with self._lock:
            if self._loop is None:
                threading.Thread(target=self._run_loop, daemon=True).start()
        self._ready.wait(timeout=30)
        return self._session is not None

    @property
    def tool_names(self) -> list:
        return list(self._tool_names)

    @property
    def start_error(self) -> Optional[str]:
        return self._start_error

    def call(self, name: str, **args: Any) -> Dict[str, Any]:
        """Returns {'data': ..., 'transport': 'mcp'|'direct'}; raises ToolFailure on ok=False."""
        if self.start():
            fut = asyncio.run_coroutine_threadsafe(self._session.call_tool(name, args), self._loop)
            res = fut.result(timeout=60)
            text = res.content[0].text if res.content else "{}"
            envelope = json.loads(text)
            transport = "mcp"
        else:
            envelope = self._direct(name, args)
            transport = "direct"
        if not envelope.get("ok"):
            raise ToolFailure(envelope.get("error", "unknown error"), envelope.get("error_type", "ToolError"),
                              envelope.get("details"))
        return {"data": envelope["data"], "transport": transport}

    @staticmethod
    def _direct(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        from app import mcp_server
        fn = getattr(mcp_server, name)
        return fn(**args)


client = McpClient()
