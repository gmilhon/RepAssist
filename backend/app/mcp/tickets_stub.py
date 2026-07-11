"""Stub 'Ticketing' MCP server.

Represents the Tier 1/2 ticketing system (the ServiceNow replacement) exposed
over MCP. Its `get_open_tickets` tool returns the rep's currently-open tickets as
an **A2UI element** the chat renders as a card — a companion to the orders server.

Mock data only. Replace `_OPEN` (and the helpers) with a real MCP `tools/call`
against the ticket store when available.
"""
from __future__ import annotations

from .client import MCPClient

# Ticket status → semantic tone the client maps to a colour.
_STATUS_TONE = {
    "open":      "danger",   # unclaimed, needs attention
    "in_review": "warn",     # claimed / in progress
}

_STATUS_LABEL = {
    "open":      "Open",
    "in_review": "In review",
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


# Deterministic open-tickets fixture for the rep, most-recent first.
# (ticket_id, summary, intent, priority, status, minutes_ago)
_OPEN = [
    ("TCK-4F2A9C1B",
     "Customer disputing a $99 restocking fee charged after an in-store return.",
     "billing", "high", "open", 95),
    ("TCK-8D71E0A3",
     "Line still shows no service 24h after eSIM swap — carrier port may be stuck.",
     "activation", "high", "in_review", 310),
    ("TCK-1C6B44F9",
     "New upgrade order blocked by a stalled prior order; needs a manual release.",
     "pending_order", "normal", "open", 1400),
    ("TCK-9A03D5E7",
     "Customer requesting a goodwill credit for a multi-day service outage.",
     "occ", "normal", "in_review", 1600),
    ("TCK-2E5F8B10",
     "Rep asking how to rename the watch face on a customer's smartwatch.",
     "other", "low", "open", 3100),
]


def get_open_tickets(arguments: dict) -> dict:
    """MCP tool: the rep's open tickets, returned as an A2UI element."""
    rep_id = arguments.get("rep_id", "rep.demo")  # noqa: F841 — scoping arg (mock ignores)
    limit = int(arguments.get("limit", 6))

    tickets = [
        {
            "ticket_id":    tid,
            "summary":      summary,
            "intent":       intent,
            "priority":     priority,          # high | normal | low
            "status":       status,            # open | in_review
            "status_label": _STATUS_LABEL.get(status, status),
            "status_tone":  _tone(status),     # ok | warn | info | danger → colour
            "age_label":    _ago_label(minutes),
            "prompt":       f"Give me a recap and next steps for ticket {tid}: {summary}",
        }
        for (tid, summary, intent, priority, status, minutes) in _OPEN[:limit]
    ]

    return {
        "elements": [
            {
                "type": "open_tickets",
                "title": "Your open tickets",
                "subtitle": "Tickets assigned to you that still need attention",
                "tickets": tickets,
            }
        ]
    }


def register(client: MCPClient) -> None:
    client.register_tool("tickets", "get_open_tickets", get_open_tickets)
