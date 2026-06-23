"""Shared state object that flows through the orchestration graph."""
from __future__ import annotations

import operator
from typing import Annotated, Any, Optional

from typing_extensions import TypedDict


class GraphState(TypedDict, total=False):
    # Conversation — plain JSON-serializable dicts: {"role", "content", "card"?}
    messages: Annotated[list[dict], operator.add]

    # Who / where
    rep_id: Optional[str]
    thread_id: Optional[str]

    # Triage output
    intent: Optional[str]
    confidence: Optional[float]
    triage_summary: Optional[str]
    entities: dict
    order_context: Optional[dict]

    # Resolution flow
    route: Optional[str]               # set by nodes, read by conditional edges
    diagnosis: Optional[dict]          # what an agent found (even if it couldn't fix it)
    proposed_action: Optional[dict]    # mutating fix awaiting rep confirmation
    confirm_decision: Optional[bool]
    resolution: Optional[dict]         # final Resolution.model_dump()
    ticket_id: Optional[str]

    # Observability
    trace: Annotated[list[dict[str, Any]], operator.add]
