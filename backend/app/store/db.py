"""SQLite-backed store for tickets + feedback, plus capability-gap analytics."""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlmodel import Session, SQLModel, create_engine, select

from ..config import get_settings
from .models import (
    ActionAudit,
    CesRoute,
    CheckoutSession,
    EnhancementVideo,
    Engagement,
    GapType,
    GuardrailEvent,
    HiddenEnhancement,
    ListenSession,
    LLMCall,
    PlaybookGuideline,
    QueueEntry,
    QueueStatus,
    ShoppingCart,
    ShopOrder,
    Ticket,
    TicketStatus,
)

_settings = get_settings()
_engine = create_engine(
    _settings.tickets_db_url, connect_args={"check_same_thread": False}
)


def _date_bounds(
    start: Optional[date], end: Optional[date]
) -> tuple[Optional[datetime], Optional[datetime]]:
    """Convert inclusive date range to UTC datetime half-open interval [lo, hi)."""
    lo = datetime(start.year, start.month, start.day, tzinfo=timezone.utc) if start else None
    hi = (
        datetime(end.year, end.month, end.day, tzinfo=timezone.utc) + timedelta(days=1)
        if end
        else None
    )
    return lo, hi


def init_db() -> None:
    SQLModel.metadata.create_all(_engine)
    # Best-effort additive migration for pre-existing SQLite files
    # (create_all never alters existing tables).
    from sqlalchemy import text

    with _engine.connect() as conn:
        try:
            conn.execute(text(
                "ALTER TABLE email_subscribers ADD COLUMN subscribed_alerts BOOLEAN DEFAULT 1"
            ))
            conn.commit()
        except Exception:  # noqa: BLE001 - column already exists
            pass
        try:
            conn.execute(text("ALTER TABLE engagement ADD COLUMN sales_intent VARCHAR"))
            conn.commit()
        except Exception:  # noqa: BLE001 - column already exists
            pass
        try:
            conn.execute(text("ALTER TABLE ticket ADD COLUMN sales_intent VARCHAR"))
            conn.commit()
        except Exception:  # noqa: BLE001 - column already exists
            pass
        for stmt in (
            "ALTER TABLE ticket ADD COLUMN ai_category VARCHAR",
            "ALTER TABLE ticket ADD COLUMN ai_reasoning VARCHAR",
            "ALTER TABLE ticket ADD COLUMN ai_article_id VARCHAR",
            "ALTER TABLE ticket ADD COLUMN ai_article_title VARCHAR",
            "ALTER TABLE ticket ADD COLUMN ai_capability VARCHAR",
            "ALTER TABLE ticket ADD COLUMN ai_analyzed_at DATETIME",
            # Production Monitor: cloud/store/channel captured at escalation time.
            "ALTER TABLE ticket ADD COLUMN cloud_env VARCHAR",
            "ALTER TABLE ticket ADD COLUMN store_id VARCHAR",
            "ALTER TABLE ticket ADD COLUMN channel VARCHAR",
            # Production Monitor: P1–P4 severity + aggregated cluster impact.
            "ALTER TABLE production_issues ADD COLUMN priority_level VARCHAR DEFAULT 'P4'",
            "ALTER TABLE production_issues ADD COLUMN workaround_available BOOLEAN DEFAULT 0",
            "ALTER TABLE production_issues ADD COLUMN channels JSON DEFAULT '[]'",
            "ALTER TABLE production_issues ADD COLUMN clouds JSON DEFAULT '[]'",
            "ALTER TABLE production_issues ADD COLUMN store_ids JSON DEFAULT '[]'",
            "ALTER TABLE production_issues ADD COLUMN store_count INTEGER DEFAULT 0",
            "ALTER TABLE jira_defects ADD COLUMN ticket_ids JSON DEFAULT '[]'",
            "ALTER TABLE email_subscribers ADD COLUMN subscribed_visit_summary BOOLEAN DEFAULT 1",
            "ALTER TABLE queue_entries ADD COLUMN account_id VARCHAR",
            "ALTER TABLE queue_entries ADD COLUMN order_id VARCHAR",
            "ALTER TABLE queue_entries ADD COLUMN scheduled_at DATETIME",
            "ALTER TABLE listen_sessions ADD COLUMN account_id VARCHAR",
            "ALTER TABLE listen_sessions ADD COLUMN order_id VARCHAR",
            "ALTER TABLE listen_sessions ADD COLUMN summary JSON",
            "ALTER TABLE listen_sessions ADD COLUMN eligibility JSON",
            "ALTER TABLE listen_sessions ADD COLUMN playbook_score INTEGER",
            "ALTER TABLE listen_sessions ADD COLUMN playbook_grade JSON",
            "ALTER TABLE listen_sessions ADD COLUMN coaching JSON",
            "ALTER TABLE shop_orders ADD COLUMN taxes FLOAT DEFAULT 0",
            "ALTER TABLE shop_orders ADD COLUMN activation_fees FLOAT DEFAULT 0",
            "ALTER TABLE shop_orders ADD COLUMN onetime_breakdown JSON DEFAULT '{}'",
            "ALTER TABLE shop_orders ADD COLUMN perks JSON DEFAULT '[]'",
            "ALTER TABLE shop_orders ADD COLUMN fulfillment VARCHAR DEFAULT 'pickup'",
            "ALTER TABLE shop_orders ADD COLUMN signed_at DATETIME",
            "ALTER TABLE shop_orders ADD COLUMN signature_ref VARCHAR",
            "ALTER TABLE shop_orders ADD COLUMN receipt_channel VARCHAR",
        ):
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception:  # noqa: BLE001 - column already exists
                pass


# --------------------------------------------------------------------------- #
# Engagement analytics
# --------------------------------------------------------------------------- #
def record_engagement(**kwargs) -> None:
    """Append one interaction event (best-effort; never breaks the conversation)."""
    try:
        with Session(_engine) as s:
            s.add(Engagement(**kwargs))
            s.commit()
    except Exception:  # noqa: BLE001 - analytics must not affect the chat path
        pass


