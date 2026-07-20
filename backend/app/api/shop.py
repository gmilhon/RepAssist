"""Read endpoints for the in-chat shopping experience.

The cart is *built* through the chat (graph.nodes.shop) and returned on each
`/api/chat` response; these endpoints let the UI fetch the customer's account
summary (shown when assisting from the queue), the current cart (e.g. on load),
and the catalog for reference. No order/payment yet — this is the phase-1 slice.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter

from .. import shop as shop_engine
from ..mock_services import shop_data
from ..store import db

router = APIRouter(prefix="/api/shop", tags=["shop"])


@router.get("/account")
def account(account_id: Optional[str] = None) -> dict:
    """Full account summary + an A2UI element the chat can render as a card."""
    summary = shop_data.account_summary(account_id)
    return {"summary": summary, "elements": [{"type": "account_summary", **summary}]}


@router.get("/catalog")
def catalog() -> dict:
    return {"devices": shop_data.DEVICES, "plans": shop_data.PLANS, "promos": shop_data.PROMOS}


@router.get("/cart/{thread_id}")
def cart(thread_id: str) -> dict:
    row = db.get_cart(thread_id)
    return shop_engine.cart_view(list(row.items) if row else [])
