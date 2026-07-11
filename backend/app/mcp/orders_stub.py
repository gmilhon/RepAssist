"""Stub 'Orders' MCP server.

Represents an external order-management system exposed over MCP. Its tools return
**A2UI elements** — structured UI component specs (not prose) that the chat client
renders as rich, interactive cards. This keeps the agent↔UI contract explicit:
the tool decides *what* to show; the client decides *how* to render it.

Everything here is mock data. Replace `_RECENT` (and the tone/label helpers) with
a real MCP `tools/call` when the orders service is available.
"""
from __future__ import annotations

from .client import MCPClient

# Status → semantic tone the client maps to a colour.
_STATUS_TONE = {
    "Activation Pending":   "warn",
    "Carrier Port Pending": "info",
    "Blocked":              "danger",
    "Credit Hold":          "danger",
    "Upgrade Pending":      "warn",
    "Completed":            "ok",
    "Active":               "ok",
}


def _tone(status: str) -> str:
    return _STATUS_TONE.get(status, "info")


def _ago_label(minutes: int) -> str:
    """Human 'time ago' label from minutes."""
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    return "Yesterday" if days == 1 else f"{days}d ago"


# Deterministic recent-orders fixture, most-recent first.
# (order_id, type, status, device, line, account_id, customer, minutes_ago, prompt)
# Prompts embed both order_id and account_id so the triage regex can reliably
# extract them without needing to prompt the rep for context.
_RECENT = [
    ("ACT-1001", "New Activation", "Activation Pending", "iPhone 17 Pro", "(555) 010-1001",
     "AC-3001", "J. Rivera", 18,
     "Order ACT-1001 on account AC-3001 is stuck in activation — the SIM won't activate"),
    ("ORD-2002", "Upgrade", "Blocked", "Galaxy S26", "(555) 010-2002",
     "AC-3003", "J. Rivera", 74,
     "Order ORD-2002 on account AC-3003 is blocking the customer's new upgrade order"),
    ("ACT-1002", "New Activation", "Carrier Port Pending", "Pixel 10", "(555) 010-1002",
     "AC-3002", "M. Okafor", 156,
     "Order ACT-1002 on account AC-3002 has a carrier port that hasn't completed yet"),
    ("ORD-2003", "New Line", "Credit Hold", "iPhone 17", "(555) 010-2003",
     "AC-3010", "D. Thompson", 320,
     "Order ORD-2003 on account AC-3010 is on a credit hold — the customer can't add their new line"),
    ("ORD-2010", "Upgrade", "Completed", "iPhone 17 Pro", "(555) 010-2010",
     "AC-5001", "K. Patel", 1500,
     "Give me a recap of completed order ORD-2010 on account AC-5001"),
]


def get_recent_orders(arguments: dict) -> dict:
    """MCP tool: recent orders for a rep, returned as an A2UI element."""
    rep_id = arguments.get("rep_id", "rep.demo")  # noqa: F841 — scoping arg (mock ignores)
    limit = int(arguments.get("limit", 6))

    orders = [
        {
            "order_id":     oid,
            "order_type":   otype,
            "status":       status,
            "status_tone":  _tone(status),
            "device":       device,
            "line":         line,
            "account_id":   account_id,
            "customer":     customer,
            "opened_label": _ago_label(minutes),
            "prompt":       prompt,
        }
        for (oid, otype, status, device, line, account_id, customer, minutes, prompt)
        in _RECENT[:limit]
    ]

    return {
        "elements": [
            {
                "type": "recent_orders",
                "title": "Recent orders",
                "subtitle": "Pick up where you left off — customers you've serviced recently",
                "orders": orders,
            }
        ]
    }


def register(client: MCPClient) -> None:
    client.register_tool("orders", "get_recent_orders", get_recent_orders)
