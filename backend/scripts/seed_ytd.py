"""Seed Jan 1 – Jun 15, 2026 engagement + ticket history.

Volume patterns:
  - High on Fri/Sat, very low on Sunday
  - Post-holiday spikes (promo intent dominates after each US holiday)
  - Gradual seasonal growth Jan → Jun

Clears existing data, then inserts in two bulk transactions.

    cd backend
    . .venv/bin/activate
    python scripts/seed_ytd.py
"""
from __future__ import annotations

import os
import sys
import uuid
import random
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.store.db import _engine, reset_demo, metrics_overview  # noqa: E402
from app.store.models import Engagement, GapType, Ticket, TicketStatus  # noqa: E402
from sqlmodel import Session  # noqa: E402

random.seed(2026)

# --------------------------------------------------------------------------- #
# Intent catalogue
# intent -> (normal_weight, post_holiday_weight, (conf_lo, conf_hi), capability)
# --------------------------------------------------------------------------- #
INTENTS: dict[str, tuple[int, int, tuple[float, float], str]] = {
    "activation":    (28, 18, (0.80, 0.96), "activation-resolver"),
    "pending_order": (18, 14, (0.78, 0.95), "pending-order-resolver"),
    "promo":         (22, 42, (0.74, 0.94), "promo-correction-agent"),
    "occ":           (14, 13, (0.72, 0.92), "occ-credit-agent"),
    "billing":       (10,  8, (0.58, 0.86), "knowledge-base"),
    "other":         ( 8,  5, (0.20, 0.42), "human-tier-2"),
}

SUMMARIES: dict[str, list[str]] = {
    "activation": [
        "Line stuck in activation after eSIM swap",
        "New iPhone won't activate, no service",
        "SIM provisioned but no signal after port",
        "Device activated but calls drop immediately",
        "Trade-in complete but service not restored",
        "Number transfer failed mid-activation",
    ],
    "pending_order": [
        "Prior order blocking the new upgrade",
        "Pending order won't release for 48 hours",
        "Customer can't add a line, order on hold",
        "Upgrade stuck in pending approval",
        "Order system showing duplicate open order",
        "Credit check order still pending after 3 days",
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
    ],
    "occ": [
        "Customer requesting activation fee waiver for new line",
        "Bill credit request for service outage last month",
        "Courtesy credit for porting delay beyond 24 hours",
        "Credit for missed installation appointment",
        "Requesting waiver of international roaming overage",
        "Account credit for equipment arrived damaged",
        "Goodwill credit for multiple dropped calls",
    ],
    "billing": [
        "First bill higher than quoted in store",
        "Unexpected proration charge this cycle",
        "Autopay discount not reflected on bill",
        "Taxes seem higher than expected",
        "Payment posted but balance not updated",
    ],
    "other": [
        "Watch face won't rename after update",
        "eSIM QR prints upside down on old sales terminal",
        "Scam-likely label on customer's calls",
        "Voicemail greeting stuck in loop",
        "App crashing on device after OS update",
    ],
}

