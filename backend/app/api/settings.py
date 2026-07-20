"""Settings-managed policy the orchestrator reads live.

Currently: CES Routing — which triage intents relay to the external Google CES
`repAssist` agent (see integrations/ces_client + graph.nodes.ces_remote). The
connection itself (which deployment, where) is env/Secret-Manager config
(CES_DEPLOYMENT); this router manages only the per-intent on/off policy, which is
persisted in the `ces_routes` table and read on every turn by
`route_after_triage`. Toggling here takes effect on the rep's next message.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import get_settings
from ..integrations import agents_client, ces_client
from ..integrations.ces_client import CES_ENTRY_AGENTS
from ..schemas import Intent
from ..store import db

router = APIRouter(prefix="/api/settings", tags=["settings"])

# Intents a manager may route to CES. Excludes SYSTEM — Rep Assist's own
# product Q&A is never delegated to an external telecom agent.
ROUTABLE = [
    Intent.ACTIVATION, Intent.PENDING_ORDER, Intent.PROMO, Intent.OCC,
    Intent.BILLING, Intent.GENERAL, Intent.OTHER,
]

INTENT_LABELS = {
    Intent.ACTIVATION: "Activation",
    Intent.PENDING_ORDER: "Pending order",
    Intent.PROMO: "Promo",
    Intent.OCC: "Credits (OCC)",
    Intent.BILLING: "Billing",
    Intent.GENERAL: "General / how-to",
    Intent.OTHER: "Other / uncategorized",
}

_ROUTABLE_VALUES = {i.value for i in ROUTABLE}


@router.get("/ces-routing")
def get_ces_routing() -> dict:
    """Current routing policy + connection status for the Settings CES page."""
    routes = db.ces_routes()
    s = get_settings()
    return {
        "configured": ces_client.enabled(),
        "stubbed": s.ces_stub,
        "deployment": s.ces_deployment or None,
        "location": s.ces_location,
        "entry_agents": CES_ENTRY_AGENTS,
        "intents": [
            {
                "intent": i.value,
                "label": INTENT_LABELS[i],
                "enabled": bool(routes.get(i.value) and routes[i.value].enabled),
                "entry_agent": routes[i.value].entry_agent if i.value in routes else None,
                # True when a built-in resolver already owns this intent — so the
                # UI can say CES "overrides" it (vs. "adds capability" for the rest).
                "has_resolver": i in agents_client.CAPABILITY_PATHS,
            }
            for i in ROUTABLE
        ],
    }


class CesRouteReq(BaseModel):
    intent: str
    enabled: bool
    entry_agent: Optional[str] = None


@router.post("/ces-routing")
def set_ces_routing(req: CesRouteReq) -> dict:
    """Toggle one intent's CES routing (and optionally its entry sub-agent)."""
    if req.intent not in _ROUTABLE_VALUES:
        raise HTTPException(422, f"Unknown or non-routable intent: {req.intent!r}")
    if req.entry_agent and req.entry_agent not in CES_ENTRY_AGENTS:
        raise HTTPException(422, f"Unknown CES entry agent: {req.entry_agent!r}")
    db.set_ces_route(req.intent, req.enabled, req.entry_agent)
    return {"intent": req.intent, "enabled": req.enabled, "entry_agent": req.entry_agent}