def reset_demo() -> None:
    """Wipe engagements + tickets (used by the demo seed script)."""
    with Session(_engine) as s:
        for e in s.exec(select(Engagement)).all():
            s.delete(e)
        for t in s.exec(select(Ticket)).all():
            s.delete(t)
        for c in s.exec(select(LLMCall)).all():
            s.delete(c)
        for a in s.exec(select(ActionAudit)).all():
            s.delete(a)
        for g in s.exec(select(GuardrailEvent)).all():
            s.delete(g)
        for q in s.exec(select(QueueEntry)).all():
            s.delete(q)
        for ls in s.exec(select(ListenSession)).all():
            s.delete(ls)
        s.commit()


def record_llm_call(**kwargs) -> None:
    """Append one LLM call-usage row (best-effort; never breaks the caller)."""
    try:
        with Session(_engine) as s:
            s.add(LLMCall(**kwargs))
            s.commit()
    except Exception:  # noqa: BLE001 - analytics must not affect the LLM call path
        pass


def record_action_audit(**kwargs) -> None:
    """Append one executed-action audit row (best-effort)."""
    try:
        with Session(_engine) as s:
            s.add(ActionAudit(**kwargs))
            s.commit()
    except Exception:  # noqa: BLE001 - analytics must not affect the confirm path
        pass


def record_guardrail_event(**kwargs) -> None:
    """Append one injection-pattern-match row (best-effort, log-only)."""
    try:
        with Session(_engine) as s:
            s.add(GuardrailEvent(**kwargs))
            s.commit()
    except Exception:  # noqa: BLE001 - analytics must not affect the calling path
        pass


def check_fallback_spike(window_minutes: int = 10, threshold: float = 0.05) -> Optional[dict]:
    """Pure query, no side effects: has the fallback-to-mock rate exceeded
    `threshold` over the last `window_minutes`? Returns spike info or None.
    Needs a minimum sample size so a single fallback in a quiet period
    doesn't read as a 100% spike.
    """
    MIN_SAMPLE = 8
    since = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
    with Session(_engine) as s:
        # Exclude listen_analyze: a Live Listen session in offline mode logs a
        # fallback=True row every few seconds by design, which would read as a
        # spike and trip auto-degrade even though nothing regressed. The
        # conversational functions remain the health signal.
        rows = list(s.exec(
            select(LLMCall).where(
                LLMCall.created_at >= since,
                LLMCall.function != "listen_analyze",
            )
        ).all())
    if len(rows) < MIN_SAMPLE:
        return None
    fallback_count = sum(1 for r in rows if r.fallback)
    rate = fallback_count / len(rows)
    if rate <= threshold:
        return None
    return {
        "window_minutes": window_minutes,
        "threshold": threshold,
        "calls": len(rows),
        "fallback_calls": fallback_count,
        "fallback_rate": round(rate, 3),
    }


def _aware(dt: datetime) -> datetime:
    # SQLite round-trips lose tzinfo for ORM-written datetimes but not for the
    # raw-SQL-bulk-inserted demo seed, so a seeded ticket resolved through the
    # app mixes an aware created_at with a naive resolved_at (or vice versa).
    # All our naive datetimes are UTC by construction (see models._now), so
    # this normalization is correct, not a guess.
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _hours(later: datetime, earlier: datetime) -> float:
    return round((_aware(later) - _aware(earlier)).total_seconds() / 3600.0, 1)


def metrics_overview(
    start: Optional[date] = None, end: Optional[date] = None
) -> dict:
    """Aggregate engagements + tickets into the operational KPI payload."""
    lo, hi = _date_bounds(start, end)
    with Session(_engine) as s:
        eng_stmt = select(Engagement)
        if lo:
            eng_stmt = eng_stmt.where(Engagement.created_at >= lo)
        if hi:
            eng_stmt = eng_stmt.where(Engagement.created_at < hi)
        engagements = list(s.exec(eng_stmt).all())

        tkt_stmt = select(Ticket)
        if lo:
            tkt_stmt = tkt_stmt.where(Ticket.created_at >= lo)
        if hi:
            tkt_stmt = tkt_stmt.where(Ticket.created_at < hi)
        tickets = list(s.exec(tkt_stmt).all())

    messages = [e for e in engagements if e.kind == "message"]
    confirmations = [e for e in engagements if e.kind == "confirmation"]

    # --- engagement ---
    threads = {e.thread_id for e in engagements if e.thread_id}
    reps = {e.rep_id for e in engagements if e.rep_id}
    confs = [e.confidence for e in messages if e.confidence is not None]
    avg_conf = round(sum(confs) / len(confs), 3) if confs else 0.0

    # --- outcomes (terminal results across all turns) ---
    auto_resolved = sum(1 for e in engagements if e.resolution_status == "resolved")
    escalated = sum(1 for e in engagements if e.status == "escalated")
    cancelled = sum(1 for e in engagements if e.resolution_status == "cancelled")
    total_outcomes = auto_resolved + escalated + cancelled
    containment = round(auto_resolved / total_outcomes, 3) if total_outcomes else 0.0
    esc_rate = round(escalated / total_outcomes, 3) if total_outcomes else 0.0

    # --- confirmations (human-in-the-loop) ---
    requested = sum(1 for e in messages if e.status == "needs_confirmation")
    approved = sum(1 for e in confirmations if e.confirmed is True)
    declined = sum(1 for e in confirmations if e.confirmed is False)
    approval_rate = round(approved / (approved + declined), 3) if (approved + declined) else 0.0

    # --- by intent ---
    intents: dict[str, dict] = {}
    for e in messages:
        key = e.intent or "unknown"
        row = intents.setdefault(
            key, {"intent": key, "count": 0, "auto_resolved": 0, "escalated": 0, "_conf": []}
        )
        row["count"] += 1
        if e.status == "escalated":
            row["escalated"] += 1
        if e.confidence is not None:
            row["_conf"].append(e.confidence)
    for e in engagements:
        if e.resolution_status == "resolved" and e.intent:
            if e.intent in intents:
                intents[e.intent]["auto_resolved"] += 1
    intent_rows = []
    for row in intents.values():
        conf = row.pop("_conf")
        row["avg_confidence"] = round(sum(conf) / len(conf), 3) if conf else 0.0
        intent_rows.append(row)
    intent_rows.sort(key=lambda r: r["count"], reverse=True)

    # --- resolving capabilities ---
    caps: Counter = Counter()
    for e in engagements:
        if e.resolution_status == "resolved" and e.capability:
            caps[e.capability] += 1
    capability_rows = [
        {"capability": c, "resolutions": n} for c, n in caps.most_common()
    ]

    # --- tickets ---
    status_counts = Counter(t.status.value if hasattr(t.status, "value") else t.status for t in tickets)
    resolved_durations = [
        _hours(t.resolved_at, t.created_at)
        for t in tickets
        if t.resolved_at and t.created_at
    ]
    avg_res_hours = round(sum(resolved_durations) / len(resolved_durations), 1) if resolved_durations else None
    tickets_by_intent = Counter(t.intent for t in tickets)

    # --- timeseries (by calendar day) ---
    days: dict[str, dict] = {}
    for e in engagements:
        d = e.created_at.date().isoformat()
        row = days.setdefault(d, {"date": d, "interactions": 0, "auto_resolved": 0, "escalated": 0})
        if e.kind == "message":
            row["interactions"] += 1
        if e.resolution_status == "resolved":
            row["auto_resolved"] += 1
        if e.status == "escalated":
            row["escalated"] += 1
    timeseries = [days[d] for d in sorted(days)]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "engagement": {
            "conversations": len(threads),
            "interactions": len(messages),
            "active_reps": len(reps),
            "avg_confidence": avg_conf,
            "messages_per_conversation": round(len(messages) / len(threads), 1) if threads else 0.0,
        },
        "outcomes": {
            "auto_resolved": auto_resolved,
            "escalated": escalated,
            "cancelled": cancelled,
            "total": total_outcomes,
            "containment_rate": containment,
            "escalation_rate": esc_rate,
        },
        "confirmations": {
            "requested": requested,
            "approved": approved,
            "declined": declined,
            "approval_rate": approval_rate,
        },
        "intents": intent_rows,
        "capabilities": capability_rows,
        "tickets": {
            "open": status_counts.get("open", 0),
            "in_review": status_counts.get("in_review", 0),
            "resolved": status_counts.get("resolved", 0),
            "closed": status_counts.get("closed", 0),
            "total": len(tickets),
            "avg_resolution_hours": avg_res_hours,
            "by_intent": [{"intent": k, "count": v} for k, v in tickets_by_intent.most_common()],
        },
        "timeseries": timeseries,
    }


