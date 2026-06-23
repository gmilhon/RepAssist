"""Tier 1/2 human-in-the-loop ticket workflow (replaces ServiceNow)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..store import db
from ..store.models import Ticket

router = APIRouter(prefix="/api/tickets", tags=["tickets"])


class ClaimRequest(BaseModel):
    agent: str


class ResolveRequest(BaseModel):
    resolution_notes: str
    root_cause_category: str
    # The capability/agent/skill the dev team should build or improve so the
    # assistant can handle this class of issue next time.
    recommended_capability: str
    gap_type: str  # see store.models.GapType
    resolved_by: str
    close_only: bool = False  # True = closed with no capability gap to build


@router.get("")
def list_tickets(status: Optional[str] = None) -> list[Ticket]:
    return db.list_tickets(status)


@router.get("/{ticket_id}")
def get_ticket(ticket_id: str) -> Ticket:
    ticket = db.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    return ticket


@router.post("/{ticket_id}/claim")
def claim(ticket_id: str, req: ClaimRequest) -> Ticket:
    ticket = db.claim_ticket(ticket_id, req.agent)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    return ticket


@router.post("/{ticket_id}/resolve")
def resolve(ticket_id: str, req: ResolveRequest) -> Ticket:
    ticket = db.resolve_ticket(
        ticket_id,
        resolution_notes=req.resolution_notes,
        root_cause_category=req.root_cause_category,
        recommended_capability=req.recommended_capability,
        gap_type=req.gap_type,
        resolved_by=req.resolved_by,
        close_only=req.close_only,
    )
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    return ticket
