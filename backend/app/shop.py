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
from datetime import datetime, timezone

from .mock_services import shop_data as cat
from .schemas import CartOp, ShopTurn

_DEVICE_KINDS = ("new_line", "upgrade")


def _item_id() -> str:
    return "it-" + uuid.uuid4().hex[:6]


# --------------------------------------------------------------------------- #
# Costing
# --------------------------------------------------------------------------- #
def _recost(item: dict) -> dict:
    """Recompute an item's monthly/onetime + human summary. Device lines finance
    the device over the term (a trade-in promo credits it), add the plan (a
    line-discount promo reduces it) and any device-protection add-on. Perks are
    a flat monthly; accessories are a one-time charge."""
    kind = item.get("kind")

    if kind == "perk":
        item["monthly"] = round(float(item.get("monthly", 0.0)), 2)
        item["onetime"] = 0.0
        item["summary"] = f"Perk · {item.get('name', 'Perk')}"
        return item
    if kind == "accessory":
        item["monthly"] = 0.0
        item["onetime"] = round(float(item.get("onetime", 0.0)), 2)
        item["summary"] = f"Accessory · {item.get('name', 'Accessory')}"
        return item

    device = cat.find_device(item.get("device")) if item.get("device") else None
    plan = cat.plan_by_name(item.get("plan")) if item.get("plan") else None
    promo = cat.promo_by_label(item.get("promo")) if item.get("promo") else None

    device_credit = promo.get("device_credit", 0.0) if promo and promo["kind"] == "trade_in" else 0.0
    monthly_off = promo.get("monthly_off", 0.0) if promo and promo["kind"] == "line_discount" else 0.0

    device_monthly = cat.device_monthly(max(0.0, (device["price"] if device else 0.0) - device_credit))
    plan_monthly = max(0.0, (plan["price"] if plan else 0.0) - monthly_off)
    protection_monthly = float((item.get("protection") or {}).get("monthly", 0.0))
    item["monthly"] = round(device_monthly + plan_monthly + protection_monthly, 2)
    item["onetime"] = 0.0

    kind_label = {"new_line": "New line", "upgrade": "Upgrade", "home_internet": "Home internet"}.get(kind, kind)
    if kind == "upgrade" and item.get("line_id"):
        kind_label = f"Upgrade {item['line_id']}"
    parts = [kind_label, item.get("device") or "device TBD", item.get("plan") or "plan TBD"]
    if item.get("promo"):
        parts.append(f"promo: {item['promo']}")
    if item.get("protection"):
        parts.append(f"+ {item['protection']['name']}")
    item["summary"] = " · ".join(parts)
    return item


def cart_view(items: list[dict]) -> dict:
    items = [_recost(dict(it)) for it in items]
    return {
        "items": items,
        "monthly_total": round(sum(it["monthly"] for it in items), 2),
        "onetime_total": round(sum(it["onetime"] for it in items), 2),
        "recommendations": _recommendations(items),
    }


def _recommendations(items: list[dict]) -> list[dict]:
    """Deterministic attach recommendations. ALWAYS recommend device protection
    for a device line that has none (and wasn't declined); suggest a perk once if
    the cart has no perks yet."""
    recs: list[dict] = []
    for it in items:
        if it.get("kind") in _DEVICE_KINDS and it.get("device") \
                and not it.get("protection") and not it.get("protection_declined"):
            dev = it["device"]
            recs.append({
                "kind": "protection", "target": dev,
                "label": f"Protect the {dev}",
                "detail": "Recommended — loss, theft & damage coverage",
                "prompt": f"Add device protection to the {dev}.",
            })
    if items and not any(it.get("kind") == "perk" for it in items):
        recs.append({
            "kind": "perk", "target": None,
            "label": "Add a perk",
            "detail": "Netflix, YouTube TV, Max, Apple One & more — $10/mo each",
            "prompt": "What perks can I add — like Netflix or YouTube TV?",
        })
    return recs


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


