"""Stub 'JIRA' MCP server — defect tracking for the Production Monitor.

When AI analysis of escalated-ticket inflow finds a **non-critical** recurring
theme, the monitor files a defect here. The stub mirrors the tool shape a real
MCP JIRA integration would expose (`create_issue` / `list_issues` / `get_issue`)
and persists defects in SQLite so the board survives restarts. Swapping in a
real JIRA MCP server later means keeping these tool contracts and pointing
`MCPClient` at a real transport.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Session, select

from ..store.db import _engine
from ..store.models import JiraDefect
from .client import MCPClient

_PROJECT = "REP"
_KEY_SEED = 1400  # first defect is REP-1401, for board realism
_BROWSE_BASE = "https://jira.example.com/browse"


def _next_key(session: Session) -> str:
    count = len(session.exec(select(JiraDefect)).all())
    return f"{_PROJECT}-{_KEY_SEED + count + 1}"


def _to_dict(d: JiraDefect) -> dict:
    return {
        "key": d.key,
        "url": f"{_BROWSE_BASE}/{d.key}",
        "summary": d.summary,
        "description": d.description,
        "priority": d.priority,
        "labels": d.labels or [],
        "status": d.status,
        "issue_id": d.issue_id,
        "ticket_ids": d.ticket_ids or [],
        "created_at": d.created_at.isoformat() if d.created_at else None,
    }


def create_issue(args: dict) -> dict:
    """Create a defect. args: summary, description, priority?, labels?, issue_id?, ticket_ids?"""
    with Session(_engine) as s:
        defect = JiraDefect(
            key=_next_key(s),
            created_at=datetime.now(timezone.utc),
            summary=(args.get("summary") or "")[:255],
            description=args.get("description") or "",
            priority=args.get("priority") or "Medium",
            labels=args.get("labels") or [],
            status="Open",
            issue_id=args.get("issue_id"),
            ticket_ids=args.get("ticket_ids") or [],
        )
        s.add(defect)
        s.commit()
        s.refresh(defect)
        return _to_dict(defect)


def attach_ticket(args: dict) -> dict:
    """Attach another originating ticket to an existing defect. args: key, ticket_id, note?"""
    with Session(_engine) as s:
        defect = s.get(JiraDefect, args.get("key") or "")
        if not defect:
            return {"error": "not_found"}
        ticket_id = args.get("ticket_id")
        ids = list(defect.ticket_ids or [])
        if ticket_id and ticket_id not in ids:
            ids.append(ticket_id)
        defect.ticket_ids = ids
        note = args.get("note")
        if note:
            defect.description = (defect.description or "") + f"\n\nh3. Also reported by {ticket_id}\n{note}"
        s.add(defect)
        s.commit()
        s.refresh(defect)
        return _to_dict(defect)


def list_issues(args: dict) -> dict:
    """List defects on the board, newest first. args: limit?"""
    limit = int(args.get("limit") or 50)
    with Session(_engine) as s:
        rows = s.exec(
            select(JiraDefect).order_by(JiraDefect.created_at.desc()).limit(limit)
        ).all()
        return {"issues": [_to_dict(d) for d in rows], "total": len(rows)}


def get_issue(args: dict) -> dict:
    """Fetch one defect by key. args: key"""
    with Session(_engine) as s:
        d = s.get(JiraDefect, args.get("key") or "")
        if not d:
            return {"error": "not_found"}
        return _to_dict(d)


def register(client: MCPClient) -> None:
    client.register_tool("jira", "create_issue", create_issue)
    client.register_tool("jira", "list_issues", list_issues)
    client.register_tool("jira", "get_issue", get_issue)
    client.register_tool("jira", "attach_ticket", attach_ticket)
