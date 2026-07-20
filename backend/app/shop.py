"""Shopping-cart engine for the in-chat add-a-line / upgrade experience.

`apply_ops` deterministically applies the structured `CartOp` mutations (from
either the LLM interpreter in `llm.interpret_shop_turn` or the offline
`fallback_interpret` below) to the cart, matching devices/plans/promos against
the catalog and recomputing per-item and cart totals. Prices are illustrative
(device payment over `TERM_MONTHS`); nothing here charges anything.
"""
from __future__ import annotations

import re
import uuid

from .mock_services import shop_data as cat
from .schemas import CartOp, ShopTurn


def _item_id() -> str:
    return "it-" + uuid.uuid4().hex[:6]


# --------------------------------------------------------------------------- #
# Costing
# --------------------------------------------------------------------------- #
def _recost(item: dict) -> dict:
    """Recompute an item's monthly/onetime + human summary from its device/plan/
    promo. Device is financed over the term; a trade-in promo credits the device,
    a line-discount promo reduces the monthly plan cost."""
    device = cat.find_device(item.get("device")) if item.get("device") else None
    plan = cat.plan_by_name(item.get("plan")) if item.get("plan") else None
    promo = cat.promo_by_label(item.get("promo")) if item.get("promo") else None

    device_credit = promo.get("device_credit", 0.0) if promo and promo["kind"] == "trade_in" else 0.0
    monthly_off = promo.get("monthly_off", 0.0) if promo and promo["kind"] == "line_discount" else 0.0

    device_monthly = cat.device_monthly(max(0.0, (device["price"] if device else 0.0) - device_credit))
    plan_monthly = max(0.0, (plan["price"] if plan else 0.0) - monthly_off)
    item["monthly"] = round(device_monthly + plan_monthly, 2)
    item["onetime"] = 0.0

    kind_label = {"new_line": "New line", "upgrade": "Upgrade", "home_internet": "Home internet"}.get(item["kind"], item["kind"])
    if item["kind"] == "upgrade" and item.get("line_id"):
        kind_label = f"Upgrade {item['line_id']}"
    parts = [kind_label]
    parts.append(item.get("device") or "device TBD")
    parts.append(item.get("plan") or "plan TBD")
    if item.get("promo"):
        parts.append(f"promo: {item['promo']}")
    item["summary"] = " · ".join(parts)
    return item


def cart_view(items: list[dict]) -> dict:
    items = [_recost(dict(it)) for it in items]
    return {
        "items": items,
        "monthly_total": round(sum(it["monthly"] for it in items), 2),
        "onetime_total": round(sum(it["onetime"] for it in items), 2),
    }


# --------------------------------------------------------------------------- #
# Checkout — SIMULATED payment only (no real charge is ever made)
# --------------------------------------------------------------------------- #
_MOCK_CARD = "Visa ending 4242"  # card "on file" for the demo — never a real card
_CHECKOUT = (
    "place the order", "place order", "check out", "checkout", "submit the order",
    "submit order", "complete the order", "complete order", "ready to pay",
    "pay now", "finalize the order", "confirm the order", "process the order",
)


def wants_checkout(text: str) -> bool:
    t = text.lower()
    return any(p in t for p in _CHECKOUT)


def order_prompt(items: list[dict]) -> str:
    """The rep-facing confirmation shown at the checkout gate."""
    view = cart_view(items)
    n = len(view["items"])
    return (
        f"Place this order — {n} item{'s' if n != 1 else ''}, "
        f"${view['monthly_total']:.2f}/mo"
        + (f" + ${view['onetime_total']:.2f} today" if view["onetime_total"] else "")
        + f", charged to {_MOCK_CARD}?"
    )


