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

    # --- Production Monitor dimensions (see production_geo_data) ---
    # Captured at escalation time so the impact map and P1–P4 severity can
    # reason about cloud/channel/store scope. Nullable for pre-existing rows.
    cloud_env: Optional[str] = None   # aws_east | aws_west — region the rep was connected to
    store_id: Optional[str] = None    # reporting location id (STORE_BY_ID)
    channel: Optional[str] = None     # retail | indirect | d2d | inside_sales
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

    # --- AI Assisted Resolution Desk classification (set by POST /api/tickets/analyze) ---
    ai_category: Optional[str] = None       # education | agent_action | system_defect
    ai_reasoning: Optional[str] = None      # one-line why for this bucket
    ai_article_id: Optional[str] = None     # OST article suggested, when category == education
    ai_article_title: Optional[str] = None
    ai_capability: Optional[str] = None     # capability suggested, when category == agent_action
    ai_analyzed_at: Optional[datetime] = None


class EmailSubscriber(SQLModel, table=True):
    """Recipients for scheduled/on-demand dashboard email reports."""

    __tablename__ = "email_subscribers"

    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True)
    name: Optional[str] = None
    subscribed_performance: bool = True   # receives Performance dashboard reports
    subscribed_cx: bool = True            # receives CX Monitor reports
    subscribed_alerts: bool = True        # receives critical production-issue alerts
    subscribed_visit_summary: bool = True  # receives Live Listen visit-summary emails
    active: bool = True
    created_at: datetime = Field(default_factory=_now)


class PlaybookGuideline(SQLModel, table=True):
    """A single Playbook guideline, managed from the Settings page. Guidelines
    define the standard a rep is graded against after a Live Listen visit —
    grouped into meeting customer needs and positioning sales opportunities."""

    __tablename__ = "playbook_guidelines"

    id: Optional[int] = Field(default=None, primary_key=True)
    category: str = "Customer Needs"   # "Customer Needs" | "Sales Positioning"
    text: str = ""
    active: bool = True
    sort_order: int = 0
    created_at: datetime = Field(default_factory=_now)


class EnhancementVideo(SQLModel, table=True):
    """A training video uploaded for one enhancement (Settings → Training), shown
    on the 'What's new' card. The file lives on disk; this row is the metadata.
    Linked to an enhancement by title (the closest stable key we have)."""

    __tablename__ = "enhancement_videos"

    id: Optional[int] = Field(default=None, primary_key=True)
    enhancement_title: str = Field(index=True)
    stored_name: str                       # generated filename on disk
    original_name: str = ""
    content_type: str = "video/mp4"
    size_bytes: int = 0
    uploaded_at: datetime = Field(default_factory=_now)


class HiddenEnhancement(SQLModel, table=True):
    """A system enhancement a manager has hidden from reps (Settings → Training).
    Enhancements themselves live in the (redeployed-each-build) JSON, so we can't
    flag them there; we persist just the hidden ones here, keyed by title — the
    same stable key EnhancementVideo uses."""

    __tablename__ = "hidden_enhancements"

    enhancement_title: str = Field(primary_key=True)
    hidden_at: datetime = Field(default_factory=_now)


class ShoppingCart(SQLModel, table=True):
    """The in-progress shopping cart for one chat thread (the in-chat
    add-a-line / upgrade experience). Rebuilt turn-by-turn by graph.nodes.shop
    and rendered in the chat's top cart drawer. Items are a JSON blob so the
    item shape can evolve without a migration."""

    __tablename__ = "shopping_carts"

    thread_id: str = Field(primary_key=True)
    account_id: Optional[str] = None
    items: list = Field(default_factory=list, sa_column=Column(JSON))
    updated_at: datetime = Field(default_factory=_now)


def _order_id() -> str:
    return "SO-" + uuid.uuid4().hex[:8].upper()


