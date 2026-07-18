"""Playbook CRUD + grading + coaching over Live Listen sessions.

Structural assertions only (stars in range, shapes present) so the cases pass
whether the LLM layer is live or in offline-mock mode.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app import llm
from app.main import app
from app.store import db

client = TestClient(app)


def _seed_playbook() -> None:
    db.seed_playbook_defaults_if_empty()


# ---- Playbook guideline CRUD ----
def test_playbook_guideline_crud():
    _seed_playbook()
    before = client.get("/api/playbook/guidelines").json()
    assert isinstance(before, list) and len(before) >= 6

    created = client.post("/api/playbook/guidelines", json={
        "category": "Sales Positioning", "text": "Always offer an accessory bundle.",
    })
    assert created.status_code == 201
    gid = created.json()["id"]

    toggled = client.patch(f"/api/playbook/guidelines/{gid}", json={"active": False})
    assert toggled.status_code == 200 and toggled.json()["active"] is False

    bad = client.post("/api/playbook/guidelines", json={"category": "Nope", "text": "x"})
    assert bad.status_code == 400

    assert client.delete(f"/api/playbook/guidelines/{gid}").status_code == 204
    assert client.patch("/api/playbook/guidelines/999999", json={"active": True}).status_code == 404


# ---- grade at stop + coaching flow ----
def test_stop_grades_and_coaching_flow():
    _seed_playbook()
    entry, _ = db.create_queue_entry(
        customer_name="Devon Marsh", reason="new_service",
        account_id="AC-3002", order_id="ACT-1002",
    )
    start = client.post("/api/listen/start", json={
        "rep_id": "rep.demo", "queue_entry_id": entry.id, "mode": "demo",
    })
    assert start.status_code == 200
    body = start.json()
    # Eligibility resolved from the account and surfaced as opportunities.
    assert "eligibility" in body and isinstance(body["opportunities"], list)
    assert body["eligibility"]["fiber_eligible"] is True
    sid = body["session"]["id"]

    client.post(f"/api/listen/{sid}/analyze", json={"utterances": [
        {"speaker": "Customer", "text": "My new phone won't activate — order ACT-1002."},
        {"speaker": "Rep", "text": "Let me check that, and while you're here — you qualify for Fiber Home Internet."},
    ]})

    stopped = client.post(f"/api/listen/{sid}/stop")
    assert stopped.status_code == 200
    grade = stopped.json()["recap"]["grade"]
    assert grade is not None
    assert 1 <= grade["stars"] <= 5
    assert len(grade["per_guideline"]) >= 6          # one per active guideline
    assert all(k in grade for k in ("headline", "strengths", "gaps"))

    # Coaching card lists the just-graded visit.
    recent = client.get("/api/coaching/recent").json()["elements"][0]
    assert recent["type"] == "coaching"
    assert any(e["session_id"] == sid for e in recent["entries"])
    row = next(e for e in recent["entries"] if e["session_id"] == sid)
    assert 1 <= row["stars"] <= 5

    # Recommendation for that visit.
    rec = client.post(f"/api/coaching/{sid}")
    assert rec.status_code == 200
    coaching = rec.json()["coaching"]
    assert coaching["summary"] and isinstance(coaching["improvements"], list)
    assert coaching["suggested_script"]

    assert client.post("/api/coaching/LS-NOPE").status_code == 404


# ---- offline mock units (always deterministic, independent of LLM mode) ----
def test_mock_grade_penalizes_unpositioned_opportunity():
    guidelines = [
        {"id": 1, "category": "Customer Needs", "text": "Address every issue"},
        {"id": 2, "category": "Sales Positioning", "text": "Position an upgrade"},
    ]
    elig = {"upgrade_promo": "$200 off", "fiber_eligible": False, "fwa_eligible": False}
    # Opportunity exists but the transcript never positions it -> lower score.
    missed = llm._mock_grade_playbook(
        [{"speaker": "Customer", "text": "my phone won't activate"}],
        [{"title": "Activation stuck"}], elig, guidelines,
    )
    # Opportunity positioned -> higher score.
    positioned = llm._mock_grade_playbook(
        [{"speaker": "Customer", "text": "my phone won't activate"},
         {"speaker": "Rep", "text": "you also qualify for an upgrade promo with trade-in"}],
        [{"title": "Activation stuck"}], elig, guidelines,
    )
    assert positioned.stars > missed.stars
    sales = next(p for p in positioned.per_guideline if p.category == "Sales Positioning")
    assert sales.met is True