def place_order(items: list[dict], account: dict, thread_id: str | None = None,
                rep_id: str | None = None) -> dict:
    """Record the order and SIMULATE taking payment. Returns the confirmation
    (order id, items, totals, masked card). No real payment is processed."""
    from .store import db
    view = cart_view(items)
    order = db.create_shop_order(
        thread_id=thread_id, rep_id=rep_id, account_id=account.get("account_id"),
        items=view["items"], monthly_total=view["monthly_total"],
        onetime_total=view["onetime_total"], payment_method=_MOCK_CARD,
    )
    return {
        "order_id": order.id,
        "items": view["items"],
        "monthly_total": view["monthly_total"],
        "onetime_total": view["onetime_total"],
        "payment_method": _MOCK_CARD,
    }


# --------------------------------------------------------------------------- #
# Applying structured ops
# --------------------------------------------------------------------------- #
def _target_item(items: list[dict], target: str | None) -> dict | None:
    """Resolve which cart item an op targets: by device name, by kind keyword,
    or (default) the most recently added item."""
    if not items:
        return None
    if target:
        t = target.lower()
        for it in reversed(items):
            if it.get("device") and it["device"].lower() in t:
                return it
        if "upgrade" in t:
            return next((it for it in reversed(items) if it["kind"] == "upgrade"), None)
        if "line" in t:
            return next((it for it in reversed(items) if it["kind"] == "new_line"), None)
    return items[-1]


def apply_ops(items: list[dict], ops: list[CartOp], account: dict) -> tuple[list[dict], list[str]]:
    """Apply the ops to a copy of `items`; return (new_items, change_notes)."""
    items = [dict(it) for it in items]
    notes: list[str] = []

    for op in ops:
        kind = op.op
        device = cat.find_device(op.device) if op.device else None
        plan = cat.plan_by_name(op.plan) or cat.find_plan(op.plan) if op.plan else None
        promo = cat.promo_by_label(op.promo) or cat.find_promo(op.promo) if op.promo else None

        if kind == "add_line":
            dtype = device["type"] if device else "phone"
            item = {
                "item_id": _item_id(), "kind": "new_line",
                "device": device["name"] if device else None, "device_type": dtype,
                "plan": (plan or cat.default_plan_for_type(dtype))["name"] if (plan or device) else None,
                "promo": promo["label"] if promo else None, "line_id": None,
            }
            items.append(_recost(item))
            notes.append(f"Added a new line{f' — {device['name']}' if device else ''}")

        elif kind == "upgrade":
            line = _match_line(account, op.line_id)
            dtype = device["type"] if device else "phone"
            item = {
                "item_id": _item_id(), "kind": "upgrade",
                "device": device["name"] if device else None, "device_type": dtype,
                "plan": (plan["name"] if plan else (line.get("plan") if line else None)),
                "promo": promo["label"] if promo else _auto_upgrade_promo(account),
                "line_id": line["line_id"] if line else (op.line_id or None),
            }
            items.append(_recost(item))
            notes.append(f"Started an upgrade{f' on {line['line_id']} ({line['phone']})' if line else ''}")

        elif kind == "set_device" and device:
            it = _target_item(items, op.target)
            if it:
                it["device"], it["device_type"] = device["name"], device["type"]
                _recost(it); notes.append(f"Set device to {device['name']}")

        elif kind == "set_plan" and plan:
            it = _target_item(items, op.target)
            if it:
                it["plan"] = plan["name"]; _recost(it); notes.append(f"Set plan to {plan['name']}")

        elif kind == "apply_promo" and promo:
            it = _target_item(items, op.target)
            if it:
                it["promo"] = promo["label"]; _recost(it); notes.append(f"Applied promo: {promo['label']}")

        elif kind == "remove_item":
            it = _target_item(items, op.target)
            if it:
                items = [x for x in items if x["item_id"] != it["item_id"]]
                notes.append(f"Removed {it.get('device') or it['kind']}")

        elif kind == "clear":
            items = []; notes.append("Cleared the cart")

    return items, notes


def _match_line(account: dict, line_id: str | None) -> dict | None:
    lines = account.get("lines", [])
    if line_id:
        lid = line_id.strip().upper()
        for ln in lines:
            if ln["line_id"].upper() == lid or lid in ln.get("phone", ""):
                return ln
    return None


