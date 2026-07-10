"""Persistence models for the human-in-the-loop ticket queue (ServiceNow
replacement) and the feedback that drives continuous improvement.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlmodel import JSON, Column, Field, SQLModel


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ticket_id() -> str:
    return "TCK-" + uuid.uuid4().hex[:8].upper()


class TicketStatus(str, Enum):
    OPEN = "open"            # created by the assistant, unassigned
    IN_REVIEW = "in_review"  # claimed by a Tier 1/2 agent
    RESOLVED = "resolved"    # fixed + feedback captured
    CLOSED = "closed"        # closed without a capability gap


class GapType(str, Enum):
    """Why the assistant could not resolve it — the signal the dev team needs."""

    MISSING_AGENT = "missing_agent"          # no agent exists for this problem
    AGENT_FAILED = "agent_failed"            # an agent exists but returned wrong/none
    MISSING_KNOWLEDGE = "missing_knowledge"  # KB has no article
    BAD_DATA = "bad_data"                    # upstream/system data issue
    TRAINING = "training"                    # rep education, not a software gap
    NONE = "none"                            # nothing to build; one-off


class Engagement(SQLModel, table=True):
    """One row per assistant interaction (a chat turn or a confirmation),
    captured for operational analytics. This is the source of the KPI dashboard.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=_now)
    thread_id: str
    rep_id: Optional[str] = None
    kind: str = "message"                     # "message" | "confirmation"
    intent: Optional[str] = None
    confidence: Optional[float] = None
    status: str = ""                          # answered | needs_confirmation | escalated
    resolution_status: Optional[str] = None   # resolved | cancelled | escalated | info | proposed
    capability: Optional[str] = None          # which agent/skill handled it
    confirmed: Optional[bool] = None          # for confirmation turns
    ticket_id: Optional[str] = None


class Ticket(SQLModel, table=True):
    id: str = Field(default_factory=_ticket_id, primary_key=True)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    # Context captured at escalation time
    rep_id: Optional[str] = None
    thread_id: Optional[str] = None
    intent: str = "other"
    priority: str = "normal"  # low | normal | high
    summary: str = ""
    order_id: Optional[str] = None
    account_id: Optional[str] = None
    conversation: list = Field(default_factory=list, sa_column=Column(JSON))
    order_context: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    trace: list = Field(default_factory=list, sa_column=Column(JSON))

    status: TicketStatus = Field(default=TicketStatus.OPEN)
    assigned_to: Optional[str] = None

    # --- Filled in by the Tier 1/2 agent on resolution (the feedback loop) ---
    resolution_notes: Optional[str] = None
    root_cause_category: Optional[str] = None
    recommended_capability: Optional[str] = None  # agent/skill the dev team should build/improve
    gap_type: Optional[GapType] = None
    resolved_by: Optional[str] = None
    resolved_at: Optional[datetime] = None


class EmailSubscriber(SQLModel, table=True):
    """Recipients for scheduled/on-demand dashboard email reports."""

    __tablename__ = "email_subscribers"

    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True)
    name: Optional[str] = None
    subscribed_performance: bool = True   # receives Performance dashboard reports
    subscribed_cx: bool = True            # receives CX Monitor reports
    active: bool = True
    created_at: datetime = Field(default_factory=_now)
