"""Graph node functions and the conditional-edge routers.

Each node takes the GraphState and returns a partial update. Nodes are kept
deliberately small and pure-ish so they are easy to test and reason about.
"""
from __future__ import annotations

import logging

from langgraph.types import interrupt

from .. import llm
from ..config import get_settings
from ..integrations import agents_client
from ..schemas import (
    DiagnoseRequest,
    Intent,
    ProposedAction,
    Resolution,
)
from ..store import db
from .state import GraphState

logger = logging.getLogger("repassist.graph")

INTENT_CAPABILITY = {
    "activation": "activation-resolver",
    "pending_order": "pending-order-resolver",
    "promo": "promo-correction-agent",
    "occ": "occ-credit-agent",
    "billing": "billing-knowledge-base",
    "general": "knowledge-base",
    "other": "human-tier-2",
}


def _last_user_text(state: GraphState) -> str:
    for msg in reversed(state.get("messages", [])):
        if msg.get("role") == "user":
            return msg.get("content", "")
    return ""


def _trace(node: str, **detail) -> list[dict]:
    return [{"node": node, **detail}]


# --------------------------------------------------------------------------- #
# 1. Triage
# --------------------------------------------------------------------------- #
def triage(state: GraphState) -> dict:
    text = _last_user_text(state)
    result = llm.classify(text)

    # Merge regex-extracted entities with whatever the classifier returned.
    entities = llm.extract_entities(text)
    if result.order_id:
        entities.setdefault("order_id", result.order_id)
    if result.account_id:
        entities.setdefault("account_id", result.account_id)

    ctx = agents_client.order_context(
        entities.get("order_id"), entities.get("account_id")
    )

    return {
        "intent": result.intent,
        "confidence": result.confidence,
        "entities": entities,
        "order_context": ctx,
        "triage_summary": result.summary,  # ignored by state schema but handy in trace
        "trace": _trace(
            "triage",
            intent=result.intent,
            confidence=result.confidence,
            entities=entities,
        ),
    }


def route_after_triage(state: GraphState) -> str:
    threshold = get_settings().triage_confidence_threshold
    intent = state.get("intent") or "other"
    confidence = state.get("confidence") or 0.0
    if confidence < threshold:
        return "ticket_fallback"
    return {
        "activation": "activation",
        "pending_order": "pending_order",
        "promo": "promo",
        "occ": "occ",
        "billing": "knowledge",
        "general": "knowledge",
        "other": "ticket_fallback",
    }.get(intent, "ticket_fallback")


# --------------------------------------------------------------------------- #
# 2. Specialist resolvers (call the existing agent microservices)
# --------------------------------------------------------------------------- #
def _run_resolver(state: GraphState, intent: Intent) -> dict:
    ents = state.get("entities", {})
    req = DiagnoseRequest(
        order_id=ents.get("order_id"),
        account_id=ents.get("account_id"),
        mtn=ents.get("mtn"),
        notes=_last_user_text(state),
    )
    diag = agents_client.diagnose(intent, req)
    capability = INTENT_CAPABILITY[intent.value]

    if not diag.can_resolve:
        return {
            "route": "ticket_fallback",
            "diagnosis": diag.model_dump(),
            "trace": _trace(f"{intent.value}_resolver", can_resolve=False),
        }

    if diag.proposed_action:
        return {
            "route": "confirm",
            "proposed_action": diag.proposed_action.model_dump(),
            "resolution": Resolution(
                status="proposed",
                summary=diag.summary,
                root_cause=diag.root_cause,
                capability=capability,
            ).model_dump(),
            "trace": _trace(f"{intent.value}_resolver", proposed=True),
        }

    return {
        "route": "compose",
        "resolution": Resolution(
            status="resolved",
            summary=diag.summary,
            root_cause=diag.root_cause,
            capability=capability,
        ).model_dump(),
        "trace": _trace(f"{intent.value}_resolver", resolved_no_action=True),
    }


def activation_resolver(state: GraphState) -> dict:
    return _run_resolver(state, Intent.ACTIVATION)


def pending_order_resolver(state: GraphState) -> dict:
    return _run_resolver(state, Intent.PENDING_ORDER)


def promo_resolver(state: GraphState) -> dict:
    return _run_resolver(state, Intent.PROMO)


def occ_resolver(state: GraphState) -> dict:
    return _run_resolver(state, Intent.OCC)


