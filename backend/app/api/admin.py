"""Admin endpoints — seeding and maintenance. Token-protected."""
from __future__ import annotations

import os
import random
import uuid
from datetime import date, datetime, timedelta, timezone

import json

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException
from sqlmodel import Session, delete, text

from ..store.db import _engine
from ..store.models import Engagement, GapType, Ticket, TicketStatus

router = APIRouter(prefix="/api/admin", tags=["admin"])

_ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")


def _require_token(x_admin_token: str = Header(default="")) -> None:
    if not _ADMIN_TOKEN or x_admin_token != _ADMIN_TOKEN:
        raise HTTPException(403, "Invalid or missing X-Admin-Token header")


# --------------------------------------------------------------------------- #
# Seed catalogue (mirrors scripts/seed_ytd.py, scaled for 5k convos/week)
# --------------------------------------------------------------------------- #

INTENTS = {
    "activation":    (28, 18, (0.80, 0.96), "activation-resolver"),
    "pending_order": (18, 14, (0.78, 0.95), "pending-order-resolver"),
    "promo":         (22, 42, (0.74, 0.94), "promo-correction-agent"),
    "occ":           (14, 13, (0.72, 0.92), "occ-credit-agent"),
    "billing":       (10,  8, (0.58, 0.86), "knowledge-base"),
    "other":         ( 8,  5, (0.20, 0.42), "human-tier-2"),
}

SUMMARIES = {
    "activation": [
        "Line stuck in activation after eSIM swap",
        "New iPhone won't activate, no service",
        "SIM provisioned but no signal after port",
        "Device activated but calls drop immediately",
        "Trade-in complete but service not restored",
        "Number transfer failed mid-activation",
        "eSIM profile downloaded but no carrier signal",
        "Activation pending for over 2 hours",
    ],
    "pending_order": [
        "Prior order blocking the new upgrade",
        "Pending order won't release for 48 hours",
        "Customer can't add a line, order on hold",
        "Upgrade stuck in pending approval",
        "Order system showing duplicate open order",
        "Credit check order still pending after 3 days",
        "Order status stuck at 'processing' for 5 days",
    ],
    "promo": [
        "BOGO credit never applied after qualifying purchase",
        "Trade-in promo missing on bill cycle",
        "Loyalty discount dropped off unexpectedly",
        "Holiday promo not appearing after deadline",
        "Buy-two-get-one credit reversed incorrectly",
        "Promotional rate expired but still being charged",
        "New Year promo code rejected at checkout",
        "Spring deal not reflected on new account",
        "Mother's Day bundle promo never applied",
        "Memorial Day trade-in credit missing",
        "Independence Day upgrade promo not applied",
        "Summer back-to-school deal not credited",
    ],
    "occ": [
        "Customer requesting activation fee waiver for new line",
        "Bill credit request for service outage last month",
        "Courtesy credit for porting delay beyond 24 hours",
        "Credit for missed installation appointment",
        "Requesting waiver of international roaming overage",
        "Account credit for equipment arrived damaged",
        "Goodwill credit for multiple dropped calls",
        "Credit requested for billing error on last cycle",
    ],
    "billing": [
        "First bill higher than quoted in store",
        "Unexpected proration charge this cycle",
        "Autopay discount not reflected on bill",
        "Taxes seem higher than expected",
        "Payment posted but balance not updated",
        "Duplicate charge on bill this month",
    ],
    "other": [
        "Watch face won't rename after update",
        "eSIM QR prints upside down on old sales terminal",
        "Scam-likely label on customer's calls",
        "Voicemail greeting stuck in loop",
        "App crashing on device after OS update",
        "Hotspot not working after plan change",
    ],
}