GAP_POOL: dict[str, list[tuple[str, GapType]]] = {
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

REPS  = [f"rep.{n}" for n in ("alvarez", "chen", "patel", "okafor", "santos", "kim", "rodriguez", "nguyen")]
TIER2 = ["tier2.alice", "tier2.marcus", "tier2.deepa"]


# --------------------------------------------------------------------------- #
# Volume & holiday helpers
# --------------------------------------------------------------------------- #

# US holidays in range; each entry: (date, post_holiday_window_days, peak_mult_day1)
HOLIDAYS = [
    (date(2026,  1,  1), 7,  3.0),   # New Year's Day — biggest promo spike
    (date(2026,  1, 19), 3,  1.8),   # MLK Jr. Day weekend
    (date(2026,  2, 16), 4,  2.0),   # Presidents' Day
    (date(2026,  4,  5), 5,  2.2),   # Easter Sunday
    (date(2026,  5, 10), 4,  2.4),   # Mother's Day
    (date(2026,  5, 25), 5,  2.8),   # Memorial Day — second-biggest spike
]

# Monday=0 … Sunday=6
DOW_MULT = {0: 0.75, 1: 0.85, 2: 0.90, 3: 1.05, 4: 1.50, 5: 1.60, 6: 0.35}

# Gentle seasonal ramp (Jan is low post-holiday, May/Jun picks up)
MONTH_MULT = {1: 0.90, 2: 0.93, 3: 0.96, 4: 1.00, 5: 1.06, 6: 1.10}


def _holiday_boost(d: date) -> float:
    """Decay from peak on day 1 to 1.0 by day window+1."""
    for holiday, window, peak in HOLIDAYS:
        delta = (d - holiday).days
        if 1 <= delta <= window:
            return 1.0 + (peak - 1.0) * (window - delta + 1) / window
    return 1.0


def _daily_volume(d: date) -> int:
    base  = 17.0
    vol   = base * DOW_MULT[d.weekday()] * _holiday_boost(d) * MONTH_MULT.get(d.month, 1.0)
    noise = random.uniform(0.88, 1.14)
    return max(2, round(vol * noise))


def _post_holiday(d: date) -> bool:
    return _holiday_boost(d) > 1.05


# --------------------------------------------------------------------------- #
# Intent / outcome helpers
# --------------------------------------------------------------------------- #

def _pick_intent(ph: bool) -> str:
    keys    = list(INTENTS)
    weights = [INTENTS[k][1 if ph else 0] for k in keys]
    return random.choices(keys, weights=weights)[0]


def _outcome(intent: str) -> str:
    """resolved_confirm | resolved_direct | declined | escalated."""
    r = random.random()
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
    return "escalated"   # other


# --------------------------------------------------------------------------- #
# Ticket builder (appends to a list; bulk-inserted later)
# --------------------------------------------------------------------------- #

def _make_ticket(lst: list[Ticket], tkt_id: str, intent: str, created: datetime, rep: str) -> None:
    summary  = random.choice(SUMMARIES[intent])
    fate     = random.random()
    common: dict = dict(
        id=tkt_id,
        created_at=created,
        rep_id=rep,
        thread_id=f"ytd-tkt-{uuid.uuid4().hex[:8]}",
        intent=intent,
        priority="high" if intent in ("activation", "pending_order") else "normal",
        summary=summary,
        conversation=[{"role": "user", "content": summary}],
    )

    if fate < 0.25:                         # still open
        lst.append(Ticket(status=TicketStatus.OPEN, updated_at=created, **common))
        return

    if fate < 0.35:                         # in review
        lst.append(Ticket(status=TicketStatus.IN_REVIEW, updated_at=created,
                          assigned_to=random.choice(TIER2), **common))
        return

    res_at   = created + timedelta(hours=round(random.uniform(0.5, 48), 1))
    gap_pool = GAP_POOL[intent]

    if fate < 0.43:                         # closed — no gap
        lst.append(Ticket(
            status=TicketStatus.CLOSED,
            resolution_notes="Handled one-off; no capability gap identified.",
            root_cause_category=summary,
            recommended_capability=None,
            gap_type=GapType.NONE,
            resolved_by=random.choice(TIER2),
            resolved_at=res_at,
            updated_at=res_at,
            **common,
        ))
        return

    cap, gap = random.choice(gap_pool)      # resolved with a real gap
    lst.append(Ticket(
        status=TicketStatus.RESOLVED,
        resolution_notes="Root cause identified and added to capability backlog.",
        root_cause_category=summary,
        recommended_capability=cap,
        gap_type=gap,
        resolved_by=random.choice(TIER2),
        resolved_at=res_at,
        updated_at=res_at,
        **common,
    ))


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
START_DATE = date(2026, 1, 1)
END_DATE   = date(2026, 6, 15)


def seed() -> dict:
    reset_demo()

    tickets:     list[Ticket]     = []
    engagements: list[Engagement] = []
    n_interactions = n_tickets = 0

    d = START_DATE
    while d <= END_DATE:
        n_convos = _daily_volume(d)
        ph       = _post_holiday(d)

        for _ in range(n_convos):
            intent = _pick_intent(ph)
            _, _, (c_lo, c_hi), capability = INTENTS[intent]
            conf   = round(random.uniform(c_lo, c_hi), 2)
            rep    = random.choice(REPS)
            thread = f"ytd-{d.isoformat()}-{uuid.uuid4().hex[:6]}"
            ts     = datetime(
                d.year, d.month, d.day,
                random.randint(9, 19), random.randint(0, 59), random.randint(0, 59),
                tzinfo=timezone.utc,
            )
            outcome = _outcome(intent)
            n_interactions += 1

            if outcome in ("resolved_confirm", "declined"):
                approved = outcome == "resolved_confirm"
                engagements.append(Engagement(
                    created_at=ts, thread_id=thread, rep_id=rep, kind="message",
                    intent=intent, confidence=conf,
                    status="needs_confirmation", resolution_status=None, capability=None,
                ))
                engagements.append(Engagement(
                    created_at=ts + timedelta(seconds=random.randint(4, 45)),
                    thread_id=thread, rep_id=rep, kind="confirmation",
                    intent=intent, confidence=conf, status="answered",
                    resolution_status="resolved" if approved else "cancelled",
                    capability=capability, confirmed=approved,
                ))

            elif outcome == "resolved_direct":
                engagements.append(Engagement(
                    created_at=ts, thread_id=thread, rep_id=rep, kind="message",
                    intent=intent, confidence=conf,
                    status="answered", resolution_status="resolved", capability=capability,
                ))

            else:  # escalated
                tkt_id = "TCK-" + uuid.uuid4().hex[:8].upper()
                n_tickets += 1
                _make_ticket(tickets, tkt_id, intent, ts, rep)
                engagements.append(Engagement(
                    created_at=ts, thread_id=thread, rep_id=rep, kind="message",
                    intent=intent, confidence=conf,
                    status="escalated", resolution_status="escalated",
                    capability="human-tier-2", ticket_id=tkt_id,
                ))

        d += timedelta(days=1)

    # Single transaction for each table — orders of magnitude faster than per-row commits
    with Session(_engine) as s:
        for t in tickets:
            s.add(t)
        for e in engagements:
            s.add(e)
        s.commit()

    return {"interactions": n_interactions, "tickets": n_tickets, "engagements": len(engagements)}


if __name__ == "__main__":
    print(f"Seeding {START_DATE} → {END_DATE} …")
    result = seed()
    print(f"Inserted {result['interactions']} conversations "
          f"({result['engagements']} engagement rows, {result['tickets']} tickets)\n")

    m = metrics_overview()
    print(f"  conversations      : {m['engagement']['conversations']}")
    print(f"  interactions       : {m['engagement']['interactions']}")
    print(f"  active reps        : {m['engagement']['active_reps']}")
    print(f"  containment rate   : {m['outcomes']['containment_rate']:.0%}")
    print(f"  escalation rate    : {m['outcomes']['escalation_rate']:.0%}")
    print(f"  confirm approval   : {m['confirmations']['approval_rate']:.0%}")
    print(f"  open tickets       : {m['tickets']['open']}")
    print(f"  avg resolution hrs : {m['tickets']['avg_resolution_hours']}")
    print()
    print("Intent breakdown:")
    for it in m["intents"]:
        pct = it["auto_resolved"] / it["count"] if it["count"] else 0
        print(f"  {it['intent']:20s} {it['count']:5d} convos  {pct:.0%} contained")
