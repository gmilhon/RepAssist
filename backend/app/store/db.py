"""SQLite-backed store for tickets + feedback, plus capability-gap analytics."""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlmodel import Session, SQLModel, create_engine, select

from ..config import get_settings
from .models import ActionAudit, Engagement, GapType, LLMCall, Ticket, TicketStatus

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


def _hours(later: datetime, earlier: datetime) -> float:
    return round((later - earlier).total_seconds() / 3600.0, 1)


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


def observability_overview(
    start: Optional[date] = None, end: Optional[date] = None
) -> dict:
    """Conversation-health, sales-intent, and guardrail metrics — the P0 slice
    of the observability proposal that's computable from data already
    captured on Engagement/Ticket, plus the always-on ActionAudit trail.
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

    messages = [e for e in engagements if e.kind == "message"]
    confirmations = [e for e in engagements if e.kind == "confirmation"]

    # --- conversation health: turns per thread ---
    turns_by_thread: dict[str, int] = Counter()
    terminal_by_thread: dict[str, bool] = {}
    for e in messages:
        if not e.thread_id:
            continue
        turns_by_thread[e.thread_id] += 1
        if e.resolution_status in ("resolved", "escalated", "cancelled"):
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

    # --- guardrail: unconfirmed-mutation invariant ---
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
        },
    }


def llm_usage_overview(
    start: Optional[date] = None, end: Optional[date] = None
) -> dict:
    """True token-economics ledger — full token taxonomy, fallback rate per
    LLM function, and cost-of-failure — from the LLMCall table."""
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
