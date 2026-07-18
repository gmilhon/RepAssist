"""Store check-in queue: front-of-store customer intake + the rep-facing queue view.

Deliberately NOT routed through the LangGraph orchestrator — check-in captures
a fixed set of fields (visit reason + name/phone), it isn't an open-ended
problem for triage to classify. "Assist" claims an entry and hands off into
the normal chat flow (see ChatWidget's queue-assist handler), which is where
issue diagnosis actually happens.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, model_validator

from ..schemas import VisitReason
from ..store import db

router = APIRouter(prefix="/api/queue", tags=["queue"])


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
