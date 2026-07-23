"""Read endpoints for the in-chat shopping experience.

The cart is *built* through the chat (graph.nodes.shop) and returned on each
`/api/chat` response; these endpoints let the UI fetch the customer's account
summary (shown when assisting from the queue), the current cart (e.g. on load),
and the catalog for reference. No order/payment yet — this is the phase-1 slice.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from .. import llm, shop as shop_engine, switch_analysis
from ..mock_services import shop_data
from ..schemas import CompetitorBill
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


# --------------------------------------------------------------------------- #
# Scan Barcode — resolve a UPC to a catalog product
# --------------------------------------------------------------------------- #
@router.get("/product-by-upc")
def product_by_upc(upc: str) -> dict:
    """Look a scanned UPC up in the catalog. `product` is null if unknown."""
    return {"upc": upc, "product": switch_analysis.product_for_upc(upc)}


# --------------------------------------------------------------------------- #
# Scan Bill — OCR a competitor bill, then build a switch quote
# --------------------------------------------------------------------------- #
class ScanBillRequest(BaseModel):
    image_base64: str = Field(description="Base64-encoded image bytes (no data: prefix).")
    media_type: str = Field(default="image/jpeg", description="image/jpeg | image/png | image/webp | image/gif")
    thread_id: Optional[str] = None


class SwitchQuoteRequest(BaseModel):
    bill: CompetitorBill
    # Additional 3rd-party services the rep identifies with the customer, e.g.
    # {"streaming": [{"name": "Netflix", "monthly": 22.99}],
    #  "home_internet": {"name": "Xfinity 400", "monthly": 70}}
    extras: dict[str, Any] = Field(default_factory=dict)


@router.post("/scan-bill")
def scan_bill(req: ScanBillRequest) -> dict:
    """Extract a competitor bill from a photo and return an initial switch quote."""
    media = req.media_type if req.media_type in llm.BILL_MEDIA_TYPES else "image/jpeg"
    bill = llm.analyze_competitor_bill(req.image_base64, media, thread_id=req.thread_id)
    quote = switch_analysis.build_switch_quote(bill, {})
    return {"bill": bill.model_dump(), "quote": quote}


@router.post("/switch-quote")
def switch_quote(req: SwitchQuoteRequest) -> dict:
    """Recompute the switch quote after the rep adds 3rd-party services/bundles."""
    quote = switch_analysis.build_switch_quote(req.bill, req.extras)
    return {"bill": req.bill.model_dump(), "quote": quote}
