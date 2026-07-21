"""HTTP endpoints for the guided POS checkout wizard (View Together → payment →
signature → confirmation). Both the rep's screen and the customer's phone
(`/checkout/{id}`) drive the SAME session through these routes — see
`app.checkout` for the engine and the "never a real charge" governance notes.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import checkout as checkout_engine

router = APIRouter(prefix="/api/shop/checkout", tags=["checkout"])


class StartRequest(BaseModel):
    thread_id: str
    account_id: Optional[str] = None
    rep_id: str = "rep.demo"


class AdvanceRequest(BaseModel):
    to: Optional[str] = "payment"


class PayRequest(BaseModel):
    payment_method: str
    fulfillment: Optional[str] = None


class SignRequest(BaseModel):
    signature: Optional[str] = None      # drawn data-URL or typed name (not stored raw)
    receipt_channel: Optional[str] = None  # sms | email | none


class SendToPhoneRequest(BaseModel):
    channel: str                          # sms | qr
    origin: Optional[str] = None          # the caller's window.location.origin
    phone: Optional[str] = None


@router.post("/start")
def start(req: StartRequest) -> dict:
    view = checkout_engine.start(req.thread_id, req.account_id, req.rep_id)
    if view is None:
        raise HTTPException(status_code=400, detail="The cart is empty — add an item before checking out.")
    return view


@router.get("/{checkout_id}")
def get(checkout_id: str) -> dict:
    view = checkout_engine.get(checkout_id)
    if view is None:
        raise HTTPException(status_code=404, detail="Checkout not found")
    return view


@router.post("/{checkout_id}/advance")
def advance(checkout_id: str, req: AdvanceRequest) -> dict:
    view = checkout_engine.advance(checkout_id, req.to)
    if view is None:
        raise HTTPException(status_code=404, detail="Checkout not found")
    return view


@router.post("/{checkout_id}/pay")
def pay(checkout_id: str, req: PayRequest) -> dict:
    view = checkout_engine.pay(checkout_id, req.payment_method, req.fulfillment)
    if view is None:
        raise HTTPException(status_code=404, detail="Checkout not found")
    return view


@router.post("/{checkout_id}/sign")
def sign(checkout_id: str, req: SignRequest) -> dict:
    view = checkout_engine.sign(checkout_id, req.signature, req.receipt_channel)
    if view is None:
        raise HTTPException(status_code=404, detail="Checkout not found")
    return view


@router.post("/{checkout_id}/send-to-phone")
def send_to_phone(checkout_id: str, req: SendToPhoneRequest) -> dict:
    result = checkout_engine.send_to_phone(checkout_id, req.channel, req.origin, req.phone)
    if result is None:
        raise HTTPException(status_code=404, detail="Checkout not found")
    return result
