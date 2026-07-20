"""Graph node functions and the conditional-edge routers.

Each node takes the GraphState and returns a partial update. Nodes are kept
deliberately small and pure-ish so they are easy to test and reason about.
"""
from __future__ import annotations

import logging

from langgraph.types import interrupt

from .. import llm, shop as shop_engine
from ..config import get_settings
from ..integrations import agents_client, ces_client
from ..mock_services import shop_data
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
    "system": "system-mcp",
    "other": "human-tier-2",
}

# Intents that need an id before a resolver can act. If it's missing, the graph
# asks the rep for it (clarify) instead of escalating.
NEEDS_ID = {
    "activation": "order_id",
    "pending_order": "order_id",
    "promo": "account_id",
    "occ": "account_id",
}

# The question the assistant asks when the required id is missing.
CLARIFY_QUESTION = {
    "activation": "Happy to help with the activation — what's the order ID? (it looks like ACT-1234)",
    "pending_order": "I can look into the blocked order — what's the order ID? (ACT-#### or ORD-####)",
    "promo": "Sure — what's the customer's account ID? (AC-1234) I'll check the promo.",
    "occ": "I can help with that credit — what's the customer's account ID? (AC-1234)",
}


def _last_user_text(state: GraphState) -> str:
    for msg in reversed(state.get("messages", [])):
        if msg.get("role") == "user":
            return msg.get("content", "")
    return ""


def _trace(node: str, **detail) -> list[dict]:
    return [{"node": node, **detail}]


# --------------------------------------------------------------------------- #
# CES relay helpers (see ces_remote + route_after_triage)
# --------------------------------------------------------------------------- #
# Phrases a rep can type to leave an in-flight CES sub-conversation and hand the
# thread back to Rep Assist. Detected in triage, which clears the sticky flag.
_CES_HANDBACK = (
    "back to rep assist", "back to repassist", "exit ces", "leave ces",
    "stop ces", "done with ces", "hand back", "handoff back", "handoff to rep assist",
)


def _wants_ces_handback(text: str) -> bool:
    t = text.lower()
    return any(phrase in t for phrase in _CES_HANDBACK)


def _ces_session_id(state: GraphState) -> str:
    """Stable per-thread CES session id, reused across turns for multi-turn
    context. Matches the CES id regex [A-Za-z0-9][A-Za-z0-9-_]{4,62}."""
    tid = (state.get("thread_id") or "anon").replace("-", "")[:48]
    return f"ra{tid}"


def _enrich_for_ces(text: str, ents: dict) -> str:
    """Append known ids to the relayed text so the CES steering agent can skip
    slot-filling — the same pre-fill trick the built-in resolvers use to avoid
    re-prompting the rep for data we already have."""
    labels = {"customer_name": "Customer", "account_id": "account_id",
              "order_id": "order_id", "mtn": "mtn"}
    tags = [f"({labels[k]}: {ents[k]})" for k in labels if ents.get(k)]
    return " ".join([text, *tags]).strip()


# --------------------------------------------------------------------------- #
# 1. Triage
# --------------------------------------------------------------------------- #
def triage(state: GraphState) -> dict:
    text = _last_user_text(state)
    result = llm.classify(text, thread_id=state.get("thread_id"), rep_id=state.get("rep_id"))

    # Merge newly-extracted entities with any carried from earlier turns.
    entities = {**(state.get("entities") or {}), **llm.extract_entities(text)}
    if result.order_id:
        entities.setdefault("order_id", result.order_id)
    if result.account_id:
        entities.setdefault("account_id", result.account_id)

    intent = result.intent
    confidence = result.confidence
    # Best-effort heuristic; carry forward the prior turn's tag if this turn
    # doesn't hit any keyword (a rep rarely repeats "add a line" every message).
    sales_intent = llm.tag_sales_intent(text) or state.get("sales_intent")

    # Slot-fill: if the assistant just asked for an id and the rep's reply now
    # supplies it, resume the prior intent instead of re-classifying the bare id.
    awaiting = state.get("awaiting")
    prior_intent = state.get("intent")
    if awaiting and prior_intent and entities.get(awaiting):
        intent = prior_intent
        confidence = max(confidence, 0.9)

    ctx = agents_client.order_context(
        entities.get("order_id"), entities.get("account_id")
    )

    updates = {
        "intent": intent,
        "confidence": confidence,
        "sales_intent": sales_intent,
        "entities": entities,
        "order_context": ctx,
        "triage_summary": result.summary,  # ignored by state schema but handy in trace
        "awaiting": None,                   # cleared; clarify re-sets if still missing
        "article": None,                    # cleared; knowledge re-sets on an OST hit
        "trace": _trace(
            "triage",
            intent=intent,
            confidence=confidence,
            entities=entities,
        ),
    }
    # If the rep explicitly asks to leave an in-flight CES sub-conversation, clear
    # the sticky flag here (before route_after_triage) so this turn is handled by
    # Rep Assist again instead of being relayed to CES.
    if state.get("ces_active") and _wants_ces_handback(text):
        updates["ces_active"] = False
    return updates