GAP_POOL = {
    "activation": [
        ("carrier-port-status-agent",  GapType.MISSING_AGENT),
        ("activation-resolver",        GapType.AGENT_FAILED),
        ("esim-provisioning-agent",    GapType.MISSING_AGENT),
    ],
    "pending_order": [
        ("credit-hold-resolver",       GapType.MISSING_AGENT),
        ("pending-order-resolver",     GapType.AGENT_FAILED),
        ("order-fraud-release-agent",  GapType.MISSING_AGENT),
    ],
    "promo": [
        ("promo-eligibility-explainer", GapType.MISSING_KNOWLEDGE),
        ("promo-correction-agent",      GapType.AGENT_FAILED),
        ("promo-audit-agent",           GapType.MISSING_AGENT),
    ],
    "occ": [
        ("credit-approval-workflow",   GapType.MISSING_AGENT),
        ("occ-credit-agent",           GapType.AGENT_FAILED),
    ],
    "billing": [
        ("billing-dispute-agent",      GapType.MISSING_AGENT),
        ("billing-knowledge-base",     GapType.MISSING_KNOWLEDGE),
    ],
    "other": [
        ("wearable-settings-agent",    GapType.MISSING_AGENT),
        ("esim-troubleshooter",        GapType.MISSING_AGENT),
        ("number-reputation-agent",    GapType.MISSING_AGENT),
    ],
}

# Sales-intent tagging mirrors the live heuristic's realistic hit rate — most
# engagements stay unclassified; when tagged, the motion correlates loosely
# with the functional intent (e.g. activation issues skew toward new-service
# or upgrade flows). (sales_intent | None, weight) per functional intent.
SALES_INTENT_MIX = {
    "activation":    [("nse", 22), ("up", 16), ("aal", 7),  (None, 55)],
    "pending_order": [("aal", 20), ("up", 15), ("nse", 6),  (None, 59)],
    "promo":         [("nse", 8),  ("aal", 6),  ("up", 8),   (None, 78)],
    "occ":           [("nse", 5),  ("aal", 5),  ("up", 5),   (None, 85)],
    "billing":       [(None, 92), ("up", 4),   ("aal", 4)],
    "other":         [(None, 95), ("nse", 2),  ("aal", 2), ("up", 1)],
}


def _pick_sales_intent(intent: str, rng: random.Random) -> str | None:
    choices = SALES_INTENT_MIX.get(intent, [(None, 100)])
    values  = [c[0] for c in choices]
    weights = [c[1] for c in choices]
    return rng.choices(values, weights=weights)[0]


REPS  = [f"rep.{n}" for n in (
    "alvarez", "chen", "patel", "okafor", "santos", "kim",
    "rodriguez", "nguyen", "washington", "flores", "lee", "martin",
    "jackson", "harris", "lopez", "clark", "walker", "hall",
)]
TIER2 = ["tier2.alice", "tier2.marcus", "tier2.deepa", "tier2.jordan"]

# Monday=0 … Sunday=6
DOW_MULT = {0: 0.75, 1: 0.85, 2: 0.90, 3: 1.05, 4: 1.50, 5: 1.60, 6: 0.35}

MONTH_MULT = {1: 0.88, 2: 0.91, 3: 0.95, 4: 1.00, 5: 1.06, 6: 1.10, 7: 1.08}

HOLIDAYS = [
    (date(2026,  1,  1), 7,  3.0),   # New Year's Day
    (date(2026,  1, 19), 3,  1.8),   # MLK Jr. Day
    (date(2026,  2, 16), 4,  2.0),   # Presidents' Day
    (date(2026,  4,  5), 5,  2.2),   # Easter
    (date(2026,  5, 10), 4,  2.4),   # Mother's Day
    (date(2026,  5, 25), 5,  2.8),   # Memorial Day
    (date(2026,  6, 19), 3,  1.6),   # Juneteenth
    (date(2026,  7,  4), 5,  2.5),   # Independence Day
]

# Target: ~714 base convos/day → ~5,000/week average
_BASE = 714.0


def _holiday_boost(d: date) -> float:
    for holiday, window, peak in HOLIDAYS:
        delta = (d - holiday).days
        if 1 <= delta <= window:
            return 1.0 + (peak - 1.0) * (window - delta + 1) / window
    return 1.0


def _daily_volume(d: date, rng: random.Random) -> int:
    vol = _BASE * DOW_MULT[d.weekday()] * _holiday_boost(d) * MONTH_MULT.get(d.month, 1.0)
    return max(2, round(vol * rng.uniform(0.90, 1.10)))


def _pick_intent(post_holiday: bool, rng: random.Random) -> str:
    keys    = list(INTENTS)
    weights = [INTENTS[k][1 if post_holiday else 0] for k in keys]
    return rng.choices(keys, weights=weights)[0]


