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
    # 12 hex chars (48 bits) — 8 chars (32 bits) collides ~25% of the time by
    # the time volume reaches tens of thousands of tickets (birthday paradox).
    return "TCK-" + uuid.uuid4().hex[:12].upper()


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
    sales_intent: Optional[str] = None        # nse | aal | up | None (heuristic tag, see llm.tag_sales_intent)


class Ticket(SQLModel, table=True):
    id: str = Field(default_factory=_ticket_id, primary_key=True)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    # Context captured at escalation time
    rep_id: Optional[str] = None
    thread_id: Optional[str] = None
    intent: str = "other"
    sales_intent: Optional[str] = None  # nse | aal | up | None (heuristic tag)
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
    subscribed_alerts: bool = True        # receives critical production-issue alerts
    active: bool = True
    created_at: datetime = Field(default_factory=_now)


class HuddleItem(SQLModel, table=True):
    """A Morning Huddle field-news item, managed from the Settings page and
    served by the 'news' MCP stub."""

    __tablename__ = "huddle_items"

    id: Optional[int] = Field(default=None, primary_key=True)
    category: str = "News"                 # Promo | Device | Policy | Network | News
    title: str = ""
    blurb: str = ""
    article_id: Optional[str] = None       # optional OST article link (e.g. OST-1002)
    active: bool = True
    sort_order: int = 0
    created_at: datetime = Field(default_factory=_now)


def _issue_id() -> str:
    return "PRD-" + uuid.uuid4().hex[:12].upper()


class ProductionIssue(SQLModel, table=True):
    """A systemic production issue detected by AI analysis of escalated-ticket
    inflow (Production Monitor). Critical issues trigger email alerts;
    non-critical recurring themes get a defect filed on the JIRA board (stub)."""

    __tablename__ = "production_issues"

    id: str = Field(default_factory=_issue_id, primary_key=True)
    detected_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    severity: str = "non_critical"        # critical | non_critical
    category: str = "other"               # payment | etni | activation | backend | promo | billing | other
    title: str = ""
    problem_statement: str = ""
    recommended_fix: str = ""
    order_blocking: bool = False

    ticket_ids: list = Field(default_factory=list, sa_column=Column(JSON))
    ticket_count: int = 0

    status: str = "active"                # active | resolved
    alert_sent: bool = False              # email alert dispatched (critical only)
    defect_key: Optional[str] = None      # JIRA key when a defect was filed (non-critical)


class JiraDefect(SQLModel, table=True):
    """A defect on the stubbed JIRA board, filed by the Production Monitor for
    non-critical recurring themes. The stub mirrors what a real MCP JIRA
    integration would create."""

    __tablename__ = "jira_defects"

    key: str = Field(primary_key=True)    # e.g. REP-1412
    created_at: datetime = Field(default_factory=_now)
    summary: str = ""
    description: str = ""                 # problem statement + recommended fix + ticket examples (markdown)
    priority: str = "Medium"
    labels: list = Field(default_factory=list, sa_column=Column(JSON))
    status: str = "Open"
    issue_id: Optional[str] = None        # back-reference to ProductionIssue.id


class LLMCall(SQLModel, table=True):
    """One row per Anthropic API call (or attempted call), across every LLM
    function in the app — conversational (classify, compose) and background
    (executive summary, production analysis, enhancements generation).

    This is the "true token economics" ledger: full token taxonomy (not just
    input/output), whether the call succeeded or degraded to the offline mock
    fallback, and per-call cost — the data neither aggregate CX Monitor totals
    nor LangSmith's default view break out on their own.
    """

    __tablename__ = "llm_calls"

    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=_now)
    thread_id: Optional[str] = None       # None for non-conversational (background) calls
    function: str = ""                    # classify | compose | executive_summary | production_analysis | enhancements
    model: str = ""

    success: bool = True                  # False when the live call raised and fell back to mock
    fallback: bool = False                # True whenever the mock/offline path was used (disabled key or failure)

    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0              # subset of output_tokens spent on extended-thinking reasoning
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0

    latency_ms: int = 0
    cost_usd: float = 0.0


class ActionAudit(SQLModel, table=True):
    """One row per mutating action actually executed against a downstream
    agent (the single `agents_client.execute()` call site in
    `graph/nodes.confirm`). `approved` should be True on every row by
    construction — the graph cannot reach `execute()` without a rep-approved
    LangGraph interrupt/resume first. This table is the continuous proof of
    that invariant (and the audit trail regulators/Trust & Safety expect),
    not a gap-closer for a bypass that exists today."""

    __tablename__ = "action_audit"

    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=_now)
    thread_id: Optional[str] = None
    rep_id: Optional[str] = None
    service: str = ""
    operation: str = ""
    approved: bool = True
    success: bool = True


class GuardrailEvent(SQLModel, table=True):
    """One row per prompt-injection pattern match (see
    docs/16-observability.md). Detection never blocks or alters the turn;
    this is purely a monitoring signal.

    `source` distinguishes where the pattern was found: `direct` (the rep's
    own typed message) vs `indirect` (data that flows into the prompt from
    elsewhere — order context, ticket/conversation history — the OWASP
    LLM01 vector where an attacker never talks to the model directly)."""

    __tablename__ = "guardrail_events"

    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=_now)
    thread_id: Optional[str] = None
    rep_id: Optional[str] = None
    node: str = ""              # triage | compose — where the scan ran
    source: str = "direct"      # direct | indirect
    pattern: str = ""           # which pattern matched, for triage/tuning
    snippet: str = ""           # short excerpt around the match, truncated