def route_after_triage(state: GraphState) -> str:
    threshold = get_settings().triage_confidence_threshold
    intent = state.get("intent") or "other"
    confidence = state.get("confidence") or 0.0
    entities = state.get("entities", {})
    # Sticky: an in-flight CES sub-conversation keeps the thread until the rep
    # hands back (triage clears ces_active on a hand-back phrase). Checked first
    # so a mid-flow follow-up ("the name is John") stays with CES even if it
    # classifies as low-confidence/other on its own.
    if state.get("ces_active") and ces_client.enabled():
        return "ces_remote"
    # Sticky: an in-flight shopping session keeps the thread so mid-flow turns
    # ("the Pixel 10", "Unlimited Ultimate") build the cart even though they
    # classify as low-confidence/other on their own. `shop` clears it on exit.
    if state.get("shop_active"):
        return "shop"
    # Ticket reference takes priority — look it up regardless of other keywords.
    if entities.get("ticket_ref_id"):
        return "ticket_recap"
    if confidence < threshold:
        return "ticket_fallback"
    # Shopping intents (add a line / upgrade) → the cart-building node. No id is
    # required to start; the account context is looked up when available.
    if intent in (Intent.ADD_LINE.value, Intent.UPGRADE.value):
        return "shop"
    # Per-intent CES routing, managed live in Settings → CES Routing. CES
    # self-slot-fills, so we route even when a required id is missing —
    # intentionally ahead of the clarify gate below.
    if ces_client.enabled() and intent in db.ces_enabled_intents():
        return "ces_remote"
    # Ask for a missing required id rather than escalating.
    needed = NEEDS_ID.get(intent)
    if needed and not entities.get(needed):
        return "clarify"
    return {
        "activation": "activation",
        "pending_order": "pending_order",
        "promo": "promo",
        "occ": "occ",
        "billing": "knowledge",
        "general": "knowledge",
        "system": "system_help",
        "add_line": "shop",
        "upgrade": "shop",
        "other": "ticket_fallback",
    }.get(intent, "ticket_fallback")


# --------------------------------------------------------------------------- #
# 1b. Clarify — ask the rep for a missing id (no ticket, conversation continues)
# --------------------------------------------------------------------------- #
def clarify(state: GraphState) -> dict:
    intent = state.get("intent") or "other"
    field = NEEDS_ID.get(intent, "order_id")
    question = CLARIFY_QUESTION.get(
        intent, "Which order or account should I look at?"
    )
    return {
        "awaiting": field,
        "resolution": Resolution(status="info", summary=question).model_dump(),
        "messages": [{"role": "assistant", "content": question, "card": None}],
        "trace": _trace("clarify", intent=intent, awaiting=field),
    }


# --------------------------------------------------------------------------- #
# 1c. Ticket recap — look up a referenced ticket (TCK-…) and return next steps
# --------------------------------------------------------------------------- #
_TICKET_NEXT_STEPS: dict[str, str] = {
    "pending_order": (
        "Pull up the stalled prior order and check its current status. "
        "If it's been stuck for more than 24 h, initiate a manual release — "
        "the new upgrade order should unblock within minutes once the hold clears."
    ),
    "activation": (
        "Verify SIM/eSIM provisioning status in the activation portal. "
        "If a carrier port is stalled, check the port-in tracker and contact "
        "the carrier liaison to force-complete if it's been pending over 48 h."
    ),
    "billing": (
        "Pull the customer's billing account and review the disputed charge. "
        "If a credit or reversal is warranted, escalate to Billing Tier 2 with this ticket."
    ),
    "occ": (
        "Confirm the service disruption window and verify customer eligibility, "
        "then process the courtesy credit via the OCC tool."
    ),
    "promo": (
        "Check promo eligibility for the customer's plan and order date. "
        "If valid, reapply the promotional discount in account management."
    ),
    "other": (
        "Review the full ticket context and route to the appropriate support queue for resolution."
    ),
}