def _outcome(intent: str, rng: random.Random) -> str:
    r = rng.random()
    if intent == "activation":
        return "resolved_confirm" if r < 0.72 else ("declined" if r < 0.82 else "escalated")
    if intent == "pending_order":
        return "resolved_confirm" if r < 0.68 else ("declined" if r < 0.76 else "escalated")
    if intent == "promo":
        if r < 0.52: return "resolved_confirm"
        if r < 0.72: return "resolved_direct"
        return "declined" if r < 0.80 else "escalated"
    if intent == "occ":
        return "resolved_confirm" if r < 0.60 else ("declined" if r < 0.65 else "escalated")
    if intent == "billing":
        return "resolved_direct" if r < 0.75 else "escalated"
    return "escalated"


def _make_ticket(
    tickets: list[dict], tkt_id: str, intent: str,
    created: datetime, rep: str, rng: random.Random, sales_intent: str | None = None,
) -> None:
    summary  = rng.choice(SUMMARIES[intent])
    fate     = rng.random()
    convo    = json.dumps([{"role": "user", "content": summary}])
    base = dict(
        id=tkt_id,
        created_at=created.isoformat(),
        updated_at=created.isoformat(),
        rep_id=rep,
        thread_id=f"seed-{uuid.uuid4().hex[:8]}",
        intent=intent,
        sales_intent=sales_intent,
        priority="high" if intent in ("activation", "pending_order") else "normal",
        summary=summary,
        conversation=convo,
        order_id=None, account_id=None, order_context=None, trace="[]",
        assigned_to=None, resolution_notes=None, root_cause_category=None,
        recommended_capability=None, gap_type=None,
        resolved_by=None, resolved_at=None,
    )

    # SQLAlchemy persists these enums by NAME (e.g. "OPEN"), so raw-SQL inserts
    # must use the enum name, not its lowercase value.
    if fate < 0.20:
        tickets.append({**base, "status": TicketStatus.OPEN.name})
        return
    if fate < 0.28:
        tickets.append({**base, "status": TicketStatus.IN_REVIEW.name, "assigned_to": rng.choice(TIER2)})
        return

    res_at   = (created + timedelta(hours=round(rng.uniform(0.5, 36), 1))).isoformat()
    gap_pool = GAP_POOL[intent]

    if fate < 0.36:
        tickets.append({**base, "status": TicketStatus.CLOSED.name, "updated_at": res_at,
                        "resolution_notes": "Handled one-off; no capability gap.",
                        "root_cause_category": summary, "gap_type": GapType.NONE.name,
                        "resolved_by": rng.choice(TIER2), "resolved_at": res_at})
        return

    cap, gap = rng.choice(gap_pool)
    tickets.append({**base, "status": TicketStatus.RESOLVED.name, "updated_at": res_at,
                    "resolution_notes": "Root cause identified and added to backlog.",
                    "root_cause_category": summary, "recommended_capability": cap,
                    "gap_type": gap.name, "resolved_by": rng.choice(TIER2),
                    "resolved_at": res_at})


# --------------------------------------------------------------------------- #
# Seed state (module-level, survives within one container instance)
# --------------------------------------------------------------------------- #
_seed_state: dict = {"running": False, "done": False, "result": None, "error": None}


_ENG_SQL = """
INSERT INTO engagement
  (created_at, thread_id, rep_id, kind, intent, confidence,
   status, resolution_status, capability, confirmed, ticket_id, sales_intent)
VALUES
  (:created_at, :thread_id, :rep_id, :kind, :intent, :confidence,
   :status, :resolution_status, :capability, :confirmed, :ticket_id, :sales_intent)
"""

_TKT_SQL = """
INSERT INTO ticket
  (id, created_at, updated_at, rep_id, thread_id, intent, sales_intent, priority, summary,
   order_id, account_id, conversation, order_context, trace,
   status, assigned_to, resolution_notes, root_cause_category,
   recommended_capability, gap_type, resolved_by, resolved_at)
VALUES
  (:id, :created_at, :updated_at, :rep_id, :thread_id, :intent, :sales_intent, :priority, :summary,
   :order_id, :account_id, :conversation, :order_context, :trace,
   :status, :assigned_to, :resolution_notes, :root_cause_category,
   :recommended_capability, :gap_type, :resolved_by, :resolved_at)
"""

