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


class VisitReason(str, Enum):
    """Why a customer is checking in at the store — distinct from `Intent`
    (which classifies a *problem* the rep describes) and from `sales_intent`
    (nse/aal/up, a heuristic tag on resolved conversations). This is captured
    up front, at check-in, before any issue has been discussed."""

    NEW_SERVICE = "new_service"        # New to Verizon / new line
    UPGRADE = "upgrade"                # device or plan upgrade
    HOME = "home"                      # home internet / 5G home
    APPOINTMENT = "appointment"        # scheduled appointment
    PICKUP = "pickup"                  # in-store order pickup
    SUPPORT = "support"                # account / billing / service question
    OTHER = "other"


VISIT_REASON_LABELS = {
    VisitReason.NEW_SERVICE: "New to Verizon",
    VisitReason.UPGRADE: "Upgrade",
    VisitReason.HOME: "Home Internet",
    VisitReason.APPOINTMENT: "Appointment",
    VisitReason.PICKUP: "In-Store Pickup",
    VisitReason.SUPPORT: "Account / Billing Support",
    VisitReason.OTHER: "Something Else",
}


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


class LiveSuggestion(BaseModel):
    """One actionable issue spotted in a live-listen transcript window."""

    intent: Literal[
        "activation", "pending_order", "promo", "occ", "billing", "general", "system", "other"
    ] = Field(description="Best-matching issue category for the spotted issue.")
    confidence: float = Field(
        description="0.0–1.0 confidence that this is a real, new, actionable issue.",
        ge=0.0, le=1.0,
    )
    title: str = Field(description="Short rep-facing card title, e.g. 'Activation sounds stuck'.")
    summary: str = Field(
        description="1-2 sentences: what was heard in the conversation and why it matters."
    )
    order_id: Optional[str] = Field(
        default=None, description="Order id if one was spoken, else null."
    )
    account_id: Optional[str] = Field(
        default=None, description="Account id if one was spoken, else null."
    )
    tone: Literal["info", "warn", "danger"] = Field(
        description="Card urgency: danger for order-blocking issues, warn for money/billing "
        "issues, info otherwise."
    )


class LiveCoachResult(BaseModel):
    """Structured output of one live-listen transcript analysis pass."""

    suggestions: list[LiveSuggestion] = Field(
        description="New actionable issues only. Empty when nothing new and concrete came up."
    )


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


class ProductionIssueFinding(BaseModel):
    """One systemic issue cluster identified from escalated-ticket inflow."""

    title: str = Field(description="Short incident-style title, e.g. 'ETNI number-inventory lookups failing'.")
    category: Literal["payment", "etni", "activation", "backend", "promo", "billing", "other"] = Field(
        description="Failing system/domain. Use 'etni' for telephone-number-inventory errors, "
        "'backend' for other upstream system failures."
    )
    severity: Literal["critical", "non_critical"] = Field(
        description="critical = order-blocking with a burst of related tickets; "
        "non_critical = recurring theme that is not blocking orders."
    )
    order_blocking: bool = Field(description="True when the issue prevents reps from completing orders.")
    problem_statement: str = Field(
        description="2-4 sentences: what is failing, the observed symptoms, and the customer/order impact."
    )
    recommended_fix: str = Field(
        description="2-4 sentences: the most likely root cause and the concrete remediation to apply."
    )
    ticket_ids: list[str] = Field(description="IDs of the escalated tickets belonging to this cluster.")


class ProductionAnalysis(BaseModel):
    """AI clustering of recent escalations into systemic production issues."""

    issues: list[ProductionIssueFinding] = Field(
        description="Only real clusters (2+ related tickets). Empty when inflow shows no systemic pattern."
    )


class TicketClassification(BaseModel):
    """One escalated ticket bucketed for the Resolution Desk's AI-assisted triage."""

    ticket_id: str = Field(description="The ticket id being classified.")
    category: Literal["education", "agent_action", "system_defect"] = Field(
        description="education = customer needs an explanation/how-to answer; "
        "agent_action = an existing automated resolver (activation/pending_order/promo/occ "
        "intents only) can likely fix it; system_defect = something is actually broken and "
        "needs the dev team."
    )
    reasoning: str = Field(description="One sentence on why this ticket belongs in that bucket.")


class TicketClassificationBatch(BaseModel):
    """Structured output of a Resolution Desk backlog classification pass."""

    classifications: list[TicketClassification] = Field(
        description="One entry per ticket given, same order not required. Classify every ticket provided."
    )


class EnhancementItem(BaseModel):
    """One rep-facing entry in the 'What's new in Rep Assist' card."""

    tag: Literal["New", "Improved"] = Field(
        description="'New' for a capability that did not exist before; 'Improved' for a change to something existing."
    )
    title: str = Field(description="Short plain-language title, e.g. 'Auto-fix for stuck activations'.")
    detail: str = Field(description="1-2 sentences, plain language, written for an entry-level retail rep — no jargon, no code/internal terms.")
    keywords: list[str] = Field(description="3-6 lowercase words/phrases a rep might type when asking about this, for follow-up-question routing.")
    answer: str = Field(description="2-3 sentence detailed answer to give when a rep asks a follow-up question about this specifically.")


class SystemEnhancementsDoc(BaseModel):
    """Rep-facing 'what's new' content, generated from recent commit history."""

    enhancements: list[EnhancementItem] = Field(
        description="Most rep-relevant, most recent first. Omit internal-only changes (bug fixes to "
        "infrastructure, deploy scripts, refactors, docs, CI) that a retail rep would never notice or ask about. "
        "Cap at 8 items — merge/replace older items with newer ones covering the same feature area."
    )
    suggestions: list[str] = Field(
        description="Exactly 3 short natural-language questions a rep might tap to ask about these enhancements."
    )


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