def ticket_recap(state: GraphState) -> dict:
    """Look up a referenced ticket (TCK-…) and return a rep-facing recap with next steps."""
    from ..mcp import get_mcp_client

    ref_id = (state.get("entities") or {}).get("ticket_ref_id", "")
    ticket = None
    try:
        result = get_mcp_client().call_tool("tickets", "get_ticket", {"ticket_id": ref_id})
        ticket = result.get("ticket")
    except Exception as exc:  # noqa: BLE001
        logger.warning("ticket lookup failed (%s)", exc)

    if not ticket:
        answer = f"I couldn't find ticket {ref_id}. Double-check the ticket number and try again."
        return {
            "resolution": Resolution(status="info", summary=answer).model_dump(),
            "messages": [{"role": "assistant", "content": answer, "card": None}],
            "trace": _trace("ticket_recap", found=False, ref_id=ref_id),
        }

    intent = ticket.get("intent", "other")
    next_steps = _TICKET_NEXT_STEPS.get(intent, _TICKET_NEXT_STEPS["other"])
    priority_label = ticket.get("priority", "normal").capitalize()
    summary = (
        f"{ref_id} — {ticket['status_label']} · {priority_label} priority\n"
        f"{ticket['summary']} (opened {ticket['age_label']})\n\n"
        f"Next steps: {next_steps}"
    )
    return {
        "resolution": Resolution(status="info", summary=summary, capability="ticketing").model_dump(),
        "messages": [{"role": "assistant", "content": summary, "card": None}],
        "trace": _trace("ticket_recap", found=True, ref_id=ref_id, intent=intent),
    }


# --------------------------------------------------------------------------- #
# 1d. System help — answer questions about Rep Assist via the system MCP tool
# --------------------------------------------------------------------------- #
def system_help(state: GraphState) -> dict:
    from ..mcp import get_mcp_client

    question = _last_user_text(state)
    try:
        result = get_mcp_client().call_tool(
            "system", "answer_system_question", {"question": question}
        )
        answer = result.get("answer", "")
    except Exception as exc:  # noqa: BLE001 - degrade gracefully
        logger.warning("system MCP answer failed (%s)", exc)
        answer = "I can help with questions about Rep Assist — try asking what's new."

    return {
        "resolution": Resolution(status="info", summary=answer, capability="system-mcp").model_dump(),
        "messages": [{"role": "assistant", "content": answer, "card": None}],
        "trace": _trace("system_help"),
    }


# --------------------------------------------------------------------------- #
# 1e. CES relay — hand the turn to the external Google CES `repAssist` agent
# --------------------------------------------------------------------------- #
def ces_remote(state: GraphState) -> dict:
    """Relay one rep turn to the external CES agent and surface its reply
    verbatim (an advisory relay — no writes; see ces_client's docstring). The
    reply is shown as-is rather than run back through `compose`, because compose
    would re-voice it with the LLM and lose the external agent's actual words.
    A stable CES session id is threaded on the state for multi-turn context, and
    `ces_active` keeps the thread on CES until the rep hands back."""
    sid = state.get("ces_session_id") or _ces_session_id(state)
    intent = state.get("intent") or "other"
    route = db.ces_routes().get(intent)
    entry_agent = route.entry_agent if route else None
    relayed = _enrich_for_ces(_last_user_text(state), state.get("entities") or {})

    try:
        turn = ces_client.run_turn(sid, relayed, entry_agent)
    except Exception as exc:  # noqa: BLE001 - run_turn shouldn't raise, but never break the chat
        logger.warning("CES relay failed (%s) — escalating", exc)
        return {
            "route": "ticket_fallback",
            "ces_active": False,
            "diagnosis": {"can_resolve": False,
                          "summary": "The external CES agent is unavailable; escalating to a specialist."},
            "trace": _trace("ces_remote", ok=False),
        }

    source = "CES · repAssist" + (f" · {entry_agent}" if entry_agent else "")
    card = {
        "intent": intent,
        "status": "info",          # a relayed conversational turn, not a closed resolution
        "root_cause": None,
        "actions_taken": [],
        "capability": source,
        "ticket_id": None,
        "order_context": state.get("order_context"),
    }
    return {
        "messages": [{"role": "assistant", "content": turn.text, "card": card}],
        # Carry a matching Resolution so _shape/_record classify the turn as an
        # answered (info) interaction attributed to CES, not a resolution/escalation.
        "resolution": Resolution(status="info", summary=turn.text, capability=source).model_dump(),
        "ces_active": True,        # sticky until the rep hands back
        "ces_session_id": sid,
        "route": "reply",          # terminal: reply is verbatim, no compose rewrite
        "trace": _trace("ces_remote", ok=True, entry_agent=entry_agent,
                        stubbed=getattr(turn, "stubbed", False)),
    }


