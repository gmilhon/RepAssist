"""Thin HTTP adapter to the *existing* agent microservices.

In production these point at the real Activation Resolver, Promo Correction
Agent and Pending Order Resolver. Locally they hit backend/app/mock_services.
The orchestrator depends only on this interface, so swapping in real services
is a config change (AGENT_SERVICES_BASE_URL), not a code change.

When the HTTP endpoint is unavailable (e.g. Cloud Run where :8100 doesn't run),
the _stub_* functions below provide identical behaviour in-process.
"""
from __future__ import annotations

import logging

import httpx

from ..config import get_settings
from ..schemas import (
    DiagnoseRequest,
    DiagnoseResponse,
    ExecuteResponse,
    Intent,
    ProposedAction,
)
from . import activation_adapter, occ_adapter, promo_adapter

logger = logging.getLogger("repassist.agents")

# Maps an intent to the REST path of the agent that owns it.
CAPABILITY_PATHS = {
    Intent.ACTIVATION: "activation",
    Intent.PENDING_ORDER: "pending-order",
    Intent.PROMO: "promo",
    Intent.OCC: "occ",
}

_TIMEOUT = httpx.Timeout(10.0)


def _base() -> str:
    return get_settings().agent_services_base_url


# --------------------------------------------------------------------------- #
# In-process stubs — mirror mock_services/main.py without HTTP
# --------------------------------------------------------------------------- #
def _action(service: str, operation: str, human_prompt: str, **params) -> dict:
    return {"service": service, "operation": operation, "params": params,
            "human_prompt": human_prompt}


def _stub_diagnose(path: str, req: DiagnoseRequest) -> dict:
    if path == "activation":
        if req.order_id == "ACT-1002":
            return {"can_resolve": False,
                    "root_cause": "Number port from the losing carrier has not completed.",
                    "summary": "Activation is blocked by an external carrier port that we "
                               "cannot release from the sales counter."}
        return {"can_resolve": True,
                "root_cause": "SIM/eSIM profile was never pushed to the network.",
                "summary": "The line is stuck because provisioning didn't reach the network.",
                "proposed_action": _action(
                    "activation", "resend_provisioning",
                    "Re-send the provisioning request to activate the line now?",
                    order_id=req.order_id)}

    if path == "pending-order":
        if req.order_id == "ORD-2003":
            return {"can_resolve": False,
                    "root_cause": "A credit-check hold is on the account.",
                    "summary": "The new order is blocked by a credit hold that requires a "
                               "specialist to review."}
        return {"can_resolve": True,
                "root_cause": "A prior order (ORD-1990) is stuck in DELAYED and blocks new orders.",
                "summary": "The customer's new order is blocked by an older, stalled order.",
                "proposed_action": _action(
                    "pending-order", "expedite_prior_order",
                    "Expedite/clear the blocking order ORD-1990 so this order can proceed?",
                    prior_order="ORD-1990", order_id=req.order_id)}

    if path == "promo":
        if req.account_id == "AC-3004":
            return {"can_resolve": True,
                    "root_cause": "The promotion window closed before activation.",
                    "summary": "The customer isn't eligible — the BOGO promo expired before "
                               "the line activated, so nothing was applied in error."}
        return {"can_resolve": True,
                "root_cause": "Eligibility criteria were met but the credit never attached.",
                "summary": "The customer qualifies for BOGO but the credit wasn't applied.",
                "proposed_action": _action(
                    "promo", "reapply_promo",
                    "Re-apply the BOGO-2026 promotional credit to this account?",
                    promo="BOGO-2026", account_id=req.account_id)}

    if path == "occ":
        if req.account_id == "AC-5003":
            return {"can_resolve": False,
                    "root_cause": "The 30-day activation fee waiver window has closed.",
                    "summary": "The account was activated more than 30 days ago; no automatic "
                               "fee waiver can be applied at this time."}
        if req.account_id == "AC-5002":
            return {"can_resolve": True,
                    "root_cause": "Documented 48-hour service degradation on the account.",
                    "summary": "Customer is eligible for a $50.00 bill credit for the "
                               "documented network outage. Manager authorization is on file.",
                    "proposed_action": _action(
                        "occ", "BILL_CREDIT",
                        f"Apply $50.00 Bill Credit to account {req.account_id}? "
                        "(Manager authorization on file.)",
                        account_id=req.account_id, amount=50.00, creditType="BILL_CREDIT")}
        return {"can_resolve": True,
                "root_cause": "Activation fee charged within the 30-day waiver window.",
                "summary": "Customer is eligible for a $35.00 activation fee waiver.",
                "proposed_action": _action(
                    "occ", "ACTIVATION_FEE_WAIVER",
                    "Apply $35.00 Activation Fee Waiver to this account?",
                    account_id=req.account_id, amount=35.00,
                    creditType="ACTIVATION_FEE_WAIVER")}

    return {"can_resolve": False, "summary": f"No stub defined for {path}."}