# Ensure tables exist as soon as the store is imported, so the orchestrator can
# create tickets whether it runs inside the API or standalone (tests, scripts).
init_db()


def create_ticket(**kwargs) -> Ticket:
    ticket = Ticket(**kwargs)
    with Session(_engine) as s:
        s.add(ticket)
        s.commit()
        s.refresh(ticket)
    return ticket


def list_tickets(status: Optional[str] = None) -> list[Ticket]:
    with Session(_engine) as s:
        stmt = select(Ticket).order_by(Ticket.created_at.desc())
        if status:
            stmt = stmt.where(Ticket.status == status)
        return list(s.exec(stmt).all())


def get_ticket(ticket_id: str) -> Optional[Ticket]:
    with Session(_engine) as s:
        return s.get(Ticket, ticket_id)


def claim_ticket(ticket_id: str, agent: str) -> Optional[Ticket]:
    with Session(_engine) as s:
        ticket = s.get(Ticket, ticket_id)
        if not ticket:
            return None
        ticket.status = TicketStatus.IN_REVIEW
        ticket.assigned_to = agent
        ticket.updated_at = datetime.now(timezone.utc)
        s.add(ticket)
        s.commit()
        s.refresh(ticket)
        return ticket


def set_ticket_ai_classification(
    ticket_id: str,
    *,
    category: str,
    reasoning: str,
    article_id: Optional[str] = None,
    article_title: Optional[str] = None,
    capability: Optional[str] = None,
    analyzed_at: datetime,
) -> Optional[Ticket]:
    with Session(_engine) as s:
        ticket = s.get(Ticket, ticket_id)
        if not ticket:
            return None
        ticket.ai_category = category
        ticket.ai_reasoning = reasoning
        ticket.ai_article_id = article_id
        ticket.ai_article_title = article_title
        ticket.ai_capability = capability
        ticket.ai_analyzed_at = analyzed_at
        ticket.updated_at = analyzed_at
        s.add(ticket)
        s.commit()
        s.refresh(ticket)
        return ticket


def resolve_ticket(
    ticket_id: str,
    *,
    resolution_notes: str,
    root_cause_category: str,
    recommended_capability: str,
    gap_type: str,
    resolved_by: str,
    close_only: bool = False,
) -> Optional[Ticket]:
    with Session(_engine) as s:
        ticket = s.get(Ticket, ticket_id)
        if not ticket:
            return None
        ticket.resolution_notes = resolution_notes
        ticket.root_cause_category = root_cause_category
        ticket.recommended_capability = recommended_capability
        ticket.gap_type = GapType(gap_type)
        ticket.resolved_by = resolved_by
        ticket.resolved_at = datetime.now(timezone.utc)
        ticket.updated_at = ticket.resolved_at
        ticket.status = TicketStatus.CLOSED if close_only else TicketStatus.RESOLVED
        s.add(ticket)
        s.commit()
        s.refresh(ticket)
        return ticket


# --------------------------------------------------------------------------- #
# Store check-in queue
# --------------------------------------------------------------------------- #
def create_queue_entry(**kwargs) -> tuple[QueueEntry, int]:
    """Create a check-in and return it with its 1-indexed position among
    customers still waiting (the entry itself included).

    Sorts/counts in Python rather than via SQL ORDER BY / WHERE on
    `created_at`: the demo seed bulk-inserts that column as ISO text
    (`...T...+00:00`) via raw SQL, while the ORM writes it as SQLAlchemy's
    own `datetime` serialization (`... ` space, no offset) — two different
    text representations in the same column. SQLite compares them
    lexicographically, which silently misorders rows; comparing the parsed
    `datetime` objects (via `_aware`) is correct regardless of how each row
    was written. See `_aware()`'s docstring for the same issue elsewhere.
    """
    with Session(_engine) as s:
        entry = QueueEntry(**kwargs)
        s.add(entry)
        s.commit()
        s.refresh(entry)
        waiting = s.exec(select(QueueEntry).where(QueueEntry.status == QueueStatus.WAITING)).all()
        position = sum(1 for w in waiting if _aware(w.created_at) <= _aware(entry.created_at))
        return entry, position


