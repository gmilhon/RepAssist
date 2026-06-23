"""Adapter for a REAL Activation Resolver agent.

This is the template for integrating any existing agent. The orchestrator only
knows our *internal* contract (DiagnoseRequest/Response, ProposedAction,
ExecuteResponse). Real agents speak their own ("vendor") contract. This module:

  1. models the vendor contract (what app/sample_agent speaks),
  2. translates internal -> vendor on the way in,
  3. calls the vendor over HTTP with auth,
  4. translates vendor -> internal on the way out.

Enable it by setting ACTIVATION_AGENT_URL (+ ACTIVATION_AGENT_TOKEN). When unset,
agents_client falls back to the built-in mock — so this is a pure config toggle.
The translation functions are pure and individually unit-tested
(see backend/tests/test_activation_adapter.py) — that's the contract test.
"""
from __future__ import annotations

import logging

import httpx
from pydantic import BaseModel

from ..config import get_settings
from ..schemas import (
    DiagnoseRequest,
    DiagnoseResponse,
    ExecuteResponse,
    ProposedAction,
)

logger = logging.getLogger("repassist.activation_adapter")


# --------------------------------------------------------------------------- #
# Vendor contract (what the real/sample Activation Resolver returns)
# --------------------------------------------------------------------------- #
class _Remediation(BaseModel):
    action: str
    label: str
    ref: str


class VendorAnalyze(BaseModel):
    lineId: str | None = None
    state: str
    faultCode: str | None = None
    analysis: str
    remediation: _Remediation | None = None


class VendorRemediate(BaseModel):
    ok: bool
    state: str
    steps: list[str] = []


# Human-readable text for the vendor's fault codes.
FAULT_TEXT = {
    "SIM_NOT_PUSHED": "SIM/eSIM profile was never pushed to the network.",
    "CARRIER_PORT": "Number port from the losing carrier has not completed.",
}


def enabled() -> bool:
    """True when a real Activation Resolver URL is configured."""
    return bool(get_settings().activation_agent_url)


def _post(path: str, payload: dict) -> dict:
    """Single HTTP call point — kept tiny so tests can route it to a TestClient."""
    s = get_settings()
    headers = {"Authorization": f"Bearer {s.activation_agent_token or 'dev'}"}
    resp = httpx.post(
        f"{s.activation_agent_url}{path}",
        json=payload,
        headers=headers,
        timeout=httpx.Timeout(10.0),
    )
    resp.raise_for_status()
    return resp.json()


# --------------------------------------------------------------------------- #
# Pure translation functions (the contract). Unit-tested in isolation.
# --------------------------------------------------------------------------- #
def to_vendor_analyze_request(req: DiagnoseRequest) -> dict:
    return {"lineId": req.order_id, "mtn": req.mtn, "context": req.notes}


def from_vendor_analyze(v: VendorAnalyze) -> DiagnoseResponse:
    root_cause = FAULT_TEXT.get(v.faultCode or "", v.faultCode)
    if v.remediation is not None:
        return DiagnoseResponse(
            can_resolve=True,
            root_cause=root_cause,
            summary=v.analysis,
            proposed_action=ProposedAction(
                service="activation",                  # routes execute back here
                operation=v.remediation.action,
                params={"lineId": v.lineId, "ref": v.remediation.ref},
                human_prompt=v.remediation.label,
            ),
        )
    if v.state == "ACTIVE":
        return DiagnoseResponse(can_resolve=True, summary=v.analysis, root_cause=None)
    # Diagnosed, but no automatic remediation available -> escalate to a human.
    return DiagnoseResponse(can_resolve=False, root_cause=root_cause, summary=v.analysis)


def from_vendor_remediate(v: VendorRemediate) -> ExecuteResponse:
    return ExecuteResponse(
        success=v.ok,
        summary=f"Line is now {v.state}." if v.ok else "Remediation did not succeed.",
        actions_taken=v.steps,
    )


# --------------------------------------------------------------------------- #
# Public adapter API (shape matches what agents_client dispatches to)
# --------------------------------------------------------------------------- #
def diagnose(req: DiagnoseRequest) -> DiagnoseResponse:
    try:
        data = _post("/v2/activation/analyze", to_vendor_analyze_request(req))
        return from_vendor_analyze(VendorAnalyze(**data))
    except Exception as exc:  # noqa: BLE001 - degrade to escalation, never crash the chat
        logger.warning("Activation Resolver diagnose failed: %s", exc)
        return DiagnoseResponse(
            can_resolve=False,
            summary="The Activation Resolver service could not be reached.",
        )


def execute(action: ProposedAction) -> ExecuteResponse:
    try:
        payload = {
            "lineId": action.params.get("lineId"),
            "action": action.operation,
            "ref": action.params.get("ref"),
        }
        data = _post("/v2/activation/remediate", payload)
        return from_vendor_remediate(VendorRemediate(**data))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Activation Resolver remediate failed: %s", exc)
        return ExecuteResponse(success=False, summary=f"Remediation call failed: {exc}")
