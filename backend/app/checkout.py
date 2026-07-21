"""Guided POS checkout engine — the 'View Together' → payment → signature wizard
that runs after the rep clicks *Review & place order*.

A checkout is a server-side, id-addressable `CheckoutSession` so the SAME flow
can be driven from the rep's screen AND the customer's phone (`/checkout/{id}`) —
the rep polls `get()` while the customer reviews/pays/signs on their own device.

Each mutating call returns a `view` dict `{checkout, element}`:
  - `checkout`: a serialized snapshot of the session (step, totals, account),
  - `element`: the A2UI element to render for the current step
    (`view_together` | `payment` | `signature` | `order_confirmation`).

Governance: payment is SIMULATED (a tender is *selected*, nothing is charged),
the signature is a demo artifact (a compact ref — never raw PII), the order is
recorded only at `sign()` with an audit row, and SMS is a mock preview. Mirrors
the "never a real charge" contract of `shop.place_order` / the graph confirm node.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import segno

from . import shop
from .config import get_settings
from .mock_services import shop_data
from .store import db

# Tender options offered at the payment step (all simulated).
_TENDERS = [
    {"id": "card_on_file", "label": "Visa ending 4242 · on file", "sub": "Charge the card we have on file"},
    {"id": "tap", "label": "Tap or insert card", "sub": "Present a card at the terminal"},
    {"id": "wallet", "label": "Apple Pay / Google Pay", "sub": "Contactless wallet"},
]
_TENDER_LABEL = {t["id"]: t["label"] for t in _TENDERS}


# --------------------------------------------------------------------------- #
# Lifecycle
# --------------------------------------------------------------------------- #
def start(thread_id: str, account_id: str | None = None, rep_id: str = "rep.demo") -> dict | None:
    """Snapshot the thread's cart into a new checkout session (step=review).
    Returns None if the cart is empty."""
    cart_row = db.get_cart(thread_id)
    # Fall back to the account the cart was built for, so the caller doesn't have
    # to re-supply it (the cart row remembers it from the shopping session).
    account_id = account_id or (cart_row.account_id if cart_row else None)
    account = shop_data.account_summary(account_id)
    items = shop.cart_view(list(cart_row.items) if cart_row else [])["items"]
    if not items:
        return None
    quote = shop.checkout_quote(items, account)
    session = db.create_checkout(
        thread_id=thread_id, rep_id=rep_id, account_id=account.get("account_id"),
        items=items, quote=quote, step="review", fulfillment=_default_fulfillment(items),
    )
    return _view(session, account)


def get(checkout_id: str) -> dict | None:
    session = db.get_checkout(checkout_id)
    return _view(session) if session else None


def advance(checkout_id: str, to: str | None = "payment") -> dict | None:
    session = db.get_checkout(checkout_id)
    if not session:
        return None
    if session.step == "review":
        session.step = "payment"
    db.save_checkout(session)
    return _view(session)


def pay(checkout_id: str, payment_method: str, fulfillment: str | None = None) -> dict | None:
    session = db.get_checkout(checkout_id)
    if not session:
        return None
    session.payment_method = _TENDER_LABEL.get(payment_method, payment_method or "Visa ending 4242")
    if fulfillment in ("pickup", "ship"):
        session.fulfillment = fulfillment
    session.step = "signature"
    db.save_checkout(session)
    return _view(session)


def sign(checkout_id: str, signature: str | None = None, receipt_channel: str | None = None) -> dict | None:
    """Capture the signature, place the order (SIMULATED payment), audit it, and
    clear the cart. Idempotent — a second call on a completed session just returns
    the confirmation, so the rep + phone can both land on `complete` safely."""
    session = db.get_checkout(checkout_id)
    if not session:
        return None
    if session.signed and session.order_id:
        return _view(session)

    account = shop_data.account_summary(session.account_id)
    sig_ref = _signature_ref(signature)
    result = shop.place_order(
        session.items, account, thread_id=session.thread_id, rep_id=session.rep_id,
        quote=session.quote, fulfillment=session.fulfillment,
        signature_ref=sig_ref, receipt_channel=receipt_channel,
    )
    db.record_action_audit(thread_id=session.thread_id, rep_id=session.rep_id,
                           service="shop", operation="place_order", approved=True, success=True)
    db.clear_cart(session.thread_id or "anon")

    session.signed = True
    session.signed_at = datetime.now(timezone.utc)
    session.signature_ref = sig_ref
    session.receipt_channel = receipt_channel
    session.order_id = result["order_id"]
    session.step = "complete"
    db.save_checkout(session)

    view = _view(session, account)
    view["order"] = result
    if receipt_channel in ("sms", "email"):
        view["receipt"] = _send_receipt(account, result, receipt_channel)
    return view


def send_to_phone(checkout_id: str, channel: str, origin: str | None = None,
                  phone: str | None = None) -> dict | None:
    """Hand the checkout off to the customer's phone. `qr` returns a scannable
    SVG data-URI of the `/checkout/{id}` link; `sms` returns a mock text preview
    (no real message is sent in the prototype)."""
    session = db.get_checkout(checkout_id)
    if not session:
        return None
    base = (origin or get_settings().frontend_origin or "").rstrip("/")
    link = f"{base}/checkout/{session.id}"
    account = shop_data.account_summary(session.account_id)
    to = phone or account.get("primary_phone")
    session.sent_channel = channel
    db.save_checkout(session)

    if channel == "qr":
        qr = segno.make(link, error="m")
        return {
            "channel": "qr", "link": link, "to": to,
            "qr_svg_data_uri": qr.svg_data_uri(scale=6, border=2, dark="#0b0b0b", light="#ffffff"),
        }
    # sms — mock/preview only
    body = f"Review & sign your order from {account.get('name', 'the store')}: {link}"
    return {
        "channel": "sms", "link": link, "to": to, "sent": False, "previewed": True, "body": body,
        "message": (f"Text preview ready for {to}" if to else "No number on file — show the QR instead"),
    }


# --------------------------------------------------------------------------- #
# View / element builders
# --------------------------------------------------------------------------- #
def _view(session, account: dict | None = None) -> dict:
    account = account or shop_data.account_summary(session.account_id)
    return {"checkout": _serialize(session, account), "element": _element_for(session, account)}


def _serialize(session, account: dict) -> dict:
    return {
        "id": session.id, "step": session.step, "thread_id": session.thread_id,
        "account_id": session.account_id, "customer_name": account.get("name"),
        "primary_phone": account.get("primary_phone"),
        "payment_method": session.payment_method, "fulfillment": session.fulfillment,
        "signed": session.signed, "order_id": session.order_id,
        "sent_channel": session.sent_channel, "quote": session.quote, "items": session.items,
    }


def _element_for(session, account: dict) -> dict | None:
    return {
        "review": _view_together_element,
        "payment": _payment_element,
        "signature": _signature_element,
        "complete": _complete_element,
    }.get(session.step, lambda s, a: None)(session, account)


def _view_together_element(session, account: dict) -> dict:
    q = session.quote or {}
    return {
        "type": "view_together",
        "checkout_id": session.id,
        "customer_name": account.get("name"),
        "account_id": session.account_id,
        "primary_phone": account.get("primary_phone"),
        "current_monthly": q.get("current_monthly"),
        "recurring_monthly": q.get("recurring_monthly", 0.0),
        "blended_monthly": q.get("blended_monthly", 0.0),
        "next_month_total": q.get("next_month_total", 0.0),
        "due_today": q.get("due_today", 0.0),
        "taxes": q.get("taxes", 0.0),
        "activation_fees": q.get("activation_fees", 0.0),
        "accessories_onetime": q.get("accessories_onetime", 0.0),
        "recurring_lines": q.get("recurring_lines", []),
        "onetime_lines": q.get("onetime_lines", []),
    }


def _payment_element(session, account: dict) -> dict:
    q = session.quote or {}
    return {
        "type": "payment",
        "checkout_id": session.id,
        "customer_name": account.get("name"),
        "due_today": q.get("due_today", 0.0),
        "recurring_monthly": q.get("recurring_monthly", 0.0),
        "blended_monthly": q.get("blended_monthly", 0.0),
        "tenders": _TENDERS,
        "fulfillment": session.fulfillment,
    }


def _signature_element(session, account: dict) -> dict:
    q = session.quote or {}
    return {
        "type": "signature",
        "checkout_id": session.id,
        "customer_name": account.get("name"),
        "payment_method": session.payment_method or "Visa ending 4242",
        "due_today": q.get("due_today", 0.0),
        "blended_monthly": q.get("blended_monthly", 0.0),
        "fulfillment": session.fulfillment,
    }


def _complete_element(session, account: dict) -> dict:
    """Rebuild the order-confirmation element from the session snapshot (so a
    phone polling a completed checkout also sees the receipt)."""
    q = session.quote or {}
    items = session.items or []
    perks = [{"name": it.get("name"), "monthly": it.get("monthly")} for it in items if it.get("kind") == "perk"]
    return {
        "type": "order_confirmation",
        "order_id": session.order_id,
        "items": items,
        "monthly_total": q.get("recurring_monthly", 0.0),
        "onetime_total": q.get("due_today", 0.0),
        "payment_method": session.payment_method or "Visa ending 4242",
        "current_monthly": q.get("current_monthly"),
        "recurring_monthly": q.get("recurring_monthly", 0.0),
        "blended_monthly": q.get("blended_monthly", 0.0),
        "taxes": q.get("taxes", 0.0),
        "activation_fees": q.get("activation_fees", 0.0),
        "due_today": q.get("due_today", 0.0),
        "onetime_lines": q.get("onetime_lines", []),
        "perks": perks,
        "fulfillment": session.fulfillment,
        "signature_ref": session.signature_ref,
        "receipt_channel": session.receipt_channel,
    }


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _default_fulfillment(items: list[dict]) -> str:
    return "ship" if any(it.get("fulfillment") == "ship" for it in items) else "pickup"


def _signature_ref(signature: str | None) -> str | None:
    """A compact, privacy-preserving reference to the captured signature — a hash
    of the drawn image or a typed marker. The raw signature is never stored."""
    if not signature:
        return None
    s = signature.strip()
    if s.startswith("data:image"):
        return "drawn-" + hashlib.sha256(s.encode()).hexdigest()[:10]
    return "typed-signature"


def _send_receipt(account: dict, result: dict, channel: str) -> dict:
    """Mock 'send the receipt' — a preview only; nothing is actually sent."""
    to = account.get("primary_phone") if channel == "sms" else None
    return {
        "channel": channel, "sent": False, "previewed": True, "to": to,
        "message": f"Receipt for order {result['order_id']} "
                   + (f"texted to {to}" if channel == "sms" and to else f"sent via {channel}"),
    }