# --------------------------------------------------------------------------- #
# 3. Knowledge lookup (billing / general)
# --------------------------------------------------------------------------- #
def knowledge(state: GraphState) -> dict:
    hit = agents_client.kb_search(_last_user_text(state))
    if not hit:
        return {
            "route": "ticket_fallback",
            "trace": _trace("knowledge", hit=False),
        }
    return {
        "route": "compose",
        "resolution": Resolution(
            status="resolved",
            summary=hit.get("answer", ""),
            capability="knowledge-base",
            actions_taken=[f"Shared KB article {hit.get('article_id', '')}".strip()],
        ).model_dump(),
        "trace": _trace("knowledge", hit=True, article=hit.get("article_id")),
    }


# --------------------------------------------------------------------------- #
# 4. Human-in-the-loop confirmation for mutating actions
# --------------------------------------------------------------------------- #
def confirm(state: GraphState) -> dict:
    action = state.get("proposed_action") or {}
    # Pauses the graph; the API surfaces this and resumes with Command(resume=...)
    decision = interrupt(
        {
            "type": "confirm_action",
            "prompt": action.get("human_prompt", "Apply this fix?"),
            "action": action,
        }
    )
    approved = bool(decision) and decision not in ("no", "deny", "cancel", "false")
    capability = (state.get("resolution") or {}).get("capability")

    if not approved:
        return {
            "route": "compose",
            "confirm_decision": False,
            "resolution": Resolution(
                status="cancelled",
                summary="Rep declined the proposed fix; no changes were made.",
                capability=capability,
            ).model_dump(),
            "trace": _trace("confirm", approved=False),
        }

    exec_result = agents_client.execute(ProposedAction(**action))
    if exec_result.success:
        return {
            "route": "compose",
            "confirm_decision": True,
            "resolution": Resolution(
                status="resolved",
                summary=exec_result.summary,
                actions_taken=exec_result.actions_taken,
                capability=capability,
            ).model_dump(),
            "trace": _trace("confirm", approved=True, executed=True),
        }
    return {
        "route": "ticket_fallback",
        "confirm_decision": True,
        "diagnosis": {"summary": exec_result.summary, "can_resolve": False},
        "trace": _trace("confirm", approved=True, executed=False),
    }


# --------------------------------------------------------------------------- #
# 5. Fallback — create a human ticket (replaces ServiceNow)
# --------------------------------------------------------------------------- #
def ticket_fallback(state: GraphState) -> dict:
    intent = state.get("intent") or "other"
    confidence = state.get("confidence") or 0.0
    diagnosis = state.get("diagnosis") or {}
    ents = state.get("entities", {})

    priority = "high" if intent in ("activation", "pending_order") else "normal"

    ticket = db.create_ticket(
        rep_id=state.get("rep_id"),
        thread_id=state.get("thread_id"),
        intent=intent,
        priority=priority,
        summary=diagnosis.get("summary") or state.get("triage_summary")
        or _last_user_text(state)[:160],
        order_id=ents.get("order_id"),
        account_id=ents.get("account_id"),
        conversation=state.get("messages", []),
        order_context=state.get("order_context"),
        trace=state.get("trace", []),
        # Pre-fill a suggested capability so the Tier 1/2 agent has a starting point.
        recommended_capability=INTENT_CAPABILITY.get(intent),
    )

    return {
        "route": "compose",
        "ticket_id": ticket.id,
        "resolution": Resolution(
            status="escalated",
            summary="This needs a Tier 1/2 specialist; I've captured the full "
            "context (conversation, order, and what I tried) on the ticket.",
            capability="human-tier-2",
        ).model_dump(),
        "trace": _trace("ticket_fallback", ticket_id=ticket.id, priority=priority),
    }


# --------------------------------------------------------------------------- #
# 6. Compose the rep-facing reply (+ a structured card for the UI)
# --------------------------------------------------------------------------- #
def compose(state: GraphState) -> dict:
    res = Resolution(**(state.get("resolution") or {"status": "info", "summary": ""}))
    text = llm.compose_reply(res, state.get("order_context"), state.get("ticket_id"))

    card = {
        "intent": state.get("intent"),
        "status": res.status,
        "root_cause": res.root_cause,
        "actions_taken": res.actions_taken,
        "capability": res.capability,
        "ticket_id": state.get("ticket_id"),
        "order_context": state.get("order_context"),
    }
    assistant_msg = {"role": "assistant", "content": text, "card": card}
    return {"messages": [assistant_msg], "trace": _trace("compose", status=res.status)}


def route_by_state(state: GraphState) -> str:
    """Generic conditional edge: follow whatever `route` the prior node set."""
    return state.get("route") or "compose"
