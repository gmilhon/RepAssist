"""'Store Queue' MCP server.

Unlike the other stubs (orders, tickets, news) this one isn't fronting mock
external-system data — it reads the app's own `queue_entries` table, populated
by the "Check In" CTA. It stays an MCP tool anyway so "View Queue" renders
through the same A2UI pipeline as every other card: the tool decides *what*
to show, the client decides *how*.
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..schemas import VISIT_REASON_LABELS, VisitReason
from ..store import db
from .client import MCPClient


def _ago_label(minutes: int) -> str:
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h {minutes % 60}m"
    return f"{hours // 24}d"


def _aware(dt: datetime) -> datetime:
    # SQLite round-trips lose tzinfo for ORM-written datetimes; all our naive
    # datetimes are UTC by construction (see models._now).
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _reason_label(reason: str) -> str:
    try:
        return VISIT_REASON_LABELS[VisitReason(reason)]
    except ValueError:
        return reason.replace("_", " ").title()


def get_queue(arguments: dict) -> dict:
    """MCP tool: the current store check-in queue, as an A2UI element."""
    limit = int(arguments.get("limit", 20))
    now = datetime.now(timezone.utc)

    entries = [
        {
            "id": e.id,
            "customer_name": e.customer_name,
            "customer_phone": e.customer_phone,
            "reason": e.reason,
            "reason_label": _reason_label(e.reason),
            "status": e.status,  # waiting | in_progress
            "wait_label": _ago_label(int((now - _aware(e.created_at)).total_seconds() // 60)),
            "assigned_rep_id": e.assigned_rep_id,
            "prompt": (
                f"I'm now assisting {e.customer_name or e.customer_phone or 'the customer'} — "
                f"they're here for: {_reason_label(e.reason)}."
            ),
        }
        for e in db.list_queue(limit=limit)
    ]

    waiting = sum(1 for e in entries if e["status"] == "waiting")
    return {
        "elements": [
            {
                "type": "queue",
                "title": "Store queue",
                "subtitle": f"{waiting} waiting" if waiting else "No one waiting right now",
                "entries": entries,
            }
        ]
    }


def register(client: MCPClient) -> None:
    client.register_tool("queue", "get_queue", get_queue)