def _auto_upgrade_promo(account: dict) -> str | None:
    """Auto-attach the account's upgrade promo, if any (the eligibility signal)."""
    return (account.get("eligibility") or {}).get("upgrade_promo")


# --------------------------------------------------------------------------- #
# Offline fallback interpreter (no LLM key / live call failed)
# --------------------------------------------------------------------------- #
_ADD = ("add a line", "add line", "new line", "another line", "add a phone", "second line")
_UP = ("upgrade", "trade in", "trade-in", "new phone for", "swap")
_REMOVE = ("remove", "delete", "take off", "drop the")
_CLEAR = ("clear the cart", "empty the cart", "start over", "clear cart")
# Edit verbs take precedence over add/upgrade so "change the new line to X" edits
# the existing item instead of adding one.
_EDIT = ("change", "make it", "switch", "set the", "instead", "actually", "rather")


def fallback_interpret(text: str, account: dict, items: list[dict]) -> ShopTurn:
    """Rule-based interpretation for offline mode: match catalog device/plan/
    promo names and shopping verbs from the rep's text."""
    t = text.lower()
    device = cat.find_device(text)
    plan = cat.find_plan(text)
    promo = cat.find_promo(text)
    line_id = _line_ref(text)
    ops: list[CartOp] = []

    if any(k in t for k in _CLEAR):
        ops.append(CartOp(op="clear"))
    elif any(k in t for k in _REMOVE):
        ops.append(CartOp(op="remove_item", target=device["name"] if device else None))
    elif any(k in t for k in _EDIT) and (device or plan or promo) and items:
        # Editing an item already in the cart (takes precedence over add/upgrade).
        if device:
            ops.append(CartOp(op="set_device", device=device["name"]))
        if plan:
            ops.append(CartOp(op="set_plan", plan=plan["name"]))
        if promo:
            ops.append(CartOp(op="apply_promo", promo=promo["label"]))
    elif any(k in t for k in _UP) or line_id:
        ops.append(CartOp(op="upgrade", device=device["name"] if device else None,
                          plan=plan["name"] if plan else None, line_id=line_id,
                          promo=promo["label"] if promo else None))
    elif any(k in t for k in _ADD):
        ops.append(CartOp(op="add_line", device=device["name"] if device else None,
                          plan=plan["name"] if plan else None,
                          promo=promo["label"] if promo else None))
    else:
        # No new item verb — treat named device/plan/promo as edits to the last item.
        if device:
            ops.append(CartOp(op="set_device", device=device["name"]))
        if plan:
            ops.append(CartOp(op="set_plan", plan=plan["name"]))
        if promo:
            ops.append(CartOp(op="apply_promo", promo=promo["label"]))

    if not ops:
        return ShopTurn(ops=[], reply=_needs_reply(items))

    new_items, notes = apply_ops(items, ops, account)
    return ShopTurn(ops=ops, reply=(", ".join(notes) + ". " if notes else "") + _needs_reply(new_items))


def _line_ref(text: str) -> str | None:
    m = re.search(r"\bline\s*([0-9]{1,2})\b", text.lower())
    if m:
        return f"L{m.group(1)}"
    m = re.search(r"\b(L[0-9]{1,2})\b", text, re.I)
    return m.group(1).upper() if m else None


def _needs_reply(items: list[dict]) -> str:
    """What the assistant should ask for next, based on the cart's gaps."""
    view = cart_view(items)
    for it in view["items"]:
        if not it.get("device"):
            return "Which device would you like? (e.g. iPhone 17 Pro, Pixel 10, Galaxy S26)"
        if not it.get("plan"):
            return f"Which plan for the {it['device']}? (Unlimited Welcome, Plus, or Ultimate)"
    if not view["items"]:
        return "What would you like to do — add a line or upgrade an existing one?"
    return f"Your cart is ${view['monthly_total']:.2f}/mo. Add anything else, or you're all set?"
