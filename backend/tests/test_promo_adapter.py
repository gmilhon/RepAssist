"""Contract test for the Promo Correction Agent integration.

Mirrors the activation adapter test, but the promo agent uses a different
contract and an X-Api-Key header — proving the adapter pattern generalizes.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.integrations import promo_adapter
from app.sample_agent.main import app as sample_app
from app.schemas import DiagnoseRequest, ProposedAction

_sample = TestClient(sample_app)


def _route_to_sample(path: str, payload: dict) -> dict:
    r = _sample.post(path, json=payload, headers={"X-Api-Key": "test-key"})
    r.raise_for_status()
    return r.json()


def test_promo_agent_requires_api_key():
    r = _sample.post("/promo-svc/v1/evaluate", json={"accountId": "AC-3003"})
    assert r.status_code == 401


def test_adapter_maps_eligible_not_applied(monkeypatch):
    monkeypatch.setattr(promo_adapter, "_post", _route_to_sample)
    resp = promo_adapter.diagnose(DiagnoseRequest(account_id="AC-3003"))
    assert resp.can_resolve is True
    assert resp.proposed_action is not None
    assert resp.proposed_action.service == "promo"
    assert resp.proposed_action.operation == "REAPPLY_CREDIT"
    assert resp.proposed_action.params["promoCode"] == "BOGO-2026"
    assert resp.proposed_action.params["fixToken"].startswith("fix_")


def test_adapter_maps_ineligible_to_no_change(monkeypatch):
    monkeypatch.setattr(promo_adapter, "_post", _route_to_sample)
    resp = promo_adapter.diagnose(DiagnoseRequest(account_id="AC-3004"))
    assert resp.can_resolve is True
    assert resp.proposed_action is None
    assert "not eligible" in resp.summary.lower()


def test_adapter_apply_success(monkeypatch):
    monkeypatch.setattr(promo_adapter, "_post", _route_to_sample)
    action = ProposedAction(
        service="promo", operation="REAPPLY_CREDIT",
        params={"accountId": "AC-3003", "fixToken": "fix_ac-3003", "promoCode": "BOGO-2026"},
        human_prompt="Re-apply?",
    )
    out = promo_adapter.execute(action)
    assert out.success is True
    assert any("BOGO-2026" in step for step in out.actions_taken)


def test_graph_uses_real_promo_agent(monkeypatch):
    monkeypatch.setattr(get_settings(), "promo_agent_url", "http://sample-promo")
    monkeypatch.setattr(promo_adapter, "_post", _route_to_sample)

    from app.graph import orchestrator

    # eligible-not-applied -> confirmation -> resolved
    thread = f"promo-{uuid.uuid4().hex[:8]}"
    res = orchestrator.start_or_continue(thread, "Account AC-3003 is missing their BOGO promo credit")
    assert res["status"] == "needs_confirmation"
    assert res["confirmation"]["action"]["operation"] == "REAPPLY_CREDIT"
    done = orchestrator.resume(thread, approved=True)
    assert done["card"]["status"] == "resolved"

    # ineligible -> resolved with no change (no ticket)
    thread2 = f"promo-{uuid.uuid4().hex[:8]}"
    res2 = orchestrator.start_or_continue(thread2, "Account AC-3004 is missing their BOGO promo")
    assert res2["status"] == "answered"
    assert res2["card"]["status"] == "resolved"