# --------------------------------------------------------------------------- #
# 1f. Shopping — build/update the cart (add a line / upgrade)
# --------------------------------------------------------------------------- #
_SHOP_EXIT = ("back to rep assist", "done shopping", "that's all", "thats all",
              "all set", "cancel the order", "cancel shopping", "exit shopping",
              "leave shopping", "never mind")


def _wants_shop_exit(text: str) -> bool:
    t = text.lower()
    return any(p in t for p in _SHOP_EXIT)


def shop(state: GraphState) -> dict:
    """Interpret the rep's turn into cart operations and update this thread's
    cart — the in-chat add-a-line / upgrade experience surfaced in the top cart
    drawer. Sticky: the shopping session owns the thread until the rep exits.
    Advisory only — no order/payment in this phase."""
    thread_id = state.get("thread_id") or "anon"
    text = _last_user_text(state)
    ents = state.get("entities") or {}
    account = shop_data.account_summary(ents.get("account_id"))

    cart_row = db.get_cart(thread_id)
    items = list(cart_row.items) if cart_row else []

    card = {"intent": state.get("intent"), "status": "info", "root_cause": None,
            "actions_taken": [], "capability": "shopping-assistant",
            "ticket_id": None, "order_context": None}

    # Rep is stepping out of the shopping flow — close it cleanly (keep the cart).
    if _wants_shop_exit(text):
        view = shop_engine.cart_view(items)
        n = len(view["items"])
        msg = (f"No problem — I've saved the cart ({n} item{'s' if n != 1 else ''}, "
               f"${view['monthly_total']:.2f}/mo). Reopen the cart anytime to keep going."
               if n else "No problem — nothing's in the cart. What else can I help with?")
        return {
            "messages": [{"role": "assistant", "content": msg, "card": card}],
            "resolution": Resolution(status="info", summary=msg, capability="shopping-assistant").model_dump(),
            "cart": view, "shop_active": False, "route": "reply",
            "trace": _trace("shop", exit=True),
        }

    # Checkout: propose the order and route through the rep-confirmation gate
    # (the same interrupt() that guards every account change). Payment is
    # simulated in confirm() — never a real charge.
    if shop_engine.wants_checkout(text):
        view = shop_engine.cart_view(items)
        if not view["items"]:
            msg = "The cart's empty — add a line or an upgrade first, then we can place the order."
            return {
                "messages": [{"role": "assistant", "content": msg, "card": card}],
                "resolution": Resolution(status="info", summary=msg, capability="shopping-assistant").model_dump(),
                "cart": view, "shop_active": True, "route": "reply",
                "trace": _trace("shop", checkout="empty"),
            }
        prompt = shop_engine.order_prompt(items)
        return {
            "proposed_action": {
                "service": "shop", "operation": "place_order",
                "params": {"item_count": len(view["items"]), "monthly_total": view["monthly_total"]},
                "human_prompt": prompt,
            },
            "resolution": Resolution(status="proposed", summary=prompt,
                                     capability="shopping-assistant").model_dump(),
            "cart": view, "shop_active": True, "route": "confirm",
            "trace": _trace("shop", checkout=True, items=len(view["items"])),
        }

    turn = llm.interpret_shop_turn(text, account, items,
                                   thread_id=thread_id, rep_id=state.get("rep_id"))
    new_items, _notes = shop_engine.apply_ops(items, turn.ops, account)
    db.save_cart(thread_id, new_items, account_id=account.get("account_id"))
    view = shop_engine.cart_view(new_items)

    return {
        "messages": [{"role": "assistant", "content": turn.reply, "card": card}],
        "resolution": Resolution(status="info", summary=turn.reply,
                                 capability="shopping-assistant").model_dump(),
        "cart": view,
        "shop_active": True,
        "route": "reply",
        "trace": _trace("shop", ops=[o.op for o in turn.ops], items=len(new_items)),
    }


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
    """Answer a knowledge question from OST (One Source of Truth) — returns the
    best-matching article as an A2UI card. Falls back to a ticket on a miss."""
    from ..mcp import get_mcp_client

    query = _last_user_text(state)
    try:
        result = get_mcp_client().call_tool("ost", "search_articles", {"query": query})
        elements = result.get("elements", [])
    except Exception as exc:  # noqa: BLE001 - degrade gracefully
        logger.warning("OST search failed (%s)", exc)
        elements = []

    if not elements:
        return {"route": "ticket_fallback", "trace": _trace("knowledge", hit=False)}

    article = elements[0]
    return {
        "route": "compose",
        "article": article,
        "resolution": Resolution(
            status="resolved",
            summary=article.get("summary", article.get("title", "")),
            capability="one-source-of-truth",
            actions_taken=[f"Shared OST article {article.get('article_id', '')}".strip()],
        ).model_dump(),
        "trace": _trace("knowledge", hit=True, article=article.get("article_id")),
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
        # Shopping: keep the cart so the rep can keep editing; other flows cancel.
        is_shop = action.get("service") == "shop"
        return {
            "route": "reply" if is_shop else "compose",
            "confirm_decision": False,
            "messages": [{"role": "assistant",
                          "content": "No problem — I didn't place the order. The cart's still here whenever you're ready.",
                          "card": None}] if is_shop else [],
            "resolution": Resolution(
                status="cancelled",
                summary="Rep declined; the order was not placed." if is_shop
                else "Rep declined the proposed fix; no changes were made.",
                capability=capability,
            ).model_dump(),
            "shop_active": True if is_shop else None,
            "trace": _trace("confirm", approved=False, shop=is_shop),
        }

    # Shopping checkout: place the order + SIMULATE payment (no real charge),
    # gated by the same rep approval above. Then clear the cart.
    if action.get("service") == "shop":
        account = shop_data.account_summary((state.get("entities") or {}).get("account_id"))
        result = shop_engine.place_order(
            (state.get("cart") or {}).get("items", []), account,
            thread_id=state.get("thread_id"), rep_id=state.get("rep_id"),
        )
        db.record_action_audit(thread_id=state.get("thread_id"), rep_id=state.get("rep_id"),
                               service="shop", operation="place_order",
                               approved=approved, success=True)
        db.clear_cart(state.get("thread_id") or "anon")
        summary = (f"✅ Order {result['order_id']} placed — ${result['monthly_total']:.2f}/mo"
                   + (f" + ${result['onetime_total']:.2f} today" if result["onetime_total"] else "")
                   + f", charged to {result['payment_method']}. Confirmation sent to the customer.")
        card = {"intent": state.get("intent"), "status": "resolved", "root_cause": None,
                "actions_taken": [], "capability": "shopping-assistant",
                "ticket_id": None, "order_context": None}
        return {
            "route": "reply",
            "confirm_decision": True,
            "messages": [{"role": "assistant", "content": summary, "card": card,
                          "a2ui": [{"type": "order_confirmation", **result}]}],
            "resolution": Resolution(status="resolved", summary=summary,
                                     capability="shopping-assistant").model_dump(),
            "cart": {"items": [], "monthly_total": 0.0, "onetime_total": 0.0},
            "shop_active": False,
            "trace": _trace("confirm", approved=True, order=result["order_id"]),
        }

    exec_result = agents_client.execute(ProposedAction(**action))
    # Audit trail for the single execute() call site in the whole app — the
    # graph structurally cannot reach this line without `approved` being True
    # above, so `approved` here should always persist as True. Monitored on
    # the CX Monitor guardrail panel as an invariant, not a rate: any False
    # row is a real incident (a refactor broke the confirm gate), not noise.
    db.record_action_audit(
        thread_id=state.get("thread_id"),
        rep_id=state.get("rep_id"),
        service=action.get("service", ""),
        operation=action.get("operation", ""),
        approved=approved,
        success=exec_result.success,
    )
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
        sales_intent=state.get("sales_intent"),
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

    # Feed the Production Monitor's live inflow (SSE + burst-triggered analysis).
    # Best-effort: monitoring must never break the conversation.
    try:
        from ..api import production
        production.notify_ticket_created(ticket)
    except Exception:  # noqa: BLE001
        pass

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
    text = llm.compose_reply(res, state.get("order_context"), state.get("ticket_id"),
                              thread_id=state.get("thread_id"), rep_id=state.get("rep_id"))

    card = {
        "intent": state.get("intent"),
        "status": res.status,
        "root_cause": res.root_cause,
        "actions_taken": res.actions_taken,
        "capability": res.capability,
        "ticket_id": state.get("ticket_id"),
        "order_context": state.get("order_context"),
    }
    assistant_msg: dict = {"role": "assistant", "content": text, "card": card}
    # Attach an OST knowledge article as an A2UI element when the answer came from OST.
    article = state.get("article")
    if article:
        assistant_msg["a2ui"] = [article]
    return {"messages": [assistant_msg], "trace": _trace("compose", status=res.status)}


def route_by_state(state: GraphState) -> str:
    """Generic conditional edge: follow whatever `route` the prior node set."""
    return state.get("route") or "compose"