def list_queue(limit: int = 20) -> list[QueueEntry]:
    """Customers still waiting or currently being helped, waiting first
    (oldest first), then in-progress (most recently started first).
    Sorted in Python for the same mixed-timestamp-format reason as
    `create_queue_entry` above."""
    with Session(_engine) as s:
        waiting = sorted(
            s.exec(select(QueueEntry).where(QueueEntry.status == QueueStatus.WAITING)).all(),
            key=lambda e: _aware(e.created_at),
        )
        in_progress = sorted(
            s.exec(select(QueueEntry).where(QueueEntry.status == QueueStatus.IN_PROGRESS)).all(),
            key=lambda e: _aware(e.started_at or e.created_at),
            reverse=True,
        )
        return list(waiting) + in_progress[: max(limit - len(waiting), 0)]


def get_queue_entry(entry_id: str) -> Optional[QueueEntry]:
    with Session(_engine) as s:
        return s.get(QueueEntry, entry_id)


def assist_queue_entry(entry_id: str, rep_id: str, thread_id: Optional[str] = None) -> Optional[QueueEntry]:
    with Session(_engine) as s:
        entry = s.get(QueueEntry, entry_id)
        if not entry:
            return None
        entry.status = QueueStatus.IN_PROGRESS
        entry.assigned_rep_id = rep_id
        entry.thread_id = thread_id
        entry.started_at = datetime.now(timezone.utc)
        entry.updated_at = entry.started_at
        s.add(entry)
        s.commit()
        s.refresh(entry)
        return entry


def live_queue_snapshot() -> dict[str, list[QueueEntry]]:
    """Everything happening on the floor right now, bucketed for the Live Queue
    indicator: walk-ins waiting, customers being assisted, in-store-pickup orders
    (still to pick vs. staged & waiting on the customer), and today's still-to-come
    appointments. Sorted in Python for the same mixed-timestamp reason as
    `list_queue`/`create_queue_entry`."""
    now = datetime.now(timezone.utc)
    with Session(_engine) as s:
        rows = list(s.exec(select(QueueEntry)).all())

    def by(status: QueueStatus) -> list[QueueEntry]:
        return [e for e in rows if e.status == status]

    waiting = sorted(by(QueueStatus.WAITING), key=lambda e: _aware(e.created_at))
    assisting = sorted(
        by(QueueStatus.IN_PROGRESS),
        key=lambda e: _aware(e.started_at or e.created_at),
        reverse=True,
    )
    ispu_to_pick = sorted(by(QueueStatus.ISPU_TO_PICK), key=lambda e: _aware(e.created_at))
    ispu_ready = sorted(by(QueueStatus.ISPU_READY), key=lambda e: _aware(e.created_at))
    # Future appointments still ahead of us today (past ones have effectively
    # become no-shows or already-served walk-ins), earliest first.
    appointments = sorted(
        (
            e for e in by(QueueStatus.SCHEDULED)
            if e.scheduled_at and _aware(e.scheduled_at) >= now
        ),
        key=lambda e: _aware(e.scheduled_at),
    )
    return {
        "waiting": waiting,
        "assisting": assisting,
        "ispu_to_pick": ispu_to_pick,
        "ispu_ready": ispu_ready,
        "appointments": appointments,
    }


# --------------------------------------------------------------------------- #
# Hidden system enhancements (Settings → Training visibility toggle)
# --------------------------------------------------------------------------- #
def hidden_enhancement_titles() -> set[str]:
    """Titles of enhancements a manager has hidden from the rep-facing card."""
    with Session(_engine) as s:
        return {h.enhancement_title for h in s.exec(select(HiddenEnhancement)).all()}


def set_enhancement_hidden(title: str, hidden: bool) -> None:
    """Hide or un-hide one enhancement (idempotent), keyed by title."""
    with Session(_engine) as s:
        existing = s.get(HiddenEnhancement, title)
        if hidden and not existing:
            s.add(HiddenEnhancement(enhancement_title=title))
            s.commit()
        elif not hidden and existing:
            s.delete(existing)
            s.commit()


# --------------------------------------------------------------------------- #
# Shopping cart (in-chat add-a-line / upgrade flow; rendered in the cart drawer)
# --------------------------------------------------------------------------- #
def get_cart(thread_id: str) -> Optional[ShoppingCart]:
    with Session(_engine) as s:
        return s.get(ShoppingCart, thread_id)


def save_cart(thread_id: str, items: list, account_id: Optional[str] = None) -> ShoppingCart:
    """Upsert a thread's cart items (reassigns the JSON list — SQLAlchemy
    doesn't track in-place mutations of a plain JSON column)."""
    with Session(_engine) as s:
        cart = s.get(ShoppingCart, thread_id) or ShoppingCart(thread_id=thread_id)
        cart.items = list(items)
        if account_id is not None:
            cart.account_id = account_id
        cart.updated_at = datetime.now(timezone.utc)
        s.add(cart)
        s.commit()
        s.refresh(cart)
        return cart


def clear_cart(thread_id: str) -> None:
    with Session(_engine) as s:
        cart = s.get(ShoppingCart, thread_id)
        if cart:
            s.delete(cart)
            s.commit()


def create_shop_order(**kwargs) -> ShopOrder:
    """Record a placed order (after the rep approves at the confirm gate)."""
    order = ShopOrder(**kwargs)
    with Session(_engine) as s:
        s.add(order)
        s.commit()
        s.refresh(order)
    return order


# --------------------------------------------------------------------------- #
# Checkout sessions (guided POS wizard — rep screen + customer phone sync)
# --------------------------------------------------------------------------- #
def create_checkout(**kwargs) -> CheckoutSession:
    session = CheckoutSession(**kwargs)
    with Session(_engine) as s:
        s.add(session)
        s.commit()
        s.refresh(session)
    return session


def get_checkout(checkout_id: str) -> Optional[CheckoutSession]:
    with Session(_engine) as s:
        return s.get(CheckoutSession, checkout_id)


def save_checkout(session: CheckoutSession) -> CheckoutSession:
    """Persist mutations to a (possibly detached) checkout session. `merge`
    upserts by primary key so re-saving an instance loaded elsewhere does an
    UPDATE rather than a conflicting INSERT, and picks up reassigned JSON cols."""
    session.updated_at = datetime.now(timezone.utc)
    with Session(_engine) as s:
        merged = s.merge(session)
        s.commit()
        s.refresh(merged)
    return merged


