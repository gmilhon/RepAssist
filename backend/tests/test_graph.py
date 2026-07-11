"""Offline tests for the orchestration graph.

No servers required: the LLM runs in mock mode (no API key) and the agent
microservices are stubbed via monkeypatch. Run with:  pytest -q
"""
from __future__ import annotations

import uuid

import pytest

from app.graph import nodes, orchestrator
from app.schemas import DiagnoseResponse, ExecuteResponse, ProposedAction


def _thread() -> str:
    return f"test-{uuid.uuid4().hex[:8]}"


@pytest.fixture(autouse=True)
def stub_services(monkeypatch):
    def fake_order_context(order_id, account_id):
        return {"order_id": order_id, "status": "Activation Pending"} if order_id else None

    def fake_diagnose(intent, req):
        return DiagnoseResponse(
            can_resolve=True,
            root_cause="SIM not provisioned",
            summary="Line stuck in activation.",
            proposed_action=ProposedAction(
                service="activation",
                operation="resend_provisioning",
                params={"order_id": req.order_id},
                human_prompt="Re-send provisioning?",
            ),
        )

    def fake_execute(action):
        return ExecuteResponse(
            success=True,
            summary="Line activated.",
            actions_taken=["Re-sent provisioning", "Line is Active"],
        )

    def fake_kb(query):
        return {"hit": True, "article_id": "KB-1042", "answer": "Prorated charges."} \
            if "bill" in query.lower() else None

    monkeypatch.setattr(nodes.agents_client, "order_context", fake_order_context)
    monkeypatch.setattr(nodes.agents_client, "diagnose", fake_diagnose)
    monkeypatch.setattr(nodes.agents_client, "execute", fake_execute)
    monkeypatch.setattr(nodes.agents_client, "kb_search", fake_kb)


def test_activation_requires_confirmation_then_resolves():
    thread = _thread()
    res = orchestrator.start_or_continue(
        thread, "Order ACT-1001 is stuck in activation, the SIM won't activate."
    )
    assert res["status"] == "needs_confirmation"
    assert res["confirmation"]["action"]["operation"] == "resend_provisioning"

    done = orchestrator.resume(thread, approved=True)
    assert done["status"] == "answered"
    assert done["card"]["status"] == "resolved"
    assert "Re-sent provisioning" in done["card"]["actions_taken"]


def test_decline_confirmation_makes_no_change():
    thread = _thread()
    orchestrator.start_or_continue(thread, "ACT-1001 activation is stuck")
    done = orchestrator.resume(thread, approved=False)
    assert done["card"]["status"] == "cancelled"


def test_billing_question_answered_from_ost():
    thread = _thread()
    res = orchestrator.start_or_continue(thread, "Why is the first bill so high / overcharge?")
    assert res["status"] == "answered"
    assert res["card"]["capability"] == "one-source-of-truth"
    # OST returns the answer as a knowledge_article A2UI card.
    assert res["a2ui"] and res["a2ui"][0]["type"] == "knowledge_article"


def test_unknown_issue_escalates_to_ticket():
    thread = _thread()
    res = orchestrator.start_or_continue(thread, "The customer's hotspot name looks weird")
    assert res["status"] == "escalated"
    assert res["ticket_id"]
