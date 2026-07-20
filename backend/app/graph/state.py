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
    sales_intent: Optional[str]         # nse | aal | up | None — heuristic tag, see llm.tag_sales_intent
    triage_summary: Optional[str]
    entities: dict
    order_context: Optional[dict]
    awaiting: Optional[str]             # entity the assistant asked the rep for (slot-fill)

    # Resolution flow
    route: Optional[str]               # set by nodes, read by conditional edges
    article: Optional[dict]            # OST knowledge_article A2UI element, if any
    diagnosis: Optional[dict]          # what an agent found (even if it couldn't fix it)
    proposed_action: Optional[dict]    # mutating fix awaiting rep confirmation
    confirm_decision: Optional[bool]
    resolution: Optional[dict]         # final Resolution.model_dump()
    ticket_id: Optional[str]

    # External CES relay (see graph.nodes.ces_remote)
    ces_active: Optional[bool]         # a CES sub-conversation currently owns this thread (sticky)
    ces_session_id: Optional[str]      # reused across turns so CES keeps context

    # In-chat shopping (see graph.nodes.shop)
    shop_active: Optional[bool]        # a shopping session owns this thread (sticky)
    cart: Optional[dict]              # latest cart view {items, monthly_total, onetime_total} for the drawer

    # Observability
    trace: Annotated[list[dict[str, Any]], operator.add]
