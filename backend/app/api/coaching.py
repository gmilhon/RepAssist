"""Coaching: recent graded Live Listen visits + GenAI coaching per visit.

The Coaching tile lists recently assisted customers with their Playbook score;
selecting one returns a GenAI recommendation on how the rep could have better
met the Playbook. Read-only over listen-session data — no mutations.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from .. import llm
from ..schemas import VISIT_REASON_LABELS, VisitReason
from ..store import db
from ..store.models import ListenSession

router = APIRouter(prefix="/api/coaching", tags=["coaching"])


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _ago_label(dt: datetime) -> str:
    minutes = int((datetime.now(timezone.utc) - _aware(dt)).total_seconds() // 60)
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    return f"{hours // 24}d ago"


def _reason_label(reason: str) -> str:
    try:
        return VISIT_REASON_LABELS[VisitReason(reason)]
    except ValueError:
        return reason.replace("_", " ").title()


def _active_guidelines() -> list[dict]:
    return [
        {"id": g.id, "category": g.category, "text": g.text}
        for g in db.list_playbook_guidelines(active_only=True)
    ]


@router.get("/recent")
def recent(limit: int = 12) -> dict:
    """Recent graded visits as an A2UI 'coaching' card."""
    sessions = db.list_recent_graded_sessions(limit=limit)
    entries = [
        {
            "session_id": s.id,
            "customer_name": s.customer_name or s.customer_phone or "Customer",
            "reason_label": _reason_label(s.reason),
            "stars": s.playbook_score or 0,
            "when_label": _ago_label(s.ended_at or s.created_at),
            "has_coaching": bool(s.coaching),
        }
        for s in sessions
    ]
    return {
        "elements": [
            {
                "type": "coaching",
                "title": "Coaching",
                "subtitle": (
                    f"{len(entries)} recent visit{'s' if len(entries) != 1 else ''} graded"
                    if entries else "No graded visits yet"
                ),
                "entries": entries,
            }
        ]
    }


@router.post("/{session_id}")
def recommend(session_id: str) -> dict:
    """Return (generating on first request) the coaching recommendation for a visit."""
    session: ListenSession | None = db.get_listen_session(session_id)
    if not session:
        raise HTTPException(404, "Listen session not found")
    coaching = session.coaching
    if coaching is None:
        coaching = llm.generate_coaching(
            session.transcript or [],
            session.suggestions or [],
            session.eligibility or {},
            _active_guidelines(),
            session.playbook_grade,
            thread_id=session.thread_id,
            rep_id=session.rep_id,
        ).model_dump()
        db.save_listen_coaching(session_id, coaching)
    return {
        "session_id": session_id,
        "customer_name": session.customer_name or session.customer_phone or "Customer",
        "stars": session.playbook_score or 0,
        "grade": session.playbook_grade,
        "coaching": coaching,
    }
