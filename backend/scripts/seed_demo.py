"""Seed realistic demo data for the Operations dashboard.

Generates ~10 days of engagement events + tickets (with feedback) so every KPI
is populated. Deterministic (fixed seed). Safe to re-run — it resets first.

    python scripts/seed_demo.py
"""
from __future__ import annotations

import os
import random
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.store import db  # noqa: E402
from app.store.models import GapType, TicketStatus  # noqa: E402

random.seed(42)
NOW = datetime.now(timezone.utc)

# intent -> (weight, confidence range, capability)
INTENTS = {
    "activation":    (28, (0.80, 0.96), "activation-resolver"),
    "pending_order": (18, (0.78, 0.95), "pending-order-resolver"),
    "promo":         (20, (0.74, 0.94), "promo-correction-agent"),
    "billing":       (16, (0.58, 0.86), "knowledge-base"),
    "general":       (8,  (0.50, 0.78), "knowledge-base"),
    "other":         (10, (0.20, 0.42), "human-tier-2"),
}
SUMMARIES = {
    "activation": ["Line stuck in activation after eSIM swap",
                   "New iPhone won't activate, no service", "SIM provisioned but no signal"],
    "pending_order": ["Prior order blocking the new upgrade", "Pending order won't release",
                      "Customer can't add a line, order on hold"],
    "promo": ["BOGO credit never applied", "Trade-in promo missing on bill",
              "Loyalty discount dropped off"],
    "billing": ["First bill higher than quoted", "Unexpected proration charge",
                "Autopay discount not reflected"],
    "general": ["How to transfer content to new device", "Upgrade eligibility question"],
    "other": ["Watch face won't rename", "eSIM QR prints upside down",
              "Scam-likely label on customer's calls", "Voicemail greeting stuck"],
}
# Capabilities Tier 1/2 recommend when they resolve an escalation, by intent.
GAP_POOL = {
    "activation": [("carrier-port-status-agent", GapType.MISSING_AGENT),
                   ("activation-resolver", GapType.AGENT_FAILED)],
    "pending_order": [("credit-hold-resolver", GapType.MISSING_AGENT),
                      ("pending-order-resolver", GapType.AGENT_FAILED)],
    "promo": [("promo-eligibility-explainer", GapType.MISSING_KNOWLEDGE),
              ("promo-correction-agent", GapType.AGENT_FAILED)],
    "billing": [("billing-dispute-agent", GapType.MISSING_AGENT),
                ("billing-knowledge-base", GapType.MISSING_KNOWLEDGE)],
    "general": [("device-howto-kb", GapType.MISSING_KNOWLEDGE)],
    "other": [("wearable-settings-agent", GapType.MISSING_AGENT),
              ("esim-troubleshooter", GapType.MISSING_AGENT),
              ("number-reputation-agent", GapType.MISSING_AGENT)],
}
REPS = [f"rep.{n}" for n in ("alvarez", "chen", "patel", "okafor", "santos", "kim")]
TIER2 = ["tier2.alice", "tier2.marcus", "tier2.deepa"]

# Store check-in queue is live "right now" state, not historical volume — a
# handful of recent fixtures so "View queue" has something to show right
# after a seed. (customer_name, customer_phone, reason, minutes_ago, status)
QUEUE_SAMPLES = [
    # (name, phone, reason, minutes_ago, status, account_id, order_id)
    ("Devon Marsh",  None,               "new_service",  6,  "waiting",     "AC-3002", "ACT-1002"),
    (None,           "(555) 019-2244",   "upgrade",      14, "waiting",     "AC-3003", "ORD-2002"),
    ("Priya Nair",   "(555) 019-7781",   "appointment",  22, "waiting",     "AC-5003", None),
    ("Wes Okonkwo",  None,               "home",         9,  "in_progress", None,      None),
    ("Grace Lin",    "(555) 019-3390",   "pickup",       31, "in_progress", None,      None),
]

_intent_keys = list(INTENTS)
_intent_weights = [INTENTS[k][0] for k in _intent_keys]


def _pick_intent() -> str:
    return random.choices(_intent_keys, weights=_intent_weights)[0]


def _outcome(intent: str) -> str:
    """Return one of: resolved_confirm, resolved_direct, declined, escalated."""
    r = random.random()
    if intent in ("activation", "pending_order"):
        return "resolved_confirm" if r < 0.72 else ("declined" if r < 0.82 else "escalated")
    if intent == "promo":
        if r < 0.55:
            return "resolved_confirm"
        if r < 0.70:
            return "resolved_direct"   # ineligible / no-action answer
        return "declined" if r < 0.80 else "escalated"
    if intent in ("billing", "general"):
        return "resolved_direct" if r < 0.78 else "escalated"
    return "escalated"  # other


