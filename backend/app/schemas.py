"""Shared Pydantic models & enums used across the graph, API and store."""
from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


class Intent(str, Enum):
    ACTIVATION = "activation"
    PENDING_ORDER = "pending_order"
    PROMO = "promo"
    OCC = "occ"
    BILLING = "billing"
    GENERAL = "general"
    SYSTEM = "system"
    OTHER = "other"


# Which capability/agent each intent maps to. Used by the router and, later, by
# the analytics that tells the dev team which capability to invest in.
INTENT_TO_CAPABILITY = {
    Intent.ACTIVATION: "activation-resolver",
    Intent.PENDING_ORDER: "pending-order-resolver",
    Intent.PROMO: "promo-correction-agent",
    Intent.OCC: "occ-credit-agent",
    Intent.BILLING: "billing-knowledge-base",
    Intent.GENERAL: "knowledge-base",
    Intent.SYSTEM: "system-mcp",
    Intent.OTHER: "human-tier-2",
}


class TriageResult(BaseModel):
    """Structured output of the triage/classification step."""

    intent: Literal[
        "activation", "pending_order", "promo", "occ", "billing", "general", "system", "other"
    ] = Field(description="Best-matching issue category for the rep's request.")
    confidence: float = Field(
        description="0.0–1.0 confidence in the chosen intent.", ge=0.0, le=1.0
    )
    order_id: Optional[str] = Field(
        default=None, description="Order id if one is mentioned, else null."
    )
    account_id: Optional[str] = Field(
        default=None, description="Account id if one is mentioned, else null."
    )
    summary: str = Field(description="One sentence restating the rep's problem.")


class ProposedAction(BaseModel):
    """A mutating fix an agent wants to apply — gated behind rep confirmation."""

    service: str
    operation: str
    params: dict = Field(default_factory=dict)
    human_prompt: str = Field(
        description="Plain-language description of the action shown to the rep."
    )


class ExecutiveSummary(BaseModel):
    """AI-generated executive summary for the Performance dashboard."""

    headline: str = Field(description="One sentence describing overall solution health.")
    trending_issues: str = Field(description="2-3 sentences on the most pressing intent/issue trends.")
    containment_escalation: str = Field(description="2-3 sentences on containment rate and escalation trends.")
    backlog_priorities: str = Field(description="2-3 sentences on the top capability investments needed.")


class Resolution(BaseModel):
    status: Literal["resolved", "proposed", "cancelled", "escalated", "info"]
    summary: str
    root_cause: Optional[str] = None
    actions_taken: list[str] = Field(default_factory=list)
    capability: Optional[str] = None  # which agent/skill handled it


# ---- HTTP request/response contracts for the existing agent services ----


class DiagnoseRequest(BaseModel):
    order_id: Optional[str] = None
    account_id: Optional[str] = None
    mtn: Optional[str] = None
    notes: Optional[str] = None


class DiagnoseResponse(BaseModel):
    can_resolve: bool
    root_cause: Optional[str] = None
    summary: str
    proposed_action: Optional[ProposedAction] = None


class ExecuteResponse(BaseModel):
    success: bool
    summary: str
    actions_taken: list[str] = Field(default_factory=list)
