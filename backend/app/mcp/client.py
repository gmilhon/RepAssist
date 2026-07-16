"""Stub MCP client.

Placeholder for a real Model Context Protocol client. In production this would
open a transport (stdio / streamable-HTTP / SSE) to one or more MCP servers,
discover their tools via `tools/list`, and invoke them via `tools/call`.

For the prototype we register in-process *stub servers* and dispatch tool calls
to them synchronously, returning the same shape a real `tools/call` result would
carry. Swapping this for a real client later means keeping `call_tool()`'s
signature and moving the dispatch onto an actual transport.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Callable

# An MCP tool takes a JSON-object argument map and returns a JSON-object result.
ToolFn = Callable[[dict], dict]


class MCPClient:
    """Minimal in-process stand-in for an MCP client."""

    def __init__(self) -> None:
        self._tools: dict[tuple[str, str], ToolFn] = {}

    def register_tool(self, server: str, tool: str, fn: ToolFn) -> None:
        """Register a stub server's tool. Real clients discover these remotely."""
        self._tools[(server, tool)] = fn

    def list_tools(self, server: str) -> list[str]:
        return [tool for (srv, tool) in self._tools if srv == server]

    def call_tool(self, server: str, tool: str, arguments: dict | None = None) -> dict:
        key = (server, tool)
        if key not in self._tools:
            raise KeyError(f"MCP tool not found: {server}/{tool}")
        return self._tools[key](arguments or {})


@lru_cache
def get_mcp_client() -> MCPClient:
    """Singleton client with the prototype's stub servers registered."""
    client = MCPClient()
    from . import jira_stub, news_stub, orders_stub, ost_stub, queue_stub, system_stub, tickets_stub

    orders_stub.register(client)
    tickets_stub.register(client)
    system_stub.register(client)
    news_stub.register(client)
    ost_stub.register(client)
    jira_stub.register(client)
    queue_stub.register(client)
    return client