def _stub_execute(service: str, operation: str, params: dict) -> dict:
    if service == "activation":
        return {"success": True,
                "summary": "Provisioning re-sent and the line activated successfully.",
                "actions_taken": ["Re-sent provisioning request to the network",
                                  "Confirmed the line is now Active"]}
    if service == "pending-order":
        prior = params.get("prior_order", "the blocking order")
        return {"success": True,
                "summary": f"Cleared {prior}; the new order is no longer blocked.",
                "actions_taken": [f"Expedited {prior}",
                                  "Released the hold on the new order"]}
    if service == "promo":
        promo = params.get("promo", "the promotion")
        return {"success": True,
                "summary": f"Re-applied {promo}; the credit will appear within 1-2 cycles.",
                "actions_taken": [f"Re-applied {promo} credit",
                                  "Validated the credit schedule on the account"]}
    if service == "occ":
        amount = params.get("amount", 0.0)
        credit_type = operation.replace("_", " ").title()
        account_id = params.get("account_id", "the account")
        return {"success": True,
                "summary": f"${float(amount):.2f} {credit_type} applied; "
                           "will appear within 1-2 billing cycles.",
                "actions_taken": [
                    f"Applied ${float(amount):.2f} {credit_type} to {account_id}",
                    "Credit scheduled for next billing cycle",
                    "Rep confirmation recorded",
                ]}
    return {"success": False, "summary": f"No stub defined for {service}."}


def _stub_order_context(order_id: str | None, account_id: str | None) -> dict:
    from ..mock_services.data import ACCOUNTS, ORDERS
    if order_id and order_id in ORDERS:
        ctx = dict(ORDERS[order_id])
        acct = ctx.get("account_id")
        if acct in ACCOUNTS:
            ctx["account"] = ACCOUNTS[acct]
        return ctx
    if account_id and account_id in ACCOUNTS:
        return {"account": ACCOUNTS[account_id]}
    return {"order_id": order_id or None, "account_id": account_id or None,
            "status": "Unknown", "note": "No matching record in mock data."}


# --------------------------------------------------------------------------- #
# Public interface
# --------------------------------------------------------------------------- #
def diagnose(intent: Intent, req: DiagnoseRequest) -> DiagnoseResponse:
    if intent == Intent.ACTIVATION and activation_adapter.enabled():
        return activation_adapter.diagnose(req)
    if intent == Intent.PROMO and promo_adapter.enabled():
        return promo_adapter.diagnose(req)
    if intent == Intent.OCC and occ_adapter.enabled():
        return occ_adapter.diagnose(req)

    path = CAPABILITY_PATHS[intent]
    url = f"{_base()}/{path}/diagnose"
    try:
        resp = httpx.post(url, json=req.model_dump(), timeout=_TIMEOUT)
        resp.raise_for_status()
        return DiagnoseResponse(**resp.json())
    except Exception as exc:  # noqa: BLE001
        logger.info("diagnose(%s) HTTP unavailable (%s) — using in-process stub", intent, exc)
        return DiagnoseResponse(**_stub_diagnose(path, req))


def execute(action: ProposedAction) -> ExecuteResponse:
    if action.service == "activation" and activation_adapter.enabled():
        return activation_adapter.execute(action)
    if action.service == "promo" and promo_adapter.enabled():
        return promo_adapter.execute(action)
    if action.service == "occ" and occ_adapter.enabled():
        return occ_adapter.execute(action)

    url = f"{_base()}/{action.service}/execute"
    try:
        resp = httpx.post(
            url,
            json={"operation": action.operation, "params": action.params},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        return ExecuteResponse(**resp.json())
    except Exception as exc:  # noqa: BLE001
        logger.info("execute(%s) HTTP unavailable (%s) — using in-process stub", action.service, exc)
        return ExecuteResponse(**_stub_execute(action.service, action.operation, action.params))


def order_context(order_id: str | None, account_id: str | None) -> dict | None:
    """Best-effort fetch of order/account context to enrich the conversation."""
    if not order_id and not account_id:
        return None
    try:
        resp = httpx.get(
            f"{_base()}/orders/lookup",
            params={"order_id": order_id or "", "account_id": account_id or ""},
            timeout=_TIMEOUT,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception as exc:  # noqa: BLE001
        logger.info("order_context HTTP unavailable (%s) — using in-process stub", exc)
    return _stub_order_context(order_id, account_id)


def kb_search(query: str) -> dict | None:
    """Knowledge-base lookup for billing/general questions."""
    try:
        resp = httpx.post(f"{_base()}/kb/search", json={"query": query}, timeout=_TIMEOUT)
        if resp.status_code == 200:
            data = resp.json()
            return data if data.get("hit") else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("kb_search failed: %s", exc)
    return None