# --------------------------------------------------------------------------- #
# CES routing policy (Settings → CES Routing; read live by route_after_triage)
# --------------------------------------------------------------------------- #
def ces_routes() -> dict[str, CesRoute]:
    """All routing rows, keyed by intent. Read once per turn by the router."""
    with Session(_engine) as s:
        return {r.intent: r for r in s.exec(select(CesRoute)).all()}


def ces_enabled_intents() -> set[str]:
    """Intents currently switched ON to relay to the external CES agent."""
    return {intent for intent, r in ces_routes().items() if r.enabled}


def set_ces_route(intent: str, enabled: bool, entry_agent: Optional[str] = None) -> None:
    """Upsert one intent's routing rule (idempotent). Passing entry_agent=None
    leaves the existing sub-agent untouched; passing "" clears it."""
    with Session(_engine) as s:
        r = s.get(CesRoute, intent) or CesRoute(intent=intent)
        r.enabled = enabled
        if entry_agent is not None:
            r.entry_agent = entry_agent or None
        r.updated_at = datetime.now(timezone.utc)
        s.add(r)
        s.commit()


# --------------------------------------------------------------------------- #
# Live Listen sessions
# --------------------------------------------------------------------------- #
def create_listen_session(**kwargs) -> ListenSession:
    with Session(_engine) as s:
        session = ListenSession(**kwargs)
        s.add(session)
        s.commit()
        s.refresh(session)
        return session


def get_listen_session(session_id: str) -> Optional[ListenSession]:
    with Session(_engine) as s:
        return s.get(ListenSession, session_id)


def append_listen_utterances(session_id: str, utterances: list[dict]) -> Optional[ListenSession]:
    """Append finalized utterances ({speaker, text} dicts) to the transcript.

    Reassigns the JSON column (old list + new list) rather than mutating in
    place — SQLAlchemy doesn't track in-place mutations of a plain JSON
    column, so an `.append()` would silently never persist.
    """
    with Session(_engine) as s:
        session = s.get(ListenSession, session_id)
        if not session:
            return None
        session.transcript = list(session.transcript or []) + list(utterances)
        session.updated_at = datetime.now(timezone.utc)
        s.add(session)
        s.commit()
        s.refresh(session)
        return session


def record_listen_suggestions(session_id: str, suggestions: list[dict]) -> Optional[ListenSession]:
    """Append newly-surfaced suggestion cards to the session. Same JSON-column
    reassignment rule as `append_listen_utterances`."""
    with Session(_engine) as s:
        session = s.get(ListenSession, session_id)
        if not session:
            return None
        session.suggestions = list(session.suggestions or []) + list(suggestions)
        session.updated_at = datetime.now(timezone.utc)
        s.add(session)
        s.commit()
        s.refresh(session)
        return session


def save_listen_summary(session_id: str, summary: dict) -> Optional[ListenSession]:
    """Persist the generated visit summary on the session so the send-summary
    endpoint reuses it instead of re-calling the model."""
    with Session(_engine) as s:
        session = s.get(ListenSession, session_id)
        if not session:
            return None
        session.summary = summary
        session.updated_at = datetime.now(timezone.utc)
        s.add(session)
        s.commit()
        s.refresh(session)
        return session


def save_listen_grade(session_id: str, score: int, grade: dict) -> Optional[ListenSession]:
    """Persist the Playbook grade (stars + breakdown) on the session."""
    with Session(_engine) as s:
        session = s.get(ListenSession, session_id)
        if not session:
            return None
        session.playbook_score = score
        session.playbook_grade = grade
        session.updated_at = datetime.now(timezone.utc)
        s.add(session)
        s.commit()
        s.refresh(session)
        return session


def save_listen_coaching(session_id: str, coaching: dict) -> Optional[ListenSession]:
    """Persist a generated coaching recommendation so it's reused, not re-called."""
    with Session(_engine) as s:
        session = s.get(ListenSession, session_id)
        if not session:
            return None
        session.coaching = coaching
        session.updated_at = datetime.now(timezone.utc)
        s.add(session)
        s.commit()
        s.refresh(session)
        return session


def list_recent_graded_sessions(limit: int = 12) -> list[ListenSession]:
    """Ended Live Listen sessions that carry a Playbook score, newest first —
    the source for the Coaching card."""
    with Session(_engine) as s:
        rows = list(s.exec(
            select(ListenSession).where(ListenSession.playbook_score != None)  # noqa: E711
        ).all())
    rows.sort(key=lambda r: _aware(r.ended_at or r.created_at), reverse=True)
    return rows[:limit]


def end_listen_session(session_id: str) -> Optional[ListenSession]:
    with Session(_engine) as s:
        session = s.get(ListenSession, session_id)
        if not session:
            return None
        if session.status != "ended":  # idempotent: a re-stop keeps the first ended_at
            session.status = "ended"
            session.ended_at = datetime.now(timezone.utc)
            session.updated_at = session.ended_at
            s.add(session)
            s.commit()
            s.refresh(session)
        return session


