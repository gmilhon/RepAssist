"""Build an apples-to-apples *switch quote* from a scanned competitor bill.

Given a `CompetitorBill` (extracted by the vision pass in `llm.analyze_competitor_bill`)
plus any additional 3rd-party services the rep identifies (e.g. the customer pays
Netflix directly, or has home internet from another provider), this maps the
competitor's setup onto our catalog:

* match their plan tier to our nearest Unlimited plan, priced with realistic
  multi-line discounts (`shop_data`-derived);
* fold every streaming service — on the bill *and* paid 3rd-party — into a
  $10/mo perk;
* add home internet (fiber/FWA) when they have it;

then report the monthly / annual savings vs. what they pay today. Pure and
deterministic, so it runs identically online and offline.
"""
from __future__ import annotations

from typing import Any

from .mock_services import shop_data
from .schemas import CompetitorBill, CompetitorStreaming

# Effective per-line price for each plan at a given line count (autopay +
# multi-line discount), mirroring how carriers actually price multiple lines.
# The list PER_LINE[plan][min(n,5)-1] is the per-line price when there are n lines.
PER_LINE: dict[str, list[float]] = {
    "unlimited-welcome":  [65.0, 55.0, 40.0, 30.0, 27.0],
    "unlimited-plus":     [80.0, 65.0, 52.0, 45.0, 42.0],
    "unlimited-ultimate": [90.0, 75.0, 60.0, 52.0, 48.0],
}

# Keywords in the competitor plan name → our matched tier.
_ULTIMATE_HINTS = ("ultimate", "premium", "max", "elite", "beyond", "magenta max", "go5g plus", "plus unlimited")
_PLUS_HINTS = ("plus", "extra", "more", "advanced", "go5g", "protection")


def _match_plan(bill: CompetitorBill) -> dict[str, Any]:
    name = (bill.plan_name or "").lower()
    if any(h in name for h in _ULTIMATE_HINTS):
        plan_id = "unlimited-ultimate"
    elif any(h in name for h in _PLUS_HINTS):
        plan_id = "unlimited-plus"
    else:
        # Fall back on their per-line spend: pricey → premium tier.
        per_line_spend = (bill.wireless_monthly / bill.line_count) if bill.line_count else 0.0
        plan_id = "unlimited-ultimate" if per_line_spend >= 75 else "unlimited-plus" if per_line_spend >= 55 else "unlimited-welcome"
    plan = next(p for p in shop_data.PLANS if p["id"] == plan_id)
    return plan


def _per_line(plan_id: str, n: int) -> float:
    tiers = PER_LINE.get(plan_id, PER_LINE["unlimited-plus"])
    return tiers[min(max(n, 1), 5) - 1]


def _our_home_internet(their_price: float) -> dict[str, Any]:
    # Offer fiber when their spend supports it, else fixed wireless.
    prod = shop_data.HOME_INTERNET["fiber"] if their_price and their_price >= 60 else shop_data.HOME_INTERNET["fwa"]
    return {"product": prod["product"], "name": prod["name"], "monthly": prod["price"]}


def _merge_streaming(bill: CompetitorBill, extras: dict[str, Any]) -> list[dict[str, Any]]:
    """Streaming on the bill + any the rep flags as paid 3rd-party. Deduped by name."""
    out: dict[str, dict[str, Any]] = {}
    for s in bill.streaming:
        out[s.name.strip().lower()] = {"name": s.name, "monthly": round(float(s.monthly), 2), "source": "bill"}
    for s in extras.get("streaming", []) or []:
        name = str(s.get("name", "")).strip()
        if not name:
            continue
        out[name.lower()] = {"name": name, "monthly": round(float(s.get("monthly", 0.0)), 2), "source": "third_party"}
    return list(out.values())


