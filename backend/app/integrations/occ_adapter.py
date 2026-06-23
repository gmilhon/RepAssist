"""Adapter for a REAL OCC (Other Charges and Credits) agent.

Follows the same pattern as activation_adapter.py and promo_adapter.py:

  1. Models the vendor contract (what app/sample_agent speaks for /occ/v1/*).
  2. Translates internal DiagnoseRequest → vendor on the way in.
  3. Calls the vendor over HTTP with Bearer auth.
  4. Translates vendor → internal DiagnoseResponse / ExecuteResponse on the way out.

Enable by setting OCC_AGENT_URL (+ OCC_AGENT_TOKEN). Unset → agents_client falls
back to the built-in mock at port 8100.

Credit types the vendor understands:
  ACTIVATION_FEE_WAIVER  – waive the one-time activation fee (30-day window)
  BILL_CREDIT            – credit for a documented service issue / outage
  COURTESY_CREDIT        – discretionary goodwill credit

Approval levels returned by the vendor:
  AUTO              – rep can apply immediately after confirmation
  MANAGER_REQUIRED  – human prompt notes the manager gate; rep still confirms
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

logger = logging.getLogger("repassist.occ_adapter")


# --------------------------------------------------------------------------- #
# Vendor contract (what the real/sample OCC agent returns)
# --------------------------------------------------------------------------- #
class VendorEvaluate(BaseModel):
    accountId: str | None = None
    eligible: bool
    creditType: str                  # ACTIVATION_FEE_WAIVER | BILL_CREDIT | COURTESY_CREDIT
    amount: float
    approvalLevel: str               # AUTO | MANAGER_REQUIRED
    reason: str
    applyToken: str | None = None    # present when eligible=True


class VendorApply(BaseModel):
    applied: bool
    creditId: str
    amount: float
    eta: str
    log: list[str] = []


def enabled() -> bool:
    return bool(get_settings().occ_agent_url)


def _post(path: str, payload: dict) -> dict:
    """Single HTTP call point — kept tiny so tests can monkeypatch it."""
    s = get_settings()
    headers = {"Authorization": f"Bearer {s.occ_agent_token or 'dev'}"}
    resp = httpx.post(
        f"{s.occ_agent_url}{path}",
        json=payload,
        headers=headers,
        timeout=httpx.Timeout(10.0),
    )
    resp.raise_for_status()
    return resp.json()


# --------------------------------------------------------------------------- #
# Pure translation functions (the contract). Unit-tested in isolation.
# --------------------------------------------------------------------------- #
def to_vendor_evaluate_request(req: DiagnoseRequest) -> dict:
    notes = (req.notes or "").lower()
    if "activation fee" in notes or "setup fee" in notes:
        credit_type = "ACTIVATION_FEE_WAIVER"
    elif "outage" in notes or "service issue" in notes or "downtime" in notes:
        credit_type = "BILL_CREDIT"
    else:
        credit_type = "BILL_CREDIT"
    return {"accountId": req.account_id, "creditType": credit_type, "reason": req.notes}


def from_vendor_evaluate(v: VendorEvaluate) -> DiagnoseResponse:
    if not v.eligible or not v.applyToken:
        return DiagnoseResponse(can_resolve=False, summary=v.reason)

    credit_label = v.creditType.replace("_", " ").title()
    manager_note = (
        " (Requires manager authorization.)" if v.approvalLevel == "MANAGER_REQUIRED" else ""
    )
    return DiagnoseResponse(
        can_resolve=True,
        summary=v.reason,
        proposed_action=ProposedAction(
            service="occ",
            operation=v.creditType,
            params={
                "accountId": v.accountId,
                "creditType": v.creditType,
                "amount": v.amount,
                "applyToken": v.applyToken,
            },
            human_prompt=f"Apply ${v.amount:.2f} {credit_label} to account {v.accountId}?{manager_note}",
        ),
    )


def from_vendor_apply(v: VendorApply) -> ExecuteResponse:
    if v.applied:
        summary = f"${v.amount:.2f} credit applied (ID {v.creditId}); will appear in {v.eta}."
    else:
        summary = "Credit application did not succeed."
    return ExecuteResponse(success=v.applied, summary=summary, actions_taken=v.log)


# --------------------------------------------------------------------------- #
# Public adapter API (shape matches what agents_client dispatches to)
# --------------------------------------------------------------------------- #
def diagnose(req: DiagnoseRequest) -> DiagnoseResponse:
    try:
        data = _post("/occ/v1/evaluate", to_vendor_evaluate_request(req))
        return from_vendor_evaluate(VendorEvaluate(**data))
    except Exception as exc:  # noqa: BLE001
        logger.warning("OCC agent diagnose failed: %s", exc)
        return DiagnoseResponse(
            can_resolve=False,
            summary="The OCC credit evaluation service could not be reached.",
        )


def execute(action: ProposedAction) -> ExecuteResponse:
    try:
        payload = {
            "accountId": action.params.get("accountId"),
            "creditType": action.params.get("creditType", action.operation),
            "amount": action.params.get("amount", 0.0),
            "applyToken": action.params.get("applyToken"),
        }
        data = _post("/occ/v1/apply", payload)
        return from_vendor_apply(VendorApply(**data))
    except Exception as exc:  # noqa: BLE001
        logger.warning("OCC agent apply failed: %s", exc)
        return ExecuteResponse(success=False, summary=f"Credit application call failed: {exc}")