def checkout_quote(items: list[dict], account: dict) -> dict:
    """The 'View Together' bill math: current vs. new recurring vs. blended
    monthly, plus the one-time charges collected today (always taxes + an
    activation fee per new/upgraded line, plus any accessories). Illustrative —
    nothing is charged."""
    view = cart_view(items)
    line_items = view["items"]
    device_lines = [it for it in line_items if it.get("kind") in _DEVICE_KINDS]

    recurring_monthly = view["monthly_total"]
    current = account.get("current_monthly")
    current_monthly = round(current, 2) if current is not None else None
    blended_monthly = round((current or 0.0) + recurring_monthly, 2)

    activation_fees = round(cat.ACTIVATION_FEE * len(device_lines), 2)
    accessories_onetime = round(sum(it.get("onetime", 0.0) for it in line_items if it.get("kind") == "accessory"), 2)
    device_retail = 0.0
    for it in device_lines:
        d = cat.find_device(it.get("device")) if it.get("device") else None
        if d:
            device_retail += d["price"]
    taxes = round(cat.TAX_RATE * (device_retail + accessories_onetime), 2)
    due_today = round(activation_fees + accessories_onetime + taxes, 2)

    recurring_lines = []
    for it in device_lines:
        sub = it.get("plan") or "Plan TBD"
        if it.get("protection"):
            sub += f" · {it['protection']['name']}"
        recurring_lines.append({"label": it.get("device") or "Device", "sub": sub, "amount": it["monthly"]})
    for it in line_items:
        if it.get("kind") == "perk":
            recurring_lines.append({"label": it.get("name", "Perk"), "sub": "Perk", "amount": it["monthly"]})

    onetime_lines = []
    if activation_fees:
        n = len(device_lines)
        onetime_lines.append({"label": f"Activation fee (${cat.ACTIVATION_FEE:.0f} × {n})", "amount": activation_fees})
    for it in line_items:
        if it.get("kind") == "accessory":
            onetime_lines.append({"label": it.get("name", "Accessory"), "amount": it["onetime"]})
    if taxes:
        onetime_lines.append({"label": "Taxes & surcharges", "amount": taxes})

    return {
        "current_monthly": current_monthly,
        "recurring_monthly": recurring_monthly,
        "blended_monthly": blended_monthly,
        "next_month_total": blended_monthly,
        "activation_fees": activation_fees,
        "accessories_onetime": accessories_onetime,
        "taxes": taxes,
        "device_retail": round(device_retail, 2),
        "due_today": due_today,
        "recurring_lines": recurring_lines,
        "onetime_lines": onetime_lines,
        "items": line_items,
    }