def seed() -> dict:
    db.reset_demo()
    n_interactions = 0
    n_tickets = 0

    for day_offset in range(10, -1, -1):
        day = NOW - timedelta(days=day_offset)
        weekday = day.weekday()
        base = random.randint(10, 20) - (6 if weekday >= 5 else 0)  # lighter weekends
        for _ in range(max(3, base)):
            intent = _pick_intent()
            conf_lo, conf_hi = INTENTS[intent][1]
            confidence = round(random.uniform(conf_lo, conf_hi), 2)
            capability = INTENTS[intent][2]
            rep = random.choice(REPS)
            thread = f"seed-{day.strftime('%m%d')}-{random.randint(1000, 9999)}"
            ts = day.replace(hour=random.randint(9, 19), minute=random.randint(0, 59),
                             second=random.randint(0, 59))
            outcome = _outcome(intent)
            n_interactions += 1

            if outcome in ("resolved_confirm", "declined"):
                # message turn requested a confirmation
                db.record_engagement(created_at=ts, thread_id=thread, rep_id=rep, kind="message",
                                      intent=intent, confidence=confidence,
                                      status="needs_confirmation", resolution_status=None, capability=None)
                approved = outcome == "resolved_confirm"
                db.record_engagement(created_at=ts + timedelta(seconds=random.randint(4, 40)),
                                     thread_id=thread, rep_id=rep, kind="confirmation",
                                     intent=intent, confidence=confidence, status="answered",
                                     resolution_status="resolved" if approved else "cancelled",
                                     capability=capability, confirmed=approved)
            elif outcome == "resolved_direct":
                db.record_engagement(created_at=ts, thread_id=thread, rep_id=rep, kind="message",
                                     intent=intent, confidence=confidence, status="answered",
                                     resolution_status="resolved", capability=capability)
            else:  # escalated -> ticket
                ticket = _make_ticket(intent, ts)
                n_tickets += 1
                db.record_engagement(created_at=ts, thread_id=thread, rep_id=rep, kind="message",
                                     intent=intent, confidence=confidence, status="escalated",
                                     resolution_status="escalated", capability="human-tier-2",
                                     ticket_id=ticket)

    n_queue = _seed_queue()
    return {"interactions": n_interactions, "tickets": n_tickets, "queue_entries": n_queue}


def _seed_queue() -> int:
    for name, phone, reason, minutes_ago, status, account_id, order_id in QUEUE_SAMPLES:
        created = NOW - timedelta(minutes=minutes_ago)
        started = NOW - timedelta(minutes=random.randint(1, minutes_ago)) if status == "in_progress" else None
        db.create_queue_entry(
            customer_name=name, customer_phone=phone, reason=reason, status=status,
            account_id=account_id, order_id=order_id,
            assigned_rep_id=random.choice(REPS) if status == "in_progress" else None,
            created_at=created, updated_at=(started or created), started_at=started,
        )
    return len(QUEUE_SAMPLES)


def _make_ticket(intent: str, created: datetime) -> str:
    summary = random.choice(SUMMARIES[intent])
    resolved = random.random() < 0.6
    common = dict(
        rep_id=random.choice(REPS), thread_id=f"seed-tkt-{random.randint(10000, 99999)}",
        intent=intent, priority="high" if intent in ("activation", "pending_order") else "normal",
        summary=summary, conversation=[{"role": "user", "content": summary}],
        created_at=created, updated_at=created,
    )
    if not resolved:
        t = db.create_ticket(status=TicketStatus.OPEN, **common)
        return t.id

    cap, gap = random.choice(GAP_POOL[intent])
    close_only = random.random() < 0.12
    resolved_at = created + timedelta(hours=round(random.uniform(0.5, 40), 1))
    t = db.create_ticket(
        status=TicketStatus.CLOSED if close_only else TicketStatus.RESOLVED,
        resolution_notes="Resolved manually; see notes.",
        root_cause_category=summary,
        recommended_capability=None if close_only else cap,
        gap_type=GapType.NONE if close_only else gap,
        resolved_by=random.choice(TIER2),
        resolved_at=resolved_at,
        **common,
    )
    return t.id


if __name__ == "__main__":
    result = seed()
    print(f"Seeded {result['interactions']} interactions, {result['tickets']} tickets, "
          f"{result['queue_entries']} queue entries.")
    m = db.metrics_overview()
    print(f"  conversations      : {m['engagement']['conversations']}")
    print(f"  containment rate   : {m['outcomes']['containment_rate']:.0%}")
    print(f"  escalation rate    : {m['outcomes']['escalation_rate']:.0%}")
    print(f"  confirm approval   : {m['confirmations']['approval_rate']:.0%}")
    print(f"  open tickets       : {m['tickets']['open']}")
    print(f"  avg resolution hrs : {m['tickets']['avg_resolution_hours']}")
