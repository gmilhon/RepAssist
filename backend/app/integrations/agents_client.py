"""Thin HTTP adapter to the *existing* agent microservices.

In production these point at the real Activation Resolver, Promo Correction
Agent and Pending Order Resolver. Locally they hit backend/app/mock_services.
The orchestrator depends only on this interface, so swapping in real services
is a config change (AGENT_SERVICES_BASE_URL), not a code change.
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
        logger.warning("diagnose(%s) failed: %s", intent, exc)
        return DiagnoseResponse(
            can_resolve=False,
            summary=f"The {path} service could not be reached.",
        )


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
        logger.warning("execute(%s) failed: %s", action.service, exc)
        return ExecuteResponse(success=False, summary=f"Execution failed: {exc}")


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
        logger.warning("order_context failed: %s", exc)
    return None


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
