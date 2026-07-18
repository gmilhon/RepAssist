"""Offline tests for the Live Listen watcher (endpoints + mock analysis).

No servers or API key required: the LLM layer runs in mock mode and
agents_client.diagnose degrades to its in-process stub. Run with:  pytest -q
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app import llm
from app.main import app
from app.store import db

client = TestClient(app)


def _start_session(mode: str = "demo", **checkin) -> dict:
    entry, _ = db.create_queue_entry(**checkin)
    res = client.post("/api/listen/start", json={
        "rep_id": "rep.demo", "queue_entry_id": entry.id, "mode": mode,
    })
    assert res.status_code == 200
    return res.json()


# ---- start: claims the queue entry and hands back the entity pre-fill ----
def test_start_claims_queue_entry_and_returns_entities():
    entry, _ = db.create_queue_entry(
        customer_name="Dana Fox", customer_phone="5551234567", reason="support",
    )
    res = client.post("/api/listen/start", json={
        "rep_id": "rep.demo", "queue_entry_id": entry.id, "mode": "demo",
    })
    assert res.status_code == 200
    body = res.json()
    assert body["session"]["status"] == "active"
    assert body["session"]["mode"] == "demo"
    assert body["session"]["queue_entry_id"] == entry.id
    assert body["thread_id"].startswith("thr-")
    assert body["entities"] == {
        "visit_reason": "support",
        "customer_name": "Dana Fox",
        "customer_phone": "5551234567",
    }
    claimed = db.get_queue_entry(entry.id)
    assert claimed.status == "in_progress"
    assert claimed.thread_id == body["thread_id"]

    bogus = client.post("/api/listen/start", json={
        "rep_id": "rep.demo", "queue_entry_id": "Q-NOPE", "mode": "mic",
    })
    assert bogus.status_code == 404


# ---- analyze: offline mock surfaces cards, dedupes intents, enriches ids ----
def test_analyze_surfaces_activation_then_promo_without_duplicates():
    start = _start_session(customer_name="J. Rivera", reason="support")
    sid = start["session"]["id"]

    res = client.post(f"/api/listen/{sid}/analyze", json={"utterances": [
        {"speaker": "Customer", "text": "My new phone still won't activate."},
        {"speaker": "Rep", "text": "Let me look — the order is ACT-1002."},
    ]})
    assert res.status_code == 200
    suggestions = res.json()["suggestions"]
    assert len(suggestions) == 1
    s = suggestions[0]
    assert s["intent"] == "activation"
    assert s["tone"] == "danger"
    assert s["capability"] == "activation-resolver"
    assert s["entities"]["order_id"] == "ACT-1002"
    assert "ACT-1002" in s["prompt"]
    # ACT-1002 is the stub's non-remediable magic id: carrier port blocked.
    assert s["diagnosis"] is not None
    assert s["diagnosis"]["can_resolve"] is False
    assert s["diagnosis"]["human_prompt"] is None

    # More activation talk must not re-surface the same intent.
    res2 = client.post(f"/api/listen/{sid}/analyze", json={"utterances": [
        {"speaker": "Customer", "text": "It's still not activating, no service at all."},
    ]})
    assert res2.status_code == 200
    assert res2.json()["suggestions"] == []

    # A promo mention with an account id surfaces a second, different card.
    res3 = client.post(f"/api/listen/{sid}/analyze", json={"utterances": [
        {"speaker": "Customer", "text": "Also my promo never applied, on account AC-5003."},
    ]})
    assert res3.status_code == 200
    sugg3 = res3.json()["suggestions"]
    assert len(sugg3) == 1
    assert sugg3[0]["intent"] == "promo"
    assert sugg3[0]["entities"]["account_id"] == "AC-5003"
    # AC-5003 is not magic on the promo path — the stub proposes a re-apply.
    assert sugg3[0]["diagnosis"]["can_resolve"] is True
    assert sugg3[0]["diagnosis"]["human_prompt"]

    assert client.post("/api/listen/LS-NOPE/analyze", json={"utterances": [
        {"speaker": None, "text": "hello"},
    ]}).status_code == 404


# ---- stop: recap counts + ended sessions reject further analysis ----
def test_stop_returns_recap_and_blocks_further_analysis():
    start = _start_session(customer_phone="5559871234", reason="upgrade")
    sid = start["session"]["id"]

    client.post(f"/api/listen/{sid}/analyze", json={"utterances": [
        {"speaker": None, "text": "The bill looks way higher than last month."},
    ]})

    res = client.post(f"/api/listen/{sid}/stop")
    assert res.status_code == 200
    body = res.json()
    assert body["session"]["status"] == "ended"
    assert body["session"]["ended_at"]
    assert body["recap"]["utterances"] == 1
    assert body["recap"]["suggestions"] == 1
    assert body["recap"]["duration_label"]

    after = client.post(f"/api/listen/{sid}/analyze", json={"utterances": [
        {"speaker": None, "text": "one more thing"},
    ]})
    assert after.status_code == 409

    assert client.post("/api/listen/LS-NOPE/stop").status_code == 404


# ---- input bounds: empty batch is a no-op; oversized input is rejected ----
def test_analyze_rejects_empty_and_oversized_input():
    start = _start_session(customer_phone="5550001111", reason="support")
    sid = start["session"]["id"]

    # An empty / whitespace-only batch neither appends nor runs an LLM pass.
    empty = client.post(f"/api/listen/{sid}/analyze", json={"utterances": [
        {"speaker": None, "text": "   "},
    ]})
    assert empty.status_code == 200
    assert empty.json()["suggestions"] == []
    assert client.post(f"/api/listen/{sid}/stop").json()["recap"]["utterances"] == 0

    start2 = _start_session(customer_phone="5550002222", reason="support")
    sid2 = start2["session"]["id"]
    # Per-utterance char cap and per-call count cap are enforced by validation.
    assert client.post(f"/api/listen/{sid2}/analyze", json={"utterances": [
        {"speaker": None, "text": "x" * 5000},
    ]}).status_code == 422
    assert client.post(f"/api/listen/{sid2}/analyze", json={"utterances": [
        {"speaker": None, "text": "hi"} for _ in range(60)
    ]}).status_code == 422


# ---- mock unit: multi-intent windows, prior-intent dedupe, confidences ----
def test_mock_analyze_multi_intent_respects_prior_intents():
    window = (
        "Customer: My phone won't activate, order ACT-1001.\n"
        "Customer: And my bill has a weird charge on it."
    )
    result = llm._mock_analyze_live_transcript(window, prior_intents=[])
    by_intent = {s.intent: s for s in result.suggestions}
    assert set(by_intent) == {"activation", "billing"}
    # Confidences mirror _mock_classify's per-family values.
    assert by_intent["activation"].confidence == 0.82
    assert by_intent["billing"].confidence == 0.7
    assert by_intent["activation"].tone == "danger"
    assert by_intent["activation"].order_id == "ACT-1001"

    repeat = llm._mock_analyze_live_transcript(window, prior_intents=["activation"])
    assert {s.intent for s in repeat.suggestions} == {"billing"}
