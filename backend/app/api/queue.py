"""Store check-in queue: front-of-store customer intake + the rep-facing queue view.

Deliberately NOT routed through the LangGraph orchestrator — check-in captures
a fixed set of fields (visit reason + name/phone), it isn't an open-ended
problem for triage to classify. "Assist" claims an entry and hands off into
the normal chat flow (see ChatWidget's queue-assist handler), which is where
issue diagnosis actually happens.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, model_validator

from ..schemas import VISIT_REASON_LABELS, VisitReason
from ..store import db
from ..store.models import QueueEntry

router = APIRouter(prefix="/api/queue", tags=["queue"])


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _reason_label(reason: str) -> str:
    try:
        return VISIT_REASON_LABELS[VisitReason(reason)]
    except ValueError:
        return reason.replace("_", " ").title()


def _elapsed_label(minutes: int) -> str:
    """'4m', '1h 20m' — a compact 'how long ago / from now' label."""
    minutes = max(0, minutes)
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes}m"
    hours, mins = divmod(minutes, 60)
    return f"{hours}h {mins}m" if mins else f"{hours}h"


class CheckInRequest(BaseModel):
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    reason: str  # VisitReason value
    account_id: Optional[str] = None   # known customer account, if looked up at check-in
    order_id: Optional[str] = None     # known customer order, if looked up at check-in

    @model_validator(mode="after")
    def _require_identifier(self) -> "CheckInRequest":
        if not (self.customer_name or "").strip() and not (self.customer_phone or "").strip():
            raise ValueError("Provide the customer's name or phone number.")
        return self


class AssistRequest(BaseModel):
    rep_id: str
    thread_id: Optional[str] = None


@router.post("/checkin")
def check_in(req: CheckInRequest) -> dict:
    try:
        reason = VisitReason(req.reason).value
    except ValueError:
        raise HTTPException(422, f"Unknown visit reason: {req.reason}")
    entry, position = db.create_queue_entry(
        customer_name=(req.customer_name or "").strip() or None,
        customer_phone=(req.customer_phone or "").strip() or None,
        reason=reason,
        account_id=(req.account_id or "").strip().upper() or None,
        order_id=(req.order_id or "").strip().upper() or None,
    )
    return {"entry": entry, "queue_position": position}


@router.post("/{entry_id}/assist")
def assist(entry_id: str, req: AssistRequest) -> dict:
    entry = db.assist_queue_entry(entry_id, req.rep_id, req.thread_id)
    if not entry:
        raise HTTPException(404, "Queue entry not found")
    return {"entry": entry}


def _serialize(e: QueueEntry, now: datetime) -> dict:
    """One live-queue row: identity + the time labels each bucket cares about."""
    created = _aware(e.created_at)
    started = _aware(e.started_at) if e.started_at else None
    scheduled = _aware(e.scheduled_at) if e.scheduled_at else None
    row = {
        "id": e.id,
        "customer_name": e.customer_name,
        "customer_phone": e.customer_phone,
        "reason": e.reason,
        "reason_label": _reason_label(e.reason),
        "status": e.status,
        "account_id": e.account_id,
        "order_id": e.order_id,
        "assigned_rep_id": e.assigned_rep_id,
        # For walk-ins / ISPU: how long they've been in this state.
        "wait_label": _elapsed_label(int((now - (started or created)).total_seconds() // 60)),
    }
    if scheduled:
        row["scheduled_at"] = scheduled.isoformat()
        row["scheduled_label"] = scheduled.astimezone().strftime("%-I:%M %p")
        row["eta_label"] = "in " + _elapsed_label(int((scheduled - now).total_seconds() // 60))
    return row


@router.get("/live")
def live_queue() -> dict:
    """Full floor snapshot for the Live Queue indicator: waiting, being assisted,
    in-store pickups (to-pick + ready), and today's upcoming appointments."""
    now = datetime.now(timezone.utc)
    snap = db.live_queue_snapshot()
    out = {k: [_serialize(e, now) for e in v] for k, v in snap.items()}
    out["counts"] = {
        "waiting": len(out["waiting"]),
        "assisting": len(out["assisting"]),
        "ispu_to_pick": len(out["ispu_to_pick"]),
        "ispu_ready": len(out["ispu_ready"]),
        "ispu": len(out["ispu_to_pick"]) + len(out["ispu_ready"]),
        "appointments": len(out["appointments"]),
    }
    return out