def observability_overview(
    start: Optional[date] = None, end: Optional[date] = None
) -> dict:
    """Conversation-health, sales-intent, and guardrail metrics, computed
    from Engagement/Ticket data plus the always-on ActionAudit and
    GuardrailEvent trails. See docs/16-observability.md.
    """
    lo, hi = _date_bounds(start, end)
    with Session(_engine) as s:
        eng_stmt = select(Engagement)
        if lo:
            eng_stmt = eng_stmt.where(Engagement.created_at >= lo)
        if hi:
            eng_stmt = eng_stmt.where(Engagement.created_at < hi)
        engagements = list(s.exec(eng_stmt).all())

        audit_stmt = select(ActionAudit)
        if lo:
            audit_stmt = audit_stmt.where(ActionAudit.created_at >= lo)
        if hi:
            audit_stmt = audit_stmt.where(ActionAudit.created_at < hi)
        audits = list(s.exec(audit_stmt).all())

        gr_stmt = select(GuardrailEvent)
        if lo:
            gr_stmt = gr_stmt.where(GuardrailEvent.created_at >= lo)
        if hi:
            gr_stmt = gr_stmt.where(GuardrailEvent.created_at < hi)
        injections = list(s.exec(gr_stmt).all())

    # Normalize once at the source: engagements mix aware (raw-SQL-seeded)
    # and naive (ORM-written) created_at values (see _aware()), and this
    # function sorts/min/max's them below.
    for e in engagements:
        e.created_at = _aware(e.created_at)

    messages = [e for e in engagements if e.kind == "message"]
    confirmations = [e for e in engagements if e.kind == "confirmation"]

    # --- conversation health: turns per thread ---
    turns_by_thread: dict[str, int] = Counter()
    for e in messages:
        if e.thread_id:
            turns_by_thread[e.thread_id] += 1
    # Terminal state can land on either the message row (direct resolve /
    # escalate) or the separate confirmation row (confirm-flow resolve /
    # cancel) — must scan all engagements, not just messages, or every
    # confirm-flow thread reads as perpetually unresolved.
    terminal_by_thread: dict[str, bool] = {}
    for e in engagements:
        if e.thread_id and e.resolution_status in ("resolved", "escalated", "cancelled"):
            terminal_by_thread[e.thread_id] = True
    turn_counts = sorted(turns_by_thread.values())
    n = len(turn_counts)

    def _pctl(p: float) -> int:
        if not n:
            return 0
        idx = min(n - 1, int(n * p))
        return turn_counts[idx]

    LOOP_THRESHOLD = 6
    looping_threads = [
        tid for tid, count in turns_by_thread.items()
        if count > LOOP_THRESHOLD and not terminal_by_thread.get(tid)
    ]

    # --- confirmation reversal ---
    approved = sum(1 for e in confirmations if e.confirmed is True)
    declined = sum(1 for e in confirmations if e.confirmed is False)
    reversal_rate = round(declined / (approved + declined), 3) if (approved + declined) else 0.0

    # --- out-of-scope trend ---
    other_count = sum(1 for e in messages if e.intent == "other")
    out_of_scope_rate = round(other_count / len(messages), 3) if messages else 0.0
    trend_note = None
    sorted_msgs = sorted(messages, key=lambda e: e.created_at)
    if len(sorted_msgs) >= 8:
        half = len(sorted_msgs) // 2
        prior, recent = sorted_msgs[:half], sorted_msgs[half:]
        prior_rate = sum(1 for e in prior if e.intent == "other") / len(prior)
        recent_rate = sum(1 for e in recent if e.intent == "other") / len(recent)
        if prior_rate > 0:
            delta = round((recent_rate - prior_rate) / prior_rate * 100)
            trend_note = f"{'up' if delta > 0 else 'down'} {abs(delta)}% vs. prior half of window"

    # --- sales-intent breakdown ---
    sales: dict[str, dict] = {}
    for e in messages:
        key = e.sales_intent or "unclassified"
        row = sales.setdefault(
            key, {"sales_intent": key, "count": 0, "auto_resolved": 0, "escalated": 0, "_conf": []}
        )
        row["count"] += 1
        if e.status == "escalated":
            row["escalated"] += 1
        if e.confidence is not None:
            row["_conf"].append(e.confidence)
    for e in engagements:
        if e.resolution_status == "resolved":
            key = e.sales_intent or "unclassified"
            if key in sales:
                sales[key]["auto_resolved"] += 1
    sales_rows = []
    for row in sales.values():
        conf = row.pop("_conf")
        row["avg_confidence"] = round(sum(conf) / len(conf), 3) if conf else 0.0
        row["containment_rate"] = round(row["auto_resolved"] / row["count"], 3) if row["count"] else 0.0
        sales_rows.append(row)
    sales_rows.sort(key=lambda r: r["count"], reverse=True)

    # --- re-ask: same intent classified 2+ times in one thread before a terminal state ---
    thread_seq: dict[str, list] = {}
    for e in sorted(messages, key=lambda e: e.created_at):
        if e.thread_id:
            thread_seq.setdefault(e.thread_id, []).append(e)
    re_ask_threads = 0
    for seq in thread_seq.values():
        seen_intents: set = set()
        for e in seq:
            if e.resolution_status in ("resolved", "escalated", "cancelled"):
                break
            if e.intent:
                if e.intent in seen_intents:
                    re_ask_threads += 1
                    break
                seen_intents.add(e.intent)
    re_ask_rate = round(re_ask_threads / len(thread_seq), 3) if thread_seq else 0.0

    # --- abandonment: thread has messages but never reaches a terminal state ---
    abandoned_threads = [tid for tid in turns_by_thread if tid not in terminal_by_thread]
    abandonment_rate = round(len(abandoned_threads) / len(turns_by_thread), 3) if turns_by_thread else 0.0

    # --- repeat-contact: new thread for same rep+intent opened within 24h of a
    # prior *resolved* thread — a proxy for a false-positive resolution.
    thread_info: dict[str, dict] = {}
    for e in engagements:
        if not e.thread_id:
            continue
        info = thread_info.setdefault(e.thread_id, {
            "rep_id": e.rep_id, "intent": e.intent,
            "start": e.created_at, "end": e.created_at, "resolved": False,
        })
        info["start"] = min(info["start"], e.created_at)
        info["end"] = max(info["end"], e.created_at)
        if not info["intent"] and e.intent:
            info["intent"] = e.intent
        if e.resolution_status == "resolved":
            info["resolved"] = True

    by_rep_intent: dict[tuple, list[dict]] = {}
    for info in thread_info.values():
        by_rep_intent.setdefault((info["rep_id"], info["intent"]), []).append(info)

    repeat_contacts = 0
    for group in by_rep_intent.values():
        group.sort(key=lambda i: i["start"])
        resolved_ends: list[datetime] = []  # sliding window, O(n) amortized
        for info in group:
            while resolved_ends and (info["start"] - resolved_ends[0]) > timedelta(hours=24):
                resolved_ends.pop(0)
            if resolved_ends:
                repeat_contacts += 1
            if info["resolved"]:
                resolved_ends.append(info["end"])
    repeat_contact_rate = round(repeat_contacts / len(thread_info), 3) if thread_info else 0.0

    # --- guardrail: unconfirmed-mutation invariant + injection-attempt log ---
    unapproved = [a for a in audits if not a.approved]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "conversation_health": {
            "turns_per_conversation": {
                "p50": _pctl(0.50), "p90": _pctl(0.90), "p99": _pctl(0.99),
                "conversations_measured": n,
            },
            "looping_threshold": LOOP_THRESHOLD,
            "looping_conversations": len(looping_threads),
            "confirmation_reversal_rate": reversal_rate,
            "confirmations_declined": declined,
            "confirmations_approved": approved,
            "out_of_scope_rate": out_of_scope_rate,
            "out_of_scope_trend": trend_note,
            "re_ask_rate": re_ask_rate,
            "abandonment_rate": abandonment_rate,
            "repeat_contact_rate": repeat_contact_rate,
        },
        "sales_intent": sales_rows,
        "guardrail": {
            "actions_executed": len(audits),
            "unconfirmed_mutation_count": len(unapproved),  # invariant: must always be 0
            "unconfirmed_mutation_examples": [
                {"thread_id": a.thread_id, "service": a.service, "operation": a.operation,
                 "created_at": a.created_at.isoformat()}
                for a in unapproved[:5]
            ],
            "injection_attempts": len(injections),  # log-only signal, see docs/17
            "injection_examples": [
                {"thread_id": g.thread_id, "node": g.node, "source": g.source,
                 "pattern": g.pattern, "snippet": g.snippet, "created_at": g.created_at.isoformat()}
                for g in injections[:5]
            ],
        },
    }


