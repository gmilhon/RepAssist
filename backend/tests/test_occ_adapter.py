"""Contract tests for the OCC (Other Charges and Credits) agent integration.

Same pattern as test_activation_adapter.py and test_promo_adapter.py:
  - The vendor contract is pinned by calling the sample agent via a TestClient
    (no real HTTP; monkeypatch routes _post there).
  - Translation functions are tested in isolation (pure functions).
  - One end-to-end graph test verifies the full eligible → confirm → resolved
    and ineligible → escalated paths.

Scenarios (keyed on account ID in the sample agent):
  AC-5001  ACTIVATION_FEE_WAIVER, $35, AUTO    → proposed action
  AC-5002  BILL_CREDIT, $50, MANAGER_REQUIRED  → proposed action with manager note
  AC-5003  not eligible                         → escalated to ticket
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.integrations import occ_adapter
from app.sample_agent.main import app as sample_app
from app.schemas import DiagnoseRequest, ProposedAction

_sample = TestClient(sample_app)


def _route_to_sample(path: str, payload: dict) -> dict:
    r = _sample.post(path, json=payload, headers={"Authorization": "Bearer test-token"})
    r.raise_for_status()
    return r.json()


# --------------------------------------------------------------------------- #
# Vendor contract: auth enforcement
# --------------------------------------------------------------------------- #
def test_occ_agent_requires_bearer_token():
    r = _sample.post("/occ/v1/evaluate", json={"accountId": "AC-5001"})
    assert r.status_code == 401


# --------------------------------------------------------------------------- #
# Translation: diagnose
# --------------------------------------------------------------------------- #
def test_adapter_maps_activation_fee_waiver_eligible(monkeypatch):
    monkeypatch.setattr(occ_adapter, "_post", _route_to_sample)
    resp = occ_adapter.diagnose(DiagnoseRequest(account_id="AC-5001"))
    assert resp.can_resolve is True
    assert resp.proposed_action is not None
    assert resp.proposed_action.service == "occ"
    assert resp.proposed_action.operation == "ACTIVATION_FEE_WAIVER"
    assert resp.proposed_action.params["amount"] == 35.00
    assert resp.proposed_action.params["creditType"] == "ACTIVATION_FEE_WAIVER"
    assert "$35.00" in resp.proposed_action.human_prompt
    assert "manager" not in resp.proposed_action.human_prompt.lower()


def test_adapter_maps_bill_credit_manager_required(monkeypatch):
    monkeypatch.setattr(occ_adapter, "_post", _route_to_sample)
    resp = occ_adapter.diagnose(DiagnoseRequest(account_id="AC-5002"))
    assert resp.can_resolve is True
    assert resp.proposed_action is not None
    assert resp.proposed_action.operation == "BILL_CREDIT"
    assert resp.proposed_action.params["amount"] == 50.00
    assert "manager" in resp.proposed_action.human_prompt.lower()


def test_adapter_maps_ineligible_to_no_resolve(monkeypatch):
    monkeypatch.setattr(occ_adapter, "_post", _route_to_sample)
    resp = occ_adapter.diagnose(DiagnoseRequest(account_id="AC-5003"))
    assert resp.can_resolve is False
    assert resp.proposed_action is None
    assert "30" in resp.summary or "window" in resp.summary.lower()


# --------------------------------------------------------------------------- #
# Translation: execute (apply)
# --------------------------------------------------------------------------- #
def test_adapter_apply_activation_fee_waiver(monkeypatch):
    monkeypatch.setattr(occ_adapter, "_post", _route_to_sample)
    action = ProposedAction(
        service="occ",
        operation="ACTIVATION_FEE_WAIVER",
        params={
            "accountId": "AC-5001",
            "creditType": "ACTIVATION_FEE_WAIVER",
            "amount": 35.00,
            "applyToken": "occ_ac-5001_act_fee",
        },
        human_prompt="Apply $35.00 Activation Fee Waiver to account AC-5001?",
    )
    out = occ_adapter.execute(action)
    assert out.success is True
    assert "35" in out.summary
    assert len(out.actions_taken) >= 1


def test_adapter_apply_bill_credit(monkeypatch):
    monkeypatch.setattr(occ_adapter, "_post", _route_to_sample)
    action = ProposedAction(
        service="occ",
        operation="BILL_CREDIT",
        params={
            "accountId": "AC-5002",
            "creditType": "BILL_CREDIT",
            "amount": 50.00,
            "applyToken": "occ_ac-5002_bill",
        },
        human_prompt="Apply $50.00 Bill Credit to account AC-5002? (Requires manager authorization.)",
    )
    out = occ_adapter.execute(action)
    assert out.success is True
    assert any("50" in step for step in out.actions_taken)


# --------------------------------------------------------------------------- #
# End-to-end: graph dispatches to real OCC agent
# --------------------------------------------------------------------------- #
def test_graph_uses_real_occ_agent(monkeypatch):
    monkeypatch.setattr(get_settings(), "occ_agent_url", "http://sample-occ")
    monkeypatch.setattr(occ_adapter, "_post", _route_to_sample)

    from app.graph import orchestrator

    # Eligible → needs_confirmation → approved → resolved
    thread = f"occ-{uuid.uuid4().hex[:8]}"
    res = orchestrator.start_or_continue(
        thread, "Customer AC-5001 wants to waive the activation fee"
    )
    assert res["status"] == "needs_confirmation"
    assert res["confirmation"]["action"]["operation"] == "ACTIVATION_FEE_WAIVER"
    assert res["confirmation"]["action"]["params"]["amount"] == 35.00

    done = orchestrator.resume(thread, approved=True)
    assert done["card"]["status"] == "resolved"
    assert done["card"]["capability"] == "occ-credit-agent"

    # Ineligible → escalated to ticket
    thread2 = f"occ-{uuid.uuid4().hex[:8]}"
    res2 = orchestrator.start_or_continue(
        thread2, "Customer AC-5003 is asking to waive the activation fee"
    )
    assert res2["status"] == "escalated"
    assert res2["ticket_id"] is not None
