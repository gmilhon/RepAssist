"""Contract test for the Activation Resolver integration.

It exercises the SAMPLE real agent (app.sample_agent) through its TestClient and
asserts the adapter correctly translates the vendor contract into our internal
contract — and that the orchestrator, with the adapter enabled, drives the real
agent end-to-end. This test breaks if either the vendor's shape OR the
translation changes, which is exactly what a contract test should guard.

Run with:  pytest -q
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.integrations import activation_adapter
from app.sample_agent.main import app as sample_app
from app.schemas import DiagnoseRequest, ProposedAction

_sample = TestClient(sample_app)


def _route_to_sample(path: str, payload: dict) -> dict:
    """Send the adapter's HTTP call to the sample agent's in-process TestClient."""
    r = _sample.post(path, json=payload, headers={"Authorization": "Bearer test-token"})
    r.raise_for_status()
    return r.json()


# ---- the sample agent enforces auth, like a real internal service ----
def test_sample_agent_requires_bearer_token():
    r = _sample.post("/v2/activation/analyze", json={"lineId": "ACT-1001"})
    assert r.status_code == 401


# ---- translation: remediable fault -> internal proposed action ----
def test_adapter_maps_remediable_fault(monkeypatch):
    monkeypatch.setattr(activation_adapter, "_post", _route_to_sample)
    resp = activation_adapter.diagnose(DiagnoseRequest(order_id="ACT-1001"))
    assert resp.can_resolve is True
    assert resp.proposed_action is not None
    assert resp.proposed_action.service == "activation"
    assert resp.proposed_action.operation == "RESEND_PROVISIONING"
    assert resp.proposed_action.params["ref"].startswith("rem_")
    assert "SIM" in (resp.root_cause or "")


# ---- translation: non-remediable fault -> escalation ----
def test_adapter_maps_non_remediable_to_escalation(monkeypatch):
    monkeypatch.setattr(activation_adapter, "_post", _route_to_sample)
    resp = activation_adapter.diagnose(DiagnoseRequest(order_id="ACT-1002"))
    assert resp.can_resolve is False
    assert resp.proposed_action is None
    assert "port" in (resp.root_cause or "").lower()


# ---- translation: remediate success -> internal execute response ----
def test_adapter_maps_execute_success(monkeypatch):
    monkeypatch.setattr(activation_adapter, "_post", _route_to_sample)
    action = ProposedAction(
        service="activation",
        operation="RESEND_PROVISIONING",
        params={"lineId": "ACT-1001", "ref": "rem_act-1001"},
        human_prompt="Re-send provisioning?",
    )
    out = activation_adapter.execute(action)
    assert out.success is True
    assert any("Active" in step for step in out.actions_taken)


# ---- end to end: orchestrator routes the real adapter when enabled ----
def test_graph_uses_real_activation_agent(monkeypatch):
    monkeypatch.setattr(get_settings(), "activation_agent_url", "http://sample-activation")
    monkeypatch.setattr(activation_adapter, "_post", _route_to_sample)

    from app.graph import orchestrator

    thread = f"adapter-{uuid.uuid4().hex[:8]}"
    res = orchestrator.start_or_continue(thread, "Order ACT-1001 is stuck in activation")
    assert res["status"] == "needs_confirmation"
    assert res["confirmation"]["action"]["operation"] == "RESEND_PROVISIONING"

    done = orchestrator.resume(thread, approved=True)
    assert done["card"]["status"] == "resolved"
    assert any("Active" in a for a in done["card"]["actions_taken"])