def llm_usage_overview(
    start: Optional[date] = None, end: Optional[date] = None
) -> dict:
    """True token-economics ledger — full token taxonomy, fallback rate per
    LLM function, and cost-of-failure — from the LLMCall table.

    "Cost per graph node" (see docs/16-observability.md) is delivered as
    cost-by-function crossed with intent and outcome, not a per-resolver
    breakdown — the resolver nodes (activation/promo/pending_order/occ) call
    `agents_client`, not Claude, so `classify` (triage) and `compose` are the
    *only* two nodes that ever touch the LLM in this graph. That's the real,
    honest granularity available.
    """
    lo, hi = _date_bounds(start, end)
    with Session(_engine) as s:
        call_stmt = select(LLMCall)
        if lo:
            call_stmt = call_stmt.where(LLMCall.created_at >= lo)
        if hi:
            call_stmt = call_stmt.where(LLMCall.created_at < hi)
        calls = list(s.exec(call_stmt).all())

        esc_stmt = select(Engagement.thread_id).where(Engagement.status == "escalated")
        if lo:
            esc_stmt = esc_stmt.where(Engagement.created_at >= lo)
        if hi:
            esc_stmt = esc_stmt.where(Engagement.created_at < hi)
        escalated_threads = {t for t in s.exec(esc_stmt).all() if t}

        meta_stmt = select(Engagement.thread_id, Engagement.intent, Engagement.resolution_status)
        if lo:
            meta_stmt = meta_stmt.where(Engagement.created_at >= lo)
        if hi:
            meta_stmt = meta_stmt.where(Engagement.created_at < hi)
        meta_rows = list(s.exec(meta_stmt).all())

    thread_intent: dict[str, str] = {}
    thread_outcome: dict[str, str] = {}
    for tid, intent, res_status in meta_rows:
        if not tid:
            continue
        if intent and tid not in thread_intent:
            thread_intent[tid] = intent
        if res_status in ("resolved", "escalated", "cancelled"):
            thread_outcome[tid] = res_status

    if not calls:
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "calls_recorded": 0,
            "token_taxonomy": {
                "avg_input": 0, "avg_output": 0, "avg_thinking": 0,
                "avg_cache_creation": 0, "avg_cache_read": 0,
                "total_input": 0, "total_output": 0, "total_thinking": 0,
                "total_cache_creation": 0, "total_cache_read": 0,
            },
            "cost_usd": {"total": 0.0, "avg_per_call": 0.0, "cost_of_failure": 0.0,
                         "cost_of_failure_pct": 0.0},
            "by_function": [],
            "by_intent": [],
            "by_outcome": [],
        }

    total_in  = sum(c.input_tokens for c in calls)
    total_out = sum(c.output_tokens for c in calls)
    total_thk = sum(c.thinking_tokens for c in calls)
    total_cc  = sum(c.cache_creation_tokens for c in calls)
    total_cr  = sum(c.cache_read_tokens for c in calls)
    total_cost = sum(c.cost_usd for c in calls)
    n = len(calls)

    cost_of_failure = sum(
        c.cost_usd for c in calls if c.thread_id and c.thread_id in escalated_threads
    )

    by_fn: dict[str, dict] = {}
    for c in calls:
        row = by_fn.setdefault(c.function, {
            "function": c.function, "calls": 0, "fallback_calls": 0,
            "total_cost_usd": 0.0, "avg_latency_ms": 0, "_lat": [],
        })
        row["calls"] += 1
        if c.fallback:
            row["fallback_calls"] += 1
        row["total_cost_usd"] += c.cost_usd
        if c.latency_ms:
            row["_lat"].append(c.latency_ms)
    fn_rows = []
    for row in by_fn.values():
        lat = row.pop("_lat")
        row["avg_latency_ms"] = int(sum(lat) / len(lat)) if lat else 0
        row["total_cost_usd"] = round(row["total_cost_usd"], 4)
        row["fallback_rate"] = round(row["fallback_calls"] / row["calls"], 3) if row["calls"] else 0.0
        fn_rows.append(row)
    fn_rows.sort(key=lambda r: r["calls"], reverse=True)

    by_intent: dict[str, dict] = {}
    by_outcome: dict[str, dict] = {}
    for c in calls:
        intent  = thread_intent.get(c.thread_id, "unknown") if c.thread_id else "background"
        outcome = thread_outcome.get(c.thread_id, "unresolved") if c.thread_id else "background"

        ir = by_intent.setdefault(intent, {"intent": intent, "calls": 0, "total_cost_usd": 0.0})
        ir["calls"] += 1
        ir["total_cost_usd"] += c.cost_usd

        orow = by_outcome.setdefault(outcome, {"outcome": outcome, "calls": 0, "total_cost_usd": 0.0})
        orow["calls"] += 1
        orow["total_cost_usd"] += c.cost_usd

    intent_rows = sorted(
        ({**r, "total_cost_usd": round(r["total_cost_usd"], 4)} for r in by_intent.values()),
        key=lambda r: r["total_cost_usd"], reverse=True,
    )
    outcome_rows = sorted(
        ({**r, "total_cost_usd": round(r["total_cost_usd"], 4)} for r in by_outcome.values()),
        key=lambda r: r["total_cost_usd"], reverse=True,
    )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "calls_recorded": n,
        "token_taxonomy": {
            "avg_input": round(total_in / n), "avg_output": round(total_out / n),
            "avg_thinking": round(total_thk / n),
            "avg_cache_creation": round(total_cc / n), "avg_cache_read": round(total_cr / n),
            "total_input": total_in, "total_output": total_out, "total_thinking": total_thk,
            "total_cache_creation": total_cc, "total_cache_read": total_cr,
        },
        "cost_usd": {
            "total": round(total_cost, 4),
            "avg_per_call": round(total_cost / n, 6),
            "cost_of_failure": round(cost_of_failure, 4),
            "cost_of_failure_pct": round(cost_of_failure / total_cost, 3) if total_cost else 0.0,
        },
        "by_function": fn_rows,
        "by_intent": intent_rows,
        "by_outcome": outcome_rows,
    }