_LLM_SQL = """
INSERT INTO llm_calls
  (created_at, thread_id, function, model, success, fallback,
   input_tokens, output_tokens, thinking_tokens, cache_creation_tokens, cache_read_tokens,
   latency_ms, cost_usd)
VALUES
  (:created_at, :thread_id, :function, :model, :success, :fallback,
   :input_tokens, :output_tokens, :thinking_tokens, :cache_creation_tokens, :cache_read_tokens,
   :latency_ms, :cost_usd)
"""

_AUDIT_SQL = """
INSERT INTO action_audit
  (created_at, thread_id, rep_id, service, operation, approved, success)
VALUES
  (:created_at, :thread_id, :rep_id, :service, :operation, :approved, :success)
"""

# Plausible per-function token/latency/cost profile — mirrors what live calls
# actually looked like when this instrumentation was built (see docs/16).
_LLM_PROFILE = {
    "classify": {"in": (700, 200), "out": (55, 20), "think": (0, 8), "lat": (2500, 4500)},
    "compose":  {"in": (850, 250), "out": (95, 30), "think": (0, 5), "lat": (2000, 3800)},
}
_IN_RATE  = 3.0 / 1_000_000
_OUT_RATE = 15.0 / 1_000_000
_FALLBACK_RATE = 0.015  # ~1.5% of calls degrade to mock, same order as real transient failure rates


def _llm_call_row(function: str, ts: str, thread: str, rng: random.Random) -> dict:
    profile = _LLM_PROFILE[function]
    fallback = rng.random() < _FALLBACK_RATE
    if fallback:
        return dict(created_at=ts, thread_id=thread, function=function, model="claude-sonnet-5",
                    success=True, fallback=True, input_tokens=0, output_tokens=0, thinking_tokens=0,
                    cache_creation_tokens=0, cache_read_tokens=0, latency_ms=0, cost_usd=0.0)
    in_tok  = max(50, int(rng.gauss(*profile["in"])))
    out_tok = max(20, int(rng.gauss(*profile["out"])))
    think   = max(0, int(rng.gauss(*profile["think"])))
    think   = min(think, out_tok)
    lat     = max(300, int(rng.gauss(*profile["lat"])))
    cost    = in_tok * _IN_RATE + out_tok * _OUT_RATE
    return dict(created_at=ts, thread_id=thread, function=function, model="claude-sonnet-5",
                success=True, fallback=False, input_tokens=in_tok, output_tokens=out_tok,
                thinking_tokens=think, cache_creation_tokens=0, cache_read_tokens=0,
                latency_ms=lat, cost_usd=round(cost, 6))