def build_switch_quote(bill: CompetitorBill, extras: dict[str, Any] | None = None) -> dict[str, Any]:
    extras = extras or {}
    n = max(int(bill.line_count or 0), 0)
    plan = _match_plan(bill)
    per_line = _per_line(plan["id"], n) if n else plan["price"]
    lines_monthly = round(per_line * n, 2)

    # Perks: one $10 perk replaces each streaming service (on-bill + 3rd-party).
    streaming = _merge_streaming(bill, extras)
    perks = [
        {
            "name": s["name"],
            "monthly": shop_data.PERK_PRICE,
            "third_party_monthly": s["monthly"],
            "saves": round(s["monthly"] - shop_data.PERK_PRICE, 2),
            "source": s["source"],
        }
        for s in streaming
    ]
    perks_monthly = round(shop_data.PERK_PRICE * len(perks), 2)

    # Home internet: from the bill, or flagged as an extra the rep enters.
    their_home = None
    if bill.home_internet:
        their_home = {"name": bill.home_internet.name, "monthly": round(float(bill.home_internet.monthly), 2)}
    elif extras.get("home_internet"):
        hi = extras["home_internet"]
        their_home = {"name": str(hi.get("name", "Home internet")), "monthly": round(float(hi.get("monthly", 0.0)), 2)}
    home = None
    if their_home:
        ours = _our_home_internet(their_home["monthly"])
        home = {**ours, "their_name": their_home["name"], "their_monthly": their_home["monthly"],
                "saves": round(their_home["monthly"] - ours["monthly"], 2)}

    # What they pay today = the bill total + any 3rd-party spend not already on it.
    extra_third_party = sum(p["third_party_monthly"] for p in perks if p["source"] == "third_party")
    if not bill.home_internet and extras.get("home_internet"):
        extra_third_party += float(extras["home_internet"].get("monthly", 0.0))
    their_total = round(float(bill.total_monthly) + extra_third_party, 2)

    our_total = round(lines_monthly + perks_monthly + (home["monthly"] if home else 0.0), 2)
    monthly_savings = round(their_total - our_total, 2)
    annual_savings = round(monthly_savings * 12, 2)

    # Display line-items for our matched quote.
    line_items: list[dict[str, Any]] = [{
        "label": f"{plan['name']} — {n} line{'s' if n != 1 else ''}",
        "sub": f"${per_line:.0f}/line", "amount": lines_monthly, "kind": "lines",
    }]
    for p in perks:
        line_items.append({"label": f"{p['name']} perk", "sub": f"vs ${p['third_party_monthly']:.2f} today",
                           "amount": p["monthly"], "kind": "perk"})
    if home:
        line_items.append({"label": home["name"], "sub": f"vs {home['their_name']} ${home['their_monthly']:.0f}",
                           "amount": home["monthly"], "kind": "home_internet"})

    return {
        "our_plan": {"id": plan["id"], "name": plan["name"], "per_line": per_line, "line_count": n, "lines_monthly": lines_monthly},
        "perks": perks,
        "home_internet": home,
        "line_items": line_items,
        "our_total_monthly": our_total,
        "their_total_monthly": their_total,
        "monthly_savings": monthly_savings,
        "annual_savings": annual_savings,
        "summary": _summary(plan, n, perks, home, monthly_savings, annual_savings),
    }


def _summary(plan, n, perks, home, monthly_savings, annual_savings) -> str:
    parts = [f"{n} line{'s' if n != 1 else ''} on {plan['name']}"]
    if perks:
        parts.append(f"{len(perks)} streaming perk{'s' if len(perks) != 1 else ''}")
    if home:
        parts.append(home["name"])
    bundle = ", ".join(parts)
    if monthly_savings > 0:
        return f"Switching to {bundle} saves about ${monthly_savings:,.2f}/mo (~${annual_savings:,.0f}/yr) vs. their bill today."
    if monthly_savings == 0:
        return f"{bundle} matches what they pay today — but with our perks and network."
    return f"{bundle} runs about ${abs(monthly_savings):,.2f}/mo more, but adds our perks, trade-in credit and network."


# --------------------------------------------------------------------------- #
# Barcode (UPC) product lookup — small demo map over the catalog.
# --------------------------------------------------------------------------- #
UPC_MAP: dict[str, str] = {
    "194253000000": "iphone-17-pro",
    "194253000017": "iphone-17",
    "842776000101": "pixel-10",
    "887276000260": "galaxy-s26",
    "194253000599": "ipad-air",
    "887276000101": "galaxy-tab-s10",
    "194253000399": "apple-watch-10",
    "887276000070": "galaxy-watch-7",
    "840000000390": "case",
    "840000000240": "screen-protector",
    "840000000290": "fast-charger",
    "840000000990": "earbuds",
}


def product_for_upc(upc: str) -> dict[str, Any] | None:
    """Resolve a scanned UPC to a catalog device or accessory."""
    digits = "".join(ch for ch in (upc or "") if ch.isdigit())
    pid = UPC_MAP.get(digits)
    if not pid:
        return None
    for d in shop_data.DEVICES:
        if d["id"] == pid:
            return {"kind": "device", "id": d["id"], "name": d["name"], "brand": d.get("brand"),
                    "price": d["price"], "monthly": shop_data.device_monthly(d["price"]), "upc": digits}
    for a in shop_data.ACCESSORIES:
        if a["id"] == pid:
            return {"kind": "accessory", "id": a["id"], "name": a["name"], "brand": None,
                    "price": a["price"], "monthly": None, "blurb": a.get("blurb"), "upc": digits}
    return None