def capability_gaps(
    start: Optional[date] = None, end: Optional[date] = None
) -> list[dict]:
    """Aggregate resolved-ticket feedback into a ranked backlog for the dev team.

    This closes the loop the user asked for: the assistant 'improves' by telling
    the dev team exactly which agents/skills to build or fix next, weighted by
    how often each gap blocks reps.
    """
    weight = {GapType.MISSING_AGENT: 3, GapType.AGENT_FAILED: 3,
              GapType.MISSING_KNOWLEDGE: 2, GapType.BAD_DATA: 1,
              GapType.TRAINING: 1, GapType.NONE: 0}
    lo, hi = _date_bounds(start, end)
    rows: dict[str, dict] = {}
    with Session(_engine) as s:
        # Only count tickets a Tier 1/2 human actually resolved with a real,
        # confirmed capability gap — not the auto-prefilled hint on open tickets,
        # and not "close (no gap)" outcomes.
        stmt = select(Ticket).where(
            Ticket.gap_type.is_not(None),
            Ticket.gap_type != GapType.NONE,
            Ticket.recommended_capability.is_not(None),
        )
        if lo:
            stmt = stmt.where(Ticket.created_at >= lo)
        if hi:
            stmt = stmt.where(Ticket.created_at < hi)
        tickets = s.exec(stmt).all()
    for t in tickets:
        cap = t.recommended_capability or "unspecified"
        row = rows.setdefault(
            cap,
            {"capability": cap, "ticket_count": 0, "score": 0,
             "gap_types": Counter(), "intents": Counter(), "examples": []},
        )
        row["ticket_count"] += 1
        gt = t.gap_type or GapType.NONE
        row["score"] += weight.get(gt, 1)
        row["gap_types"][gt.value] += 1
        row["intents"][t.intent] += 1
        if len(row["examples"]) < 3 and t.summary:
            row["examples"].append({"ticket_id": t.id, "summary": t.summary})

    result = []
    for row in rows.values():
        row["gap_types"] = dict(row["gap_types"])
        row["intents"] = dict(row["intents"])
        result.append(row)
    result.sort(key=lambda r: (r["score"], r["ticket_count"]), reverse=True)
    return result


# --------------------------------------------------------------------------- #
# Playbook guidelines (managed in Settings; graded against after Live Listen)
# --------------------------------------------------------------------------- #
_PLAYBOOK_DEFAULTS = [
    ("Customer Needs", "Greet the customer warmly and confirm what they came in for."),
    ("Customer Needs", "Acknowledge and address every issue the customer raises."),
    ("Customer Needs", "Confirm the fix or next step and set clear expectations before they leave."),
    ("Sales Positioning", "Check the customer's upgrade eligibility and mention any available promo."),
    ("Sales Positioning", "Position home internet (Fiber Home Internet or Fixed Wireless Internet) when the customer qualifies."),
    ("Sales Positioning", "Tie any recommendation to the customer's stated needs, never pushy."),
]


def seed_playbook_defaults_if_empty() -> None:
    """Populate the default Playbook the first time (idempotent)."""
    with Session(_engine) as s:
        if s.exec(select(PlaybookGuideline)).first():
            return
        for i, (category, text) in enumerate(_PLAYBOOK_DEFAULTS):
            s.add(PlaybookGuideline(category=category, text=text, sort_order=i))
        s.commit()


def list_playbook_guidelines(active_only: bool = False) -> list[PlaybookGuideline]:
    with Session(_engine) as s:
        stmt = select(PlaybookGuideline)
        if active_only:
            stmt = stmt.where(PlaybookGuideline.active == True)  # noqa: E712
        rows = list(s.exec(stmt).all())
    rows.sort(key=lambda r: (r.sort_order, r.id or 0))
    return rows


# --------------------------------------------------------------------------- #
# Enhancement training videos (Settings → Training; shown on the What's-new card)
# --------------------------------------------------------------------------- #
def add_enhancement_video(**kwargs) -> EnhancementVideo:
    with Session(_engine) as s:
        video = EnhancementVideo(**kwargs)
        s.add(video)
        s.commit()
        s.refresh(video)
        return video


def list_enhancement_videos() -> list[EnhancementVideo]:
    with Session(_engine) as s:
        rows = list(s.exec(select(EnhancementVideo)).all())
    rows.sort(key=lambda v: _aware(v.uploaded_at), reverse=True)
    return rows


def get_enhancement_video(video_id: int) -> Optional[EnhancementVideo]:
    with Session(_engine) as s:
        return s.get(EnhancementVideo, video_id)


def latest_video_for_title(title: str) -> Optional[EnhancementVideo]:
    """Most recent video uploaded for an enhancement title, if any."""
    with Session(_engine) as s:
        rows = list(s.exec(
            select(EnhancementVideo).where(EnhancementVideo.enhancement_title == title)
        ).all())
    if not rows:
        return None
    rows.sort(key=lambda v: _aware(v.uploaded_at), reverse=True)
    return rows[0]


def delete_enhancement_video(video_id: int) -> Optional[EnhancementVideo]:
    """Delete the row and return it (so the caller can remove the file)."""
    with Session(_engine) as s:
        video = s.get(EnhancementVideo, video_id)
        if not video:
            return None
        s.delete(video)
        s.commit()
        return video
