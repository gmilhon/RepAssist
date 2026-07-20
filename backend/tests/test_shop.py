"""Offline tests for the in-chat shopping slice (add a line / upgrade).

Runs with the LLM forced off so the deterministic rule-based interpreter
(`shop.fallback_interpret`) drives the cart — no credentials needed. Covers
intent routing, cart building/editing, the sticky session + exit, and the
account-summary + cart read endpoints. Run: pytest -q
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.graph import orchestrator
from app.main import app
from app.store import db

_client = TestClient(app)


def _thread() -> str:
    return f"shoptest-{uuid.uuid4().hex[:8]}"


@pytest.fixture(autouse=True)
def offline_llm(monkeypatch):
    # Force the rule-based interpreter so the test is deterministic + credential-free.
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "")


def _cart_items(res: dict) -> list:
    return (res.get("cart") or {}).get("items", [])


def test_add_line_builds_cart(offline_llm):
    thread = _thread()
    res = orchestrator.start_or_continue(
        thread, "Add a new line with an iPhone 17 Pro on Unlimited Ultimate",
        initial_entities={"account_id": "AC-3003"},
    )
    assert res["intent"] == "add_line"
    assert res["shop_active"] is True
    items = _cart_items(res)
    assert len(items) == 1
    assert items[0]["device"] == "iPhone 17 Pro"
    assert items[0]["plan"] == "Unlimited Ultimate"
    assert res["cart"]["monthly_total"] > 0
    db.clear_cart(thread)


def test_sticky_follow_up_and_edit(offline_llm):
    thread = _thread()
    orchestrator.start_or_continue(thread, "add a line with a Pixel 10 on Unlimited Plus",
                                   initial_entities={"account_id": "AC-3003"})
    # A bare follow-up ("Galaxy S26") classifies as low-confidence 'other' but the
    # sticky shopping session keeps the thread on the shop node — here an edit.
    r2 = orchestrator.start_or_continue(thread, "actually change it to the Galaxy S26")
    items = _cart_items(r2)
    assert len(items) == 1, "edit should not add a second item"
    assert items[0]["device"] == "Galaxy S26"
    db.clear_cart(thread)


def test_upgrade_auto_attaches_account_promo(offline_llm):
    thread = _thread()
    res = orchestrator.start_or_continue(
        thread, "upgrade line 1 to an iPhone 17 Pro",
        initial_entities={"account_id": "AC-3003"},  # has a $200 trade-in promo
    )
    assert res["intent"] == "upgrade"
    item = _cart_items(res)[0]
    assert item["kind"] == "upgrade"
    assert item["line_id"] == "L1"
    assert item["promo"] and "trade-in" in item["promo"].lower()
    db.clear_cart(thread)


def test_exit_ends_session(offline_llm):
    thread = _thread()
    orchestrator.start_or_continue(thread, "add a line with a Pixel 10",
                                   initial_entities={"account_id": "AC-3003"})
    r = orchestrator.start_or_continue(thread, "that's all for now")
    assert r["shop_active"] is False
    db.clear_cart(thread)


def test_checkout_confirm_places_order(offline_llm):
    thread = _thread()
    orchestrator.start_or_continue(thread, "add a line with an iPhone 17 Pro on Unlimited Ultimate",
                                   initial_entities={"account_id": "AC-3003"})
    res = orchestrator.start_or_continue(thread, "ok place the order")
    assert res["status"] == "needs_confirmation"
    assert res["confirmation"]["action"]["service"] == "shop"
    assert "$" in res["confirmation"]["action"]["human_prompt"]

    done = orchestrator.resume(thread, approved=True)
    assert done["status"] == "answered"
    assert "Order SO-" in done["assistant_message"]
    assert done["a2ui"] and done["a2ui"][0]["type"] == "order_confirmation"
    assert done["a2ui"][0]["payment_method"]  # simulated payment recorded
    assert (done["cart"] or {}).get("items") == []  # cart cleared on placement
    assert done["shop_active"] is False


def test_checkout_decline_keeps_cart(offline_llm):
    thread = _thread()
    orchestrator.start_or_continue(thread, "add a line with a Pixel 10",
                                   initial_entities={"account_id": "AC-3003"})
    orchestrator.start_or_continue(thread, "checkout")
    dec = orchestrator.resume(thread, approved=False)
    assert len(_cart_items(dec)) == 1  # cart preserved
    assert dec["shop_active"] is True
    db.clear_cart(thread)


def test_listen_cart_mutation(offline_llm):
    from app.api.listen import _cart_from_listen, _has_cart_hint
    from app.store.models import ListenSession
    thread = _thread()
    orchestrator.start_or_continue(thread, "add a line with an iPhone 17 Pro on Unlimited Ultimate",
                                   initial_entities={"account_id": "AC-3003"})
    sess = ListenSession(id="LS-T", rep_id="rep.demo", thread_id=thread, account_id="AC-3003")
    upd = _cart_from_listen(sess, "let's change that to the Galaxy S26 instead")
    assert upd and upd["cart"]["items"][0]["device"] == "Galaxy S26"
    # ambient conversation with no shopping hint is skipped (no spurious LLM call)
    assert not _has_cart_hint("the weather is nice today")
    assert _cart_from_listen(sess, "the weather is nice today") is None
    db.clear_cart(thread)


def test_shop_endpoints():
    a = _client.get("/api/shop/account?account_id=AC-3003").json()
    assert a["summary"]["name"] == "J. Rivera"
    assert len(a["summary"]["lines"]) == 3
    assert a["summary"]["home_internet"]["product"] == "fwa"
    assert a["elements"][0]["type"] == "account_summary"

    cat = _client.get("/api/shop/catalog").json()
    assert len(cat["devices"]) >= 6 and len(cat["plans"]) >= 3

    # Unknown account falls back to a default profile (never errors).
    d = _client.get("/api/shop/account").json()
    assert d["summary"]["name"] == "Guest"
