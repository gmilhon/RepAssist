"""Contract test for the external CES relay integration.

Exercises the whole feature offline — no GCP creds, no live CES call:
`ces_client` runs in stub mode and `enabled()` is forced on by pointing
`CES_DEPLOYMENT` at a placeholder (the same trick `test_activation_adapter`
uses for `activation_agent_url`). Covers:

  * per-intent routing driven live by the `ces_routes` table (Settings policy),
  * the `ces_remote` node relaying + surfacing the reply verbatim,
  * sticky multi-turn continuation and the hand-back exit,
  * off-by-default when no deployment is configured,
  * the Settings GET/POST API.

Assertions key off the CURRENT turn's `card.capability` rather than the graph
`trace`, because `trace` accumulates across turns (operator.add + checkpointer).

Run with:  pytest -q
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.graph import orchestrator
from app.integrations import ces_client
from app.main import app
from app.store import db

_client = TestClient(app)
_PLACEHOLDER_DEP = "projects/test-494103/locations/us/apps/demo/deployments/demo"
_ALL_ROUTABLE = ("activation", "pending_order", "promo", "occ", "billing", "general", "other")


def _thread() -> str:
    return f"cestest-{uuid.uuid4().hex[:8]}"


def _ces_routed(res: dict) -> bool:
    """Did THIS turn get relayed to CES? True iff the reply card is CES-sourced."""
    card = res.get("card") or {}
    return str(card.get("capability") or "").startswith("CES")


@pytest.fixture
def ces_on(monkeypatch):
    """Enable the feature offline: a placeholder deployment + stubbed replies.
    monkeypatch auto-reverts both after the test, so other suites see it off."""
    monkeypatch.setattr(get_settings(), "ces_deployment", _PLACEHOLDER_DEP)
    monkeypatch.setattr(get_settings(), "ces_stub", True)
    return _PLACEHOLDER_DEP


@pytest.fixture(autouse=True)
def clean_routes():
    """Routing policy lives in the shared sqlite file — clear the intents this
    suite toggles, before and after, so a stray row never leaks into the demo."""
    for intent in _ALL_ROUTABLE:
        db.set_ces_route(intent, False, "")
    yield
    for intent in _ALL_ROUTABLE:
        db.set_ces_route(intent, False, "")


# ---- per-intent routing: ON relays to CES -------------------------------------
def test_billing_routes_to_ces_when_enabled(ces_on):
    db.set_ces_route("billing", True)
    res = orchestrator.start_or_continue(
        _thread(), "The customer sees an overcharge on their bill"
    )
    assert res["status"] == "answered"
    assert _ces_routed(res)
    assert res["card"]["capability"] == "CES · repAssist"
    # the relayed reply is surfaced verbatim (stub marker), NOT re-voiced by compose
    assert res["assistant_message"].startswith("[CES · repAssist")


# ---- per-intent routing: OFF uses the built-in path ---------------------------
def test_billing_falls_back_to_builtin_when_disabled(ces_on):
    db.set_ces_route("billing", False)
    res = orchestrator.start_or_continue(
        _thread(), "The customer sees an overcharge on their bill"
    )
    # billing → built-in knowledge/ticket path, never CES
    assert not _ces_routed(res)
    assert not (res["assistant_message"] or "").startswith("[CES")


# ---- off by default: no deployment configured => never routes -----------------
def test_off_by_default_without_deployment():
    assert ces_client.enabled() is False
    db.set_ces_route("billing", True)  # toggled on, but the feature gate is off
    res = orchestrator.start_or_continue(
        _thread(), "The customer sees an overcharge on their bill"
    )
    assert not _ces_routed(res)


# ---- entry sub-agent is relayed and reflected in the source label -------------
def test_entry_agent_relayed(ces_on):
    db.set_ces_route("billing", True, "Billing")
    res = orchestrator.start_or_continue(_thread(), "wrong charge on the bill")
    assert res["card"]["capability"] == "CES · repAssist · Billing"


# ---- sticky multi-turn continuation, then hand-back ---------------------------
def test_sticky_continuation_and_handback(ces_on):
    db.set_ces_route("activation", True)
    thread = _thread()

    r1 = orchestrator.start_or_continue(thread, "The line won't activate, no service")
    assert _ces_routed(r1)

    # A bare follow-up classifies as low-confidence 'other' on its own, but the
    # sticky flag keeps the thread on CES.
    r2 = orchestrator.start_or_continue(thread, "The customer's name is John Smith")
    assert _ces_routed(r2)

    # Explicit hand-back clears the sticky flag → Rep Assist handles the thread.
    r3 = orchestrator.start_or_continue(thread, "back to rep assist — what's new?")
    assert not _ces_routed(r3)


# ---- Settings API: read the policy + connection status ------------------------
def test_settings_get_lists_routable_intents(ces_on):
    r = _client.get("/api/settings/ces-routing")
    assert r.status_code == 200
    body = r.json()
    assert body["configured"] is True
    assert body["stubbed"] is True
    intents = {i["intent"] for i in body["intents"]}
    assert {"billing", "activation", "general"} <= intents
    assert "system" not in intents  # SYSTEM is never routable
    # activation has a built-in resolver; general does not
    by_intent = {i["intent"]: i for i in body["intents"]}
    assert by_intent["activation"]["has_resolver"] is True
    assert by_intent["general"]["has_resolver"] is False
    assert "Billing" in body["entry_agents"]


# ---- Settings API: POST toggles a route, rejects bad input --------------------
def test_settings_post_toggles_and_validates(ces_on):
    ok = _client.post(
        "/api/settings/ces-routing",
        json={"intent": "billing", "enabled": True, "entry_agent": "Billing"},
    )
    assert ok.status_code == 200
    assert "billing" in db.ces_enabled_intents()
    assert db.ces_routes()["billing"].entry_agent == "Billing"

    # unknown/non-routable intent rejected
    assert _client.post("/api/settings/ces-routing", json={"intent": "system", "enabled": True}).status_code == 422
    # unknown entry agent rejected
    assert _client.post(
        "/api/settings/ces-routing",
        json={"intent": "billing", "enabled": True, "entry_agent": "Nope"},
    ).status_code == 422