class ShopOrder(SQLModel, table=True):
    """A placed shopping order (add-a-line / upgrade checkout). The 'payment' is
    SIMULATED — no real charge is ever made; this records the demo receipt after
    the rep approves the order at the confirmation gate."""

    __tablename__ = "shop_orders"

    id: str = Field(default_factory=_order_id, primary_key=True)
    created_at: datetime = Field(default_factory=_now)
    thread_id: Optional[str] = None
    rep_id: Optional[str] = None
    account_id: Optional[str] = None
    items: list = Field(default_factory=list, sa_column=Column(JSON))
    monthly_total: float = 0.0
    onetime_total: float = 0.0
    payment_method: str = ""       # masked mock card, e.g. "Visa ending 4242"
    # One-time / perks / fulfillment breakdown captured at the signature step.
    taxes: float = 0.0
    activation_fees: float = 0.0
    onetime_breakdown: dict = Field(default_factory=dict, sa_column=Column(JSON))
    perks: list = Field(default_factory=list, sa_column=Column(JSON))
    fulfillment: str = "pickup"    # pickup | ship
    signed_at: Optional[datetime] = None
    signature_ref: Optional[str] = None   # demo artifact ref — never raw PII
    receipt_channel: Optional[str] = None  # sms | email | none


def _checkout_id() -> str:
    return "CO-" + uuid.uuid4().hex[:12]


class CheckoutSession(SQLModel, table=True):
    """A guided POS checkout for one cart — the 'View Together' → payment →
    signature wizard. Server-side + addressable by `id` so the SAME session can
    be driven from the rep's screen AND the customer's phone (/checkout/{id}).
    Payment is SIMULATED and the signature is a demo artifact; no real charge is
    ever made and no card/PII is stored."""

    __tablename__ = "checkout_sessions"

    id: str = Field(default_factory=_checkout_id, primary_key=True)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
    thread_id: Optional[str] = None
    rep_id: Optional[str] = None
    account_id: Optional[str] = None
    items: list = Field(default_factory=list, sa_column=Column(JSON))
    quote: dict = Field(default_factory=dict, sa_column=Column(JSON))
    step: str = "review"           # review | payment | signature | complete
    payment_method: Optional[str] = None
    fulfillment: str = "pickup"    # pickup | ship
    signed: bool = False
    signed_at: Optional[datetime] = None
    signature_ref: Optional[str] = None
    receipt_channel: Optional[str] = None
    sent_channel: Optional[str] = None    # last send-to-phone channel used (sms|qr)
    order_id: Optional[str] = None


class CesRoute(SQLModel, table=True):
    """Which triage intents relay to the external Google CES `repAssist` agent
    instead of the built-in resolver/knowledge node. Managed from Settings → CES
    Routing and read live each turn (see graph.nodes.route_after_triage), so a
    manager's toggle takes effect on the very next message. Mirrors the
    HiddenEnhancement pattern: a tiny policy table keyed by a stable string.

    The connection itself (which deployment, where) is env/Secret-Manager config,
    NOT stored here — this table holds only the on/off routing policy."""

    __tablename__ = "ces_routes"

    intent: str = Field(primary_key=True)          # Intent value: "billing", "activation", …
    enabled: bool = True
    entry_agent: Optional[str] = None              # optional CES sub-agent (Billing/Accounts/…)
    updated_at: datetime = Field(default_factory=_now)


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

    severity: str = "non_critical"        # critical | non_critical (drives alert vs. defect)
    priority_level: str = "P4"            # P1 | P2 | P3 | P4 (impact-derived severity)
    category: str = "other"               # payment | etni | activation | backend | promo | billing | other
    title: str = ""
    problem_statement: str = ""
    recommended_fix: str = ""
    order_blocking: bool = False          # sales-blocking
    workaround_available: bool = False    # a workaround exists (pulls P3→P4)

    ticket_ids: list = Field(default_factory=list, sa_column=Column(JSON))
    ticket_count: int = 0

    # Aggregated impact across the cluster's member tickets, recomputed each
    # analysis pass — the inputs to the P-level and what the card renders.
    channels: list = Field(default_factory=list, sa_column=Column(JSON))    # distinct channels impacted
    clouds: list = Field(default_factory=list, sa_column=Column(JSON))      # distinct cloud envs impacted
    store_ids: list = Field(default_factory=list, sa_column=Column(JSON))   # distinct reporting stores
    store_count: int = 0                  # number of unique reporting stores

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
    ticket_ids: list = Field(default_factory=list, sa_column=Column(JSON))  # Resolution Desk tickets attached here


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


