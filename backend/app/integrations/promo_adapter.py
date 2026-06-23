"""Adapter for a REAL Promo Correction Agent.

Second worked example of the integration pattern (see activation_adapter.py).
Deliberately different from the activation agent to show the pattern generalizes:
this vendor uses an `X-Api-Key` header (not Bearer) and an eligibility-style
contract. Enable by setting PROMO_AGENT_URL (+ PROMO_AGENT_TOKEN).
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

logger = logging.getLogger("repassist.promo_adapter")


# --- Vendor contract ---
class _PromoInfo(BaseModel):
    code: str
    name: str


class _PromoFix(BaseModel):
    type: str
    token: str


class VendorEval(BaseModel):
    accountId: str | None = None
    eligibility: str
    promo: _PromoInfo | None = None
    reason: str
    fix: _PromoFix | None = None


class VendorApply(BaseModel):
    applied: bool
    creditEta: str = ""
    log: list[str] = []


def enabled() -> bool:
    return bool(get_settings().promo_agent_url)


def _post(path: str, payload: dict) -> dict:
    s = get_settings()
    headers = {"X-Api-Key": s.promo_agent_token or "dev"}
    resp = httpx.post(
        f"{s.promo_agent_url}{path}", json=payload, headers=headers,
        timeout=httpx.Timeout(10.0),
    )
    resp.raise_for_status()
    return resp.json()


# --- Pure translation functions (the contract) ---
def to_vendor_eval_request(req: DiagnoseRequest) -> dict:
    return {"accountId": req.account_id, "mtn": req.mtn, "freeText": req.notes}


def from_vendor_eval(v: VendorEval) -> DiagnoseResponse:
    if v.fix is not None:
        promo_name = v.promo.name if v.promo else "the promotion"
        return DiagnoseResponse(
            can_resolve=True,
            root_cause=v.reason,
            summary=v.reason,
            proposed_action=ProposedAction(
                service="promo",
                operation=v.fix.type,
                params={
                    "accountId": v.accountId,
                    "fixToken": v.fix.token,
                    "promoCode": v.promo.code if v.promo else None,
                },
                human_prompt=f"Re-apply the {promo_name} credit to this account?",
            ),
        )
    # INELIGIBLE / APPLIED -> a correct answer with no change to make.
    return DiagnoseResponse(can_resolve=True, summary=v.reason, root_cause=None)


def from_vendor_apply(v: VendorApply) -> ExecuteResponse:
    return ExecuteResponse(
        success=v.applied,
        summary=(f"Re-applied the promotion; the credit will appear within {v.creditEta}."
                 if v.applied else "The promotion could not be applied."),
        actions_taken=v.log,
    )


# --- Public adapter API ---
def diagnose(req: DiagnoseRequest) -> DiagnoseResponse:
    try:
        data = _post("/promo-svc/v1/evaluate", to_vendor_eval_request(req))
        return from_vendor_eval(VendorEval(**data))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Promo Correction Agent evaluate failed: %s", exc)
        return DiagnoseResponse(
            can_resolve=False,
            summary="The Promo Correction Agent service could not be reached.",
        )


def execute(action: ProposedAction) -> ExecuteResponse:
    try:
        payload = {
            "accountId": action.params.get("accountId"),
            "fixToken": action.params.get("fixToken"),
            "promoCode": action.params.get("promoCode"),
        }
        data = _post("/promo-svc/v1/apply", payload)
        return from_vendor_apply(VendorApply(**data))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Promo Correction Agent apply failed: %s", exc)
        return ExecuteResponse(success=False, summary=f"Promo apply failed: {exc}")
