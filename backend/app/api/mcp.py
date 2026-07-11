"""MCP-backed endpoints for the chat's A2UI (agent-to-UI) elements.

Thin HTTP surface over the stub MCP client. Each endpoint calls an MCP tool and
returns its A2UI element payload for the chat client to render.
"""
from __future__ import annotations

from fastapi import APIRouter, Query

from ..mcp import get_mcp_client

router = APIRouter(prefix="/api/mcp", tags=["mcp"])


@router.get("/recent-orders")
def recent_orders(
    rep_id: str = Query("rep.demo"),
    limit: int = Query(6, ge=1, le=20),
) -> dict:
    """Recent orders for a rep, as an A2UI `recent_orders` element."""
    client = get_mcp_client()
    return client.call_tool("orders", "get_recent_orders", {"rep_id": rep_id, "limit": limit})


@router.get("/open-tickets")
def open_tickets(
    rep_id: str = Query("rep.demo"),
    limit: int = Query(6, ge=1, le=20),
) -> dict:
    """The rep's open tickets, as an A2UI `open_tickets` element."""
    client = get_mcp_client()
    return client.call_tool("tickets", "get_open_tickets", {"rep_id": rep_id, "limit": limit})