def place_order(items: list[dict], account: dict, thread_id: str | None = None,
                rep_id: str | None = None, quote: dict | None = None,
                fulfillment: str | None = None, signature_ref: str | None = None,
                receipt_channel: str | None = None) -> dict:
    """Record the order and SIMULATE taking payment. Returns the full confirmation
    (order id, items, recurring + one-time breakdown, perks, masked card). No real
    payment is ever processed."""
    from .store import db
    view = cart_view(items)
    q = quote or checkout_quote(items, account)
    perks = [{"name": it.get("name"), "monthly": it.get("monthly")}
             for it in view["items"] if it.get("kind") == "perk"]
    onetime_breakdown = {
        "activation_fees": q["activation_fees"],
        "accessories": q["accessories_onetime"],
        "taxes": q["taxes"],
    }
    order = db.create_shop_order(
        thread_id=thread_id, rep_id=rep_id, account_id=account.get("account_id"),
        items=view["items"], monthly_total=view["monthly_total"],
        onetime_total=q["due_today"], payment_method=_MOCK_CARD,
        taxes=q["taxes"], activation_fees=q["activation_fees"],
        onetime_breakdown=onetime_breakdown, perks=perks,
        fulfillment=fulfillment or "pickup",
        signed_at=datetime.now(timezone.utc) if signature_ref else None,
        signature_ref=signature_ref, receipt_channel=receipt_channel,
    )
    return {
        "order_id": order.id,
        "items": view["items"],
        "monthly_total": view["monthly_total"],
        "onetime_total": q["due_today"],
        "payment_method": _MOCK_CARD,
        "current_monthly": q["current_monthly"],
        "recurring_monthly": q["recurring_monthly"],
        "blended_monthly": q["blended_monthly"],
        "taxes": q["taxes"],
        "activation_fees": q["activation_fees"],
        "accessories_onetime": q["accessories_onetime"],
        "due_today": q["due_today"],
        "onetime_lines": q["onetime_lines"],
        "perks": perks,
        "fulfillment": fulfillment or "pickup",
        "signature_ref": signature_ref,
        "receipt_channel": receipt_channel,
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
            if op.trade_in_device:
                _apply_trade_in(item, account, op.trade_in_device)
                notes.append(f"Trade-in {op.trade_in_device}")

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
            if op.trade_in_device:
                _apply_trade_in(item, account, op.trade_in_device)
                notes.append(f"Trade-in {op.trade_in_device}")

        elif kind == "add_protection":
            it = _last_device_item(items, op.target)
            if it:
                prot = (cat.protection_by_name(op.protection) or cat.find_protection(op.protection)
                        or cat.protection_for_type(it.get("device_type")))
                if prot:
                    it["protection"] = {"name": prot["name"], "monthly": prot["monthly"], "blurb": prot.get("blurb", "")}
                    it.pop("protection_declined", None)
                    _recost(it)
                    notes.append(f"Added {prot['name']} to {it.get('device')}")

        elif kind == "decline_protection":
            it = _last_device_item(items, op.target)
            if it:
                it["protection"] = None
                it["protection_declined"] = True
                _recost(it)
                notes.append(f"Skipped protection on {it.get('device')}")

        elif kind == "add_perk":
            perk = cat.perk_by_name(op.perk) or cat.find_perk(op.perk) or cat.find_perk(op.plan)
            if perk and not any(x.get("kind") == "perk" and x.get("name") == perk["name"] for x in items):
                items.append(_recost({
                    "item_id": _item_id(), "kind": "perk", "name": perk["name"],
                    "blurb": perk.get("blurb", ""), "monthly": perk["monthly"], "onetime": 0.0, "device": None,
                }))
                notes.append(f"Added perk: {perk['name']}")

        elif kind == "remove_perk":
            perk = cat.perk_by_name(op.perk) or cat.find_perk(op.perk)
            if perk:
                before = len(items)
                items = [x for x in items if not (x.get("kind") == "perk" and x.get("name") == perk["name"])]
                if len(items) < before:
                    notes.append(f"Removed perk: {perk['name']}")

        elif kind == "add_accessory":
            acc = cat.accessory_by_name(op.accessory) or cat.find_accessory(op.accessory)
            if acc:
                items.append(_recost({
                    "item_id": _item_id(), "kind": "accessory", "name": acc["name"],
                    "blurb": acc.get("blurb", ""), "monthly": 0.0, "onetime": acc["price"], "device": None,
                }))
                notes.append(f"Added accessory: {acc['name']}")

        elif kind == "set_fulfillment" and op.fulfillment in ("pickup", "ship"):
            it = _last_device_item(items, op.target)
            if it:
                it["fulfillment"] = op.fulfillment
                notes.append(f"{it.get('device')} — {'ship to home' if op.fulfillment == 'ship' else 'in-store pickup'}")

        elif kind == "set_trade_in" and op.trade_in_device:
            it = _last_device_item(items, op.target)
            if it:
                credit = _apply_trade_in(it, account, op.trade_in_device)
                notes.append(f"Trade-in {op.trade_in_device} — ${credit:.0f} credit")

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


def _last_device_item(items: list[dict], target: str | None = None) -> dict | None:
    """Resolve the device line an add-on targets (protection/fulfillment/trade-in):
    the explicit target if it's a device line, else the most recent device line."""
    if target:
        it = _target_item(items, target)
        if it and it.get("kind") in _DEVICE_KINDS:
            return it
    return next((it for it in reversed(items)
                 if it.get("kind") in _DEVICE_KINDS and it.get("device")), None)


def _apply_trade_in(item: dict, account: dict, trade_in_device: str) -> float:
    """Attach a trade-in to a device line: record the old device + credit for
    display and apply the trade-in promo so the credit flows into financing."""
    promo = cat.promo_by_label(_auto_upgrade_promo(account) or "")
    if not promo or promo.get("kind") != "trade_in":
        promo = next((p for p in cat.PROMOS if p["kind"] == "trade_in"), None)
    credit = promo.get("device_credit", 0.0) if promo else 0.0
    item["trade_in"] = {"device": trade_in_device, "credit": credit}
    if promo:
        item["promo"] = promo["label"]
    _recost(item)
    return credit


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
    promo/protection/perk/accessory names + shopping verbs from the rep's text.
    Add-ons (protection/perk/accessory/fulfillment/trade-in) compose with a
    primary device action in the same turn."""
    t = text.lower()
    device = cat.find_device(text)
    plan = cat.find_plan(text)
    promo = cat.find_promo(text)
    perk = cat.find_perk(text)
    accessory = cat.find_accessory(text)
    protection = cat.find_protection(text)
    line_id = _line_ref(text)
    trade_ref = _trade_in_ref(text)

    is_clear = any(k in t for k in _CLEAR)
    is_remove = any(k in t for k in _REMOVE)
    # Full protection words only (avoids "protective case", an accessory).
    wants_protection = protection is not None or any(k in t for k in ("protection", "insurance", "coverage", "warranty"))
    declines_protection = wants_protection and any(k in t for k in ("no ", "not ", "skip", "decline", "don't", "dont", "without", "waive"))
    has_addon = wants_protection or bool(perk) or bool(accessory) or trade_ref is not None \
        or any(k in t for k in ("ship it", "ship to", "deliver", "mail it", "pick it up", "pickup", "pick up", "in store", "in-store"))

    ops: list[CartOp] = []
    primary_add = None  # the add_line/upgrade op, if one is created this turn

    # ---- Primary device action ---- #
    if is_clear:
        ops.append(CartOp(op="clear"))
    elif is_remove and not perk and not accessory:
        ops.append(CartOp(op="remove_item", target=device["name"] if device else None))
    elif any(k in t for k in _EDIT) and (device or plan or promo) and items:
        if device:
            ops.append(CartOp(op="set_device", device=device["name"]))
        if plan:
            ops.append(CartOp(op="set_plan", plan=plan["name"]))
        if promo:
            ops.append(CartOp(op="apply_promo", promo=promo["label"]))
    elif any(k in t for k in _UP) or line_id:
        primary_add = CartOp(op="upgrade", device=device["name"] if device else None,
                             plan=plan["name"] if plan else None, line_id=line_id,
                             promo=promo["label"] if promo else None, trade_in_device=trade_ref)
        ops.append(primary_add)
    elif any(k in t for k in _ADD):
        primary_add = CartOp(op="add_line", device=device["name"] if device else None,
                             plan=plan["name"] if plan else None,
                             promo=promo["label"] if promo else None)
        ops.append(primary_add)
    elif not has_addon and (device or plan or promo):
        # Bare device/plan/promo with no verb — treat as edits to the last item.
        if device:
            ops.append(CartOp(op="set_device", device=device["name"]))
        if plan:
            ops.append(CartOp(op="set_plan", plan=plan["name"]))
        if promo:
            ops.append(CartOp(op="apply_promo", promo=promo["label"]))

    # ---- Add-ons (compose with the primary above) ---- #
    if not is_clear and wants_protection:
        if declines_protection:
            ops.append(CartOp(op="decline_protection", target=device["name"] if device else None))
        else:
            ops.append(CartOp(op="add_protection", protection=(protection or {}).get("name"),
                              target=device["name"] if device else None))
    if perk:
        ops.append(CartOp(op="remove_perk" if is_remove else "add_perk", perk=perk["name"]))
    if accessory and not is_remove:
        ops.append(CartOp(op="add_accessory", accessory=accessory["name"]))
    if any(k in t for k in ("ship it", "ship to", "deliver", "mail it")):
        ops.append(CartOp(op="set_fulfillment", fulfillment="ship", target=device["name"] if device else None))
    elif any(k in t for k in ("pick it up", "pickup", "pick up", "in store", "in-store")):
        ops.append(CartOp(op="set_fulfillment", fulfillment="pickup", target=device["name"] if device else None))
    if trade_ref and primary_add is None and not is_clear:
        ops.append(CartOp(op="set_trade_in", trade_in_device=trade_ref))

    if not ops:
        return ShopTurn(ops=[], reply=_needs_reply(items))

    new_items, notes = apply_ops(items, ops, account)
    return ShopTurn(ops=ops, reply=(", ".join(notes) + ". " if notes else "") + _needs_reply(new_items))


def _trade_in_ref(text: str) -> str | None:
    """Best-effort: the old device named in a 'trade in my old <device>' phrase."""
    m = re.search(
        r"trad(?:e|ing)[\s-]?in\s+(?:my\s+|the\s+|our\s+|an?\s+)?(?:old\s+|current\s+)?([\w][\w\s]*?)"
        r"(?:\s+for\b|\s+on\b|\s+and\b|[.,!?]|$)", text, re.I)
    if m:
        phrase = m.group(1).strip()
        if phrase and 2 <= len(phrase) <= 30:
            return phrase
    if "trade in" in text.lower() or "trade-in" in text.lower() or "trading in" in text.lower():
        return "current phone"
    return None


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