def _queue_id() -> str:
    return "Q-" + uuid.uuid4().hex[:8].upper()


class QueueStatus(str, Enum):
    WAITING = "waiting"          # checked in, not yet being helped
    IN_PROGRESS = "in_progress"  # a rep tapped "Assist" and is working with them
    # In-store pickup (ISPU) fulfilment states — order-driven, not walk-in.
    ISPU_TO_PICK = "ispu_to_pick"  # order placed, still needs picking off the shelf
    ISPU_READY = "ispu_ready"      # picked & staged, awaiting customer collection
    # A future appointment booked for later today; customer hasn't arrived yet.
    SCHEDULED = "scheduled"


class QueueEntry(SQLModel, table=True):
    """A customer checked in at the store, waiting for or currently receiving
    help. Created by the "Check In" CTA; the "View Queue" CTA lists these as
    an A2UI `queue` card, and tapping a row's Assist button claims the entry
    and drops the rep into a normal chat thread with the customer's name/phone
    and visit reason pre-filled as entities."""

    __tablename__ = "queue_entries"

    id: str = Field(default_factory=_queue_id, primary_key=True)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    reason: str = "other"  # VisitReason value

    # Known customer account/order, captured at check-in so the assisting rep
    # (and Live Listen) can call agents without re-prompting for these ids.
    account_id: Optional[str] = None
    order_id: Optional[str] = None

    status: str = QueueStatus.WAITING
    assigned_rep_id: Optional[str] = None
    thread_id: Optional[str] = None  # chat thread once a rep starts assisting
    started_at: Optional[datetime] = None

    # When a SCHEDULED appointment is booked for (today, in the future). Null for
    # walk-in / ISPU rows. Drives the "Future appointments" list in Live Queue.
    scheduled_at: Optional[datetime] = None


def _listen_id() -> str:
    return "LS-" + uuid.uuid4().hex[:8].upper()


class ListenSession(SQLModel, table=True):
    """One Live Listen session: a rep starts listening while assisting a
    checked-in customer, utterances stream into `transcript`, and the AI
    watcher's surfaced cards accumulate in `suggestions`. The watcher is
    strictly read-only — accepting a card goes through the normal chat flow;
    nothing in the listen path executes actions or creates tickets."""

    __tablename__ = "listen_sessions"

    id: str = Field(default_factory=_listen_id, primary_key=True)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    rep_id: str
    thread_id: str                     # chat thread the session is attached to
    queue_entry_id: Optional[str] = None

    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    reason: str = "other"              # VisitReason value, copied from the queue entry
    account_id: Optional[str] = None   # known customer account, copied from the queue entry
    order_id: Optional[str] = None     # known customer order, copied from the queue entry
    mode: str = "mic"                  # "mic" | "demo"

    status: str = "active"             # "active" | "ended"
    ended_at: Optional[datetime] = None

    eligibility: Optional[dict] = Field(default=None, sa_column=Column(JSON))  # sales opportunities for this customer

    transcript: list = Field(default_factory=list, sa_column=Column(JSON))   # [{speaker, text}]
    suggestions: list = Field(default_factory=list, sa_column=Column(JSON))  # surfaced suggestion dicts
    summary: Optional[dict] = Field(default=None, sa_column=Column(JSON))     # generated VisitSummary
    playbook_score: Optional[int] = None                                     # 1-5 stars vs. the Playbook
    playbook_grade: Optional[dict] = Field(default=None, sa_column=Column(JSON))  # full PlaybookGrade
    coaching: Optional[dict] = Field(default=None, sa_column=Column(JSON))    # generated CoachingRecommendation


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
