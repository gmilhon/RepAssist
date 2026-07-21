"""Offline tests for the guided POS checkout wizard + merchandising add-ons.

Runs with the LLM forced off so the deterministic interpreter drives the cart
(no credentials). Covers: protection/perk/accessory ops + totals, the always-on
protection recommendation, the View Together quote math (taxes + activation +
accessories → due today; blended monthly), the checkout lifecycle (start →
advance → pay → sign) placing an order with the full breakdown + an audit row +
a cleared cart, the phone-sync GET contract, and send-to-phone (SMS + QR).
Run: pytest -q
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import checkout as checkout_engine
from app import shop
from app.config import get_settings
from app.main import app
from app.mock_services import shop_data as cat
from app.store import db
from app.store.models import ActionAudit, ShopOrder

_client = TestClient(app)

DEMO_MSGS = [
    "add a new line with a Pixel 10 on Unlimited Ultimate",
    "add device protection to the Pixel 10",
    "add the Netflix perk",
    "grab a protective case too",
]


def _thread() -> str:
    return f"cotest-{uuid.uuid4().hex[:8]}"


@pytest.fixture(autouse=True)
def offline_llm(monkeypatch):
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "")


def _build_cart(thread: str, account_id: str = "AC-3003", msgs=DEMO_MSGS):
    acct = cat.account_summary(account_id)
    items: list = []
    for m in msgs:
        turn = shop.fallback_interpret(m, acct, items)
        items, _ = shop.apply_ops(items, turn.ops, acct)
    db.save_cart(thread, items, account_id=account_id)
    return items, acct


def _order(order_id: str) -> ShopOrder | None:
    with Session(db._engine) as s:
        return s.get(ShopOrder, order_id)


def test_addons_mutate_cart_and_totals(offline_llm):
    thread = _thread()
    items, _ = _build_cart(thread)
    view = shop.cart_view(items)
    kinds = [it["kind"] for it in view["items"]]
    assert kinds.count("perk") == 1
    assert kinds.count("accessory") == 1
    dev = next(it for it in view["items"] if it["kind"] == "new_line")
    assert dev["protection"] and dev["protection"]["name"]
    # Pixel financed + Ultimate + protection, plus the $10 perk on top.
    assert view["monthly_total"] > 100
    # The accessory is the only one-time item.
    assert view["onetime_total"] == pytest.approx(39.99, abs=0.01)
    db.clear_cart(thread)


def test_protection_is_always_recommended(offline_llm):
    thread = _thread()
    items, acct = _build_cart(thread, msgs=["add a new line with a Pixel 10 on Unlimited Ultimate"])
    recs = shop.cart_view(items)["recommendations"]
    assert any(r["kind"] == "protection" and "Pixel 10" in (r["target"] or "") for r in recs)
    # Once protection is on the device, the recommendation drops off.
    turn = shop.fallback_interpret("add device protection to the Pixel 10", acct, items)
    items, _ = shop.apply_ops(items, turn.ops, acct)
    assert not any(r["kind"] == "protection" for r in shop.cart_view(items)["recommendations"])
    db.clear_cart(thread)


def test_quote_due_today_math(offline_llm):
    thread = _thread()
    items, acct = _build_cart(thread)
    q = shop.checkout_quote(items, acct)
    assert q["current_monthly"] == 245.0                     # existing 3 lines + FWA
    assert q["activation_fees"] == cat.ACTIVATION_FEE        # one new device line
    assert q["accessories_onetime"] == pytest.approx(39.99, abs=0.01)
    expected_tax = round(cat.TAX_RATE * (799.0 + 39.99), 2)  # device retail + accessory
    assert q["taxes"] == pytest.approx(expected_tax, abs=0.01)
    assert q["due_today"] == pytest.approx(q["activation_fees"] + q["taxes"] + q["accessories_onetime"], abs=0.01)
    assert q["blended_monthly"] == pytest.approx(q["current_monthly"] + q["recurring_monthly"], abs=0.01)
    db.clear_cart(thread)


def test_checkout_lifecycle_places_order(offline_llm):
    thread = _thread()
    _build_cart(thread)
    v = checkout_engine.start(thread, "AC-3003")
    cid = v["checkout"]["id"]
    assert v["element"]["type"] == "view_together"
    assert v["element"]["current_monthly"] == 245.0
    assert v["element"]["due_today"] > 0

    assert checkout_engine.advance(cid)["element"]["type"] == "payment"
    assert checkout_engine.pay(cid, "card_on_file", "ship")["element"]["type"] == "signature"

    done = checkout_engine.sign(cid, signature="data:image/png;base64,AAAA", receipt_channel="sms")
    assert done["checkout"]["step"] == "complete"
    order_id = done["order"]["order_id"]
    assert order_id.startswith("SO-")

    # Order persisted with the one-time breakdown + fulfillment + signature ref.
    order = _order(order_id)
    assert order is not None
    assert order.activation_fees == cat.ACTIVATION_FEE
    assert order.taxes > 0
    assert order.fulfillment == "ship"
    assert order.signature_ref  # a compact, non-PII reference
    assert any(p["name"] == "Netflix" for p in order.perks)

    # Cart cleared, phone-sync GET reflects the completed order, sign is idempotent.
    assert db.get_cart(thread) is None
    g = checkout_engine.get(cid)
    assert g["element"]["type"] == "order_confirmation" and g["element"]["order_id"] == order_id
    assert checkout_engine.sign(cid)["checkout"]["order_id"] == order_id

    # A confirm-gate audit row was recorded for the placement.
    with Session(db._engine) as s:
        rows = s.exec(select(ActionAudit).where(ActionAudit.thread_id == thread)).all()
    assert any(r.operation == "place_order" and r.approved and r.success for r in rows)


def test_send_to_phone_sms_and_qr(offline_llm):
    thread = _thread()
    _build_cart(thread)
    r = _client.post("/api/shop/checkout/start", json={"thread_id": thread, "account_id": "AC-3003"})
    assert r.status_code == 200
    cid = r.json()["checkout"]["id"]

    qr = _client.post(f"/api/shop/checkout/{cid}/send-to-phone",
                      json={"channel": "qr", "origin": "http://localhost:5173"}).json()
    assert qr["qr_svg_data_uri"].startswith("data:image/svg+xml")
    assert qr["link"] == f"http://localhost:5173/checkout/{cid}"

    sms = _client.post(f"/api/shop/checkout/{cid}/send-to-phone",
                       json={"channel": "sms", "origin": "http://localhost:5173"}).json()
    assert sms["previewed"] is True and sms["sent"] is False
    assert sms["to"]  # primary phone on file for AC-3003
    db.clear_cart(thread)


def test_checkout_http_flow(offline_llm):
    thread = _thread()
    _build_cart(thread)
    cid = _client.post("/api/shop/checkout/start", json={"thread_id": thread, "account_id": "AC-3003"}).json()["checkout"]["id"]
    assert _client.post(f"/api/shop/checkout/{cid}/advance", json={}).json()["element"]["type"] == "payment"
    assert _client.post(f"/api/shop/checkout/{cid}/pay", json={"payment_method": "tap"}).json()["element"]["type"] == "signature"
    done = _client.post(f"/api/shop/checkout/{cid}/sign", json={"signature": "data:image/png;base64,AAAA"}).json()
    assert done["element"]["type"] == "order_confirmation"
    assert done["checkout"]["step"] == "complete"


def test_start_rejects_empty_cart(offline_llm):
    r = _client.post("/api/shop/checkout/start", json={"thread_id": _thread(), "account_id": "AC-3003"})
    assert r.status_code == 400
