"""Builds and compiles the LangGraph orchestrator, and exposes run/resume
helpers that the API layer calls.

Flow:

    START → triage ─┬→ activation ──┐
                    ├→ pending_order┤→ confirm ─┬→ compose → END
                    ├→ promo ───────┘           └→ ticket_fallback → compose
                    ├→ occ ─────────────────────→ confirm / ticket_fallback
                    ├→ knowledge ───────────────→ compose
                    └→ ticket_fallback ─────────→ compose

`confirm` issues a LangGraph `interrupt()` so the rep can approve/deny any
mutating fix; the API surfaces it and resumes with `Command(resume=...)`.
"""
from __future__ import annotations

import sqlite3
from functools import lru_cache

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from ..config import get_settings
from ..store import db
from . import nodes
from .state import GraphState


def _build() :
    builder = StateGraph(GraphState)

    builder.add_node("triage", nodes.triage)
    builder.add_node("clarify", nodes.clarify)
    builder.add_node("system_help", nodes.system_help)
    builder.add_node("activation", nodes.activation_resolver)
    builder.add_node("pending_order", nodes.pending_order_resolver)
    builder.add_node("promo", nodes.promo_resolver)
    builder.add_node("occ", nodes.occ_resolver)
    builder.add_node("knowledge", nodes.knowledge)
    builder.add_node("confirm", nodes.confirm)
    builder.add_node("ticket_fallback", nodes.ticket_fallback)
    builder.add_node("compose", nodes.compose)

    builder.add_edge(START, "triage")
    builder.add_conditional_edges(
        "triage",
        nodes.route_after_triage,
        {
            "clarify": "clarify",
            "system_help": "system_help",
            "activation": "activation",
            "pending_order": "pending_order",
            "promo": "promo",
            "occ": "occ",
            "knowledge": "knowledge",
            "ticket_fallback": "ticket_fallback",
        },
    )
    # clarify and system_help are terminal — they reply directly.
    builder.add_edge("clarify", END)
    builder.add_edge("system_help", END)
    for resolver in ("activation", "pending_order", "promo", "occ"):
        builder.add_conditional_edges(
            resolver,
            nodes.route_by_state,
            {"confirm": "confirm", "ticket_fallback": "ticket_fallback", "compose": "compose"},
        )
    builder.add_conditional_edges(
        "knowledge",
        nodes.route_by_state,
        {"compose": "compose", "ticket_fallback": "ticket_fallback"},
    )
    builder.add_conditional_edges(
        "confirm",
        nodes.route_by_state,
        {"compose": "compose", "ticket_fallback": "ticket_fallback"},
    )
    builder.add_edge("ticket_fallback", "compose")
    builder.add_edge("compose", END)
    return builder


@lru_cache
def get_graph():
    conn = sqlite3.connect(get_settings().checkpoint_db, check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    try:
        checkpointer.setup()
    except Exception:  # noqa: BLE001 - older/newer versions set up lazily
        pass
    return _build().compile(checkpointer=checkpointer)


# --------------------------------------------------------------------------- #
# Run helpers
# --------------------------------------------------------------------------- #
def _config(thread_id: str) -> dict:
    return {
        "configurable": {"thread_id": thread_id},
        "run_name": "rep-assist-conversation",
    }


def _pending_interrupt(snapshot):
    for task in snapshot.tasks:
        if task.interrupts:
            return task.interrupts[0].value
    return None


def _shape(thread_id: str, snapshot) -> dict:
    values = snapshot.values
    interrupt_val = _pending_interrupt(snapshot)
    if interrupt_val is not None:
        return {
            "thread_id": thread_id,
            "status": "needs_confirmation",
            "assistant_message": None,
            "card": None,
            "confirmation": interrupt_val,
            "intent": values.get("intent"),
            "confidence": values.get("confidence"),
            "rep_id": values.get("rep_id"),
            "ticket_id": values.get("ticket_id"),
            "trace": values.get("trace", []),
        }

    messages = values.get("messages", [])
    last_assistant = next(
        (m for m in reversed(messages) if m.get("role") == "assistant"), None
    )
    resolution = values.get("resolution") or {}
    status = "escalated" if resolution.get("status") == "escalated" else "answered"
    return {
        "thread_id": thread_id,
        "status": status,
        "assistant_message": (last_assistant or {}).get("content"),
        "card": (last_assistant or {}).get("card"),
        "confirmation": None,
        "intent": values.get("intent"),
        "confidence": values.get("confidence"),
        "rep_id": values.get("rep_id"),
        "ticket_id": values.get("ticket_id"),
        "trace": values.get("trace", []),
    }


def _record(result: dict, kind: str, confirmed: bool | None = None) -> None:
    card = result.get("card") or {}
    db.record_engagement(
        thread_id=result.get("thread_id"),
        rep_id=result.get("rep_id"),
        kind=kind,
        intent=result.get("intent"),
        confidence=result.get("confidence"),
        status=result.get("status"),
        resolution_status=card.get("status"),
        capability=card.get("capability"),
        confirmed=confirmed,
        ticket_id=result.get("ticket_id"),
    )


def start_or_continue(thread_id: str, user_text: str, rep_id: str | None = None) -> dict:
    graph = get_graph()
    cfg = _config(thread_id)
    graph.invoke(
        {
            "messages": [{"role": "user", "content": user_text}],
            "rep_id": rep_id,
            "thread_id": thread_id,
        },
        cfg,
    )
    result = _shape(thread_id, graph.get_state(cfg))
    _record(result, kind="message")
    return result


def resume(thread_id: str, approved: bool) -> dict:
    graph = get_graph()
    cfg = _config(thread_id)
    graph.invoke(Command(resume=approved), cfg)
    result = _shape(thread_id, graph.get_state(cfg))
    _record(result, kind="confirmation", confirmed=approved)
    return result