def _run_seed() -> dict:
    rng   = random.Random(20260101)
    start = date(2026, 1, 1)
    end   = date.today()

    total_conversations = 0
    total_engagements   = 0
    total_tickets       = 0
    total_llm_calls     = 0
    total_actions       = 0

    conn = _engine.raw_connection()
    try:
        conn.execute("DELETE FROM engagement")
        conn.execute("DELETE FROM ticket")
        conn.execute("DELETE FROM llm_calls")
        conn.execute("DELETE FROM action_audit")
        conn.commit()

        # Process week by week to stay memory-efficient; use raw SQL for speed
        d = start
        while d <= end:
            week_end = min(d + timedelta(days=6), end)
            eng_rows: list[dict] = []
            tkt_rows: list[dict] = []
            llm_rows: list[dict] = []
            audit_rows: list[dict] = []
            threads:  set[str]   = set()

            cur = d
            while cur <= week_end:
                vol = _daily_volume(cur, rng)
                ph  = _holiday_boost(cur) > 1.05

                for _ in range(vol):
                    intent = _pick_intent(ph, rng)
                    _, _, (c_lo, c_hi), capability = INTENTS[intent]
                    conf   = round(rng.uniform(c_lo, c_hi), 2)
                    rep    = rng.choice(REPS)
                    sales_intent = _pick_sales_intent(intent, rng)
                    thread = f"seed-{cur.isoformat()}-{uuid.uuid4().hex[:6]}"
                    ts     = datetime(
                        cur.year, cur.month, cur.day,
                        rng.randint(8, 20), rng.randint(0, 59), rng.randint(0, 59),
                        tzinfo=timezone.utc,
                    ).isoformat()
                    threads.add(thread)
                    outcome = _outcome(intent, rng)

                    # Every turn triages (classify) and composes a reply — same
                    # 1:1 shape the live graph produces (see docs/16).
                    llm_rows.append(_llm_call_row("classify", ts, thread, rng))
                    llm_rows.append(_llm_call_row("compose", ts, thread, rng))

                    if outcome in ("resolved_confirm", "declined"):
                        approved = outcome == "resolved_confirm"
                        eng_rows.append(dict(
                            created_at=ts, thread_id=thread, rep_id=rep, kind="message",
                            intent=intent, confidence=conf, status="needs_confirmation",
                            resolution_status=None, capability=None, confirmed=None, ticket_id=None,
                            sales_intent=sales_intent,
                        ))
                        eng_rows.append(dict(
                            created_at=ts, thread_id=thread, rep_id=rep, kind="confirmation",
                            intent=intent, confidence=conf, status="answered",
                            resolution_status="resolved" if approved else "cancelled",
                            capability=capability, confirmed=approved, ticket_id=None,
                            sales_intent=sales_intent,
                        ))
                        if approved:
                            audit_rows.append(dict(
                                created_at=ts, thread_id=thread, rep_id=rep,
                                service=capability, operation="EXECUTE",
                                approved=True, success=True,
                            ))

                    elif outcome == "resolved_direct":
                        eng_rows.append(dict(
                            created_at=ts, thread_id=thread, rep_id=rep, kind="message",
                            intent=intent, confidence=conf, status="answered",
                            resolution_status="resolved", capability=capability,
                            confirmed=None, ticket_id=None, sales_intent=sales_intent,
                        ))

                    else:
                        tkt_id = "TCK-" + uuid.uuid4().hex[:12].upper()
                        _make_ticket(tkt_rows, tkt_id, intent,
                                     datetime.fromisoformat(ts), rep, rng, sales_intent)
                        eng_rows.append(dict(
                            created_at=ts, thread_id=thread, rep_id=rep, kind="message",
                            intent=intent, confidence=conf, status="escalated",
                            resolution_status="escalated", capability="human-tier-2",
                            confirmed=None, ticket_id=tkt_id, sales_intent=sales_intent,
                        ))

                cur += timedelta(days=1)

            conn.executemany(_ENG_SQL, eng_rows)
            conn.executemany(_TKT_SQL, tkt_rows)
            conn.executemany(_LLM_SQL, llm_rows)
            if audit_rows:
                conn.executemany(_AUDIT_SQL, audit_rows)
            conn.commit()

            total_conversations += len(threads)
            total_engagements   += len(eng_rows)
            total_tickets       += len(tkt_rows)
            total_llm_calls     += len(llm_rows)
            total_actions       += len(audit_rows)
            d = week_end + timedelta(days=1)

    finally:
        conn.close()

    days = (end - start).days + 1
    return {
        "seeded_days": days,
        "date_range": f"{start} → {end}",
        "conversations": total_conversations,
        "engagements": total_engagements,
        "tickets": total_tickets,
        "llm_calls": total_llm_calls,
        "actions_audited": total_actions,
        "weekly_avg_conversations": round(total_conversations / (days / 7)),
    }


def _seed_background() -> None:
    global _seed_state
    try:
        result = _run_seed()
        _seed_state = {"running": False, "done": True, "result": result, "error": None}
    except Exception as exc:
        _seed_state = {"running": False, "done": False, "result": None, "error": str(exc)}


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #

@router.post("/seed", status_code=202)
def seed_demo(background_tasks: BackgroundTasks, x_admin_token: str = Header(default="")) -> dict:
    _require_token(x_admin_token)
    if _seed_state["running"]:
        return {"status": "already_running"}
    _seed_state.update({"running": True, "done": False, "result": None, "error": None})
    background_tasks.add_task(_seed_background)
    return {"status": "started", "poll": "/api/admin/seed/status"}


@router.get("/seed/status")
def seed_status(x_admin_token: str = Header(default="")) -> dict:
    _require_token(x_admin_token)
    return _seed_state
