"""Tests for the operational metrics aggregation."""
from __future__ import annotations

from app.store import db


def test_metrics_overview_aggregates_engagements():
    db.reset_demo()

    # billing resolved directly from the KB (no confirmation)
    db.record_engagement(thread_id="t1", rep_id="r1", kind="message", intent="billing",
                         confidence=0.7, status="answered", resolution_status="resolved",
                         capability="knowledge-base")
    # activation: confirmation requested, then approved + resolved
    db.record_engagement(thread_id="t2", rep_id="r1", kind="message", intent="activation",
                         confidence=0.9, status="needs_confirmation", resolution_status=None)
    db.record_engagement(thread_id="t2", rep_id="r1", kind="confirmation", intent="activation",
                         confidence=0.9, status="answered", resolution_status="resolved",
                         capability="activation-resolver", confirmed=True)
    # unknown -> escalated to a ticket
    db.record_engagement(thread_id="t3", rep_id="r2", kind="message", intent="other",
                         confidence=0.3, status="escalated", resolution_status="escalated",
                         capability="human-tier-2", ticket_id="TCK-X")

    m = db.metrics_overview()

    assert m["engagement"]["conversations"] == 3
    assert m["engagement"]["interactions"] == 3          # message-kind turns
    assert m["engagement"]["active_reps"] == 2
    assert m["outcomes"]["auto_resolved"] == 2
    assert m["outcomes"]["escalated"] == 1
    assert round(m["outcomes"]["containment_rate"], 2) == 0.67
    assert m["confirmations"]["requested"] == 1
    assert m["confirmations"]["approved"] == 1
    caps = {c["capability"] for c in m["capabilities"]}
    assert {"knowledge-base", "activation-resolver"} <= caps
    assert any(i["intent"] == "activation" for i in m["intents"])
