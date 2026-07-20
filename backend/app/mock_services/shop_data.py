"""Shopping catalog + enriched account profiles for the in-chat shopping
experience (add a line / upgrade a device). Vendor-neutral product names by
project convention. Deterministic so demos are repeatable.

The base account records live in `data.py` (name, headline plan, line count,
tenure) and drive the resolver scenarios; this module adds the richer per-line
device/plan detail + home-internet product the shopping flow and the account
summary need, keyed by the same account ids.
"""
from __future__ import annotations

from .data import ACCOUNTS, resolve_eligibility

# --------------------------------------------------------------------------- #
# Catalog
# --------------------------------------------------------------------------- #
# Devices — retail price + a 36-month device-payment estimate. `type` gates
# which plans a line can take (a watch can't take an Unlimited phone plan).
DEVICES = [
    {"id": "iphone-17-pro", "name": "iPhone 17 Pro", "type": "phone", "brand": "Apple", "price": 1099.0},
    {"id": "iphone-17", "name": "iPhone 17", "type": "phone", "brand": "Apple", "price": 799.0},
    {"id": "pixel-10", "name": "Pixel 10", "type": "phone", "brand": "Google", "price": 799.0},
    {"id": "galaxy-s26", "name": "Galaxy S26", "type": "phone", "brand": "Samsung", "price": 899.0},
    {"id": "ipad-air", "name": "iPad Air", "type": "tablet", "brand": "Apple", "price": 599.0},
    {"id": "galaxy-tab-s10", "name": "Galaxy Tab S10", "type": "tablet", "brand": "Samsung", "price": 499.0},
    {"id": "apple-watch-10", "name": "Apple Watch Series 10", "type": "watch", "brand": "Apple", "price": 399.0},
    {"id": "galaxy-watch-7", "name": "Galaxy Watch 7", "type": "watch", "brand": "Samsung", "price": 299.0},
]

# Plans — monthly price + which device types they apply to.
PLANS = [
    {"id": "unlimited-welcome", "name": "Unlimited Welcome", "price": 65.0, "for": ["phone"]},
    {"id": "unlimited-plus", "name": "Unlimited Plus", "price": 80.0, "for": ["phone"]},
    {"id": "unlimited-ultimate", "name": "Unlimited Ultimate", "price": 90.0, "for": ["phone"]},
    {"id": "number-share", "name": "Number Share", "price": 15.0, "for": ["watch"]},
    {"id": "tablet-data", "name": "Tablet Data", "price": 20.0, "for": ["tablet"]},
]

# Promotions — `line_discount` reduces the plan's monthly; `trade_in` /
# `upgrade_fee` reduce the device/upfront cost. Mirrors the eligibility labels
# in data.py so an account's upgrade_promo maps to a real promo here.
PROMOS = [
    {"id": "trade-200", "label": "$200 off a new phone with eligible trade-in", "kind": "trade_in", "device_credit": 200.0},
    {"id": "early-upgrade", "label": "Early upgrade — device payment 50% paid off", "kind": "upgrade_fee", "device_credit": 0.0},
    {"id": "loyalty-upgrade", "label": "Loyalty upgrade — waived upgrade fee", "kind": "upgrade_fee", "device_credit": 0.0},
    {"id": "new-line-10", "label": "New line — $10/mo off for 12 months", "kind": "line_discount", "monthly_off": 10.0},
]

HOME_INTERNET = {
    "fiber": {"product": "fiber", "name": "Fiber Home Internet", "price": 55.0},
    "fwa": {"product": "fwa", "name": "Fixed Wireless Internet", "price": 50.0},
}

TERM_MONTHS = 36  # device-payment term used for the monthly estimate


def device_monthly(price: float) -> float:
    return round(price / TERM_MONTHS, 2)


# --------------------------------------------------------------------------- #
# Enriched account profiles — the customer's current lines + home internet.
# --------------------------------------------------------------------------- #
_PROFILES: dict[str, dict] = {
    "AC-3001": {
        "lines": [
            {"line_id": "L1", "phone": "(555) 010-3011", "device": "iPhone 15 Pro", "device_type": "phone", "plan": "Unlimited Plus", "upgrade_eligible": True},
        ],
        "home_internet": None,
    },
    "AC-3002": {
        "lines": [
            {"line_id": "L1", "phone": "(555) 010-3021", "device": "Pixel 8", "device_type": "phone", "plan": "Unlimited Welcome", "upgrade_eligible": True},
        ],
        "home_internet": None,
    },
    "AC-3003": {
        "lines": [
            {"line_id": "L1", "phone": "(555) 010-3031", "device": "iPhone 15 Pro", "device_type": "phone", "plan": "Unlimited Ultimate", "upgrade_eligible": True},
            {"line_id": "L2", "phone": "(555) 010-3032", "device": "iPhone 14", "device_type": "phone", "plan": "Unlimited Ultimate", "upgrade_eligible": False},
            {"line_id": "L3", "phone": "(555) 010-3033", "device": "Apple Watch Series 8", "device_type": "watch", "plan": "Number Share", "upgrade_eligible": True},
        ],
        "home_internet": {"product": "fwa", "name": "Fixed Wireless Internet", "plan": "Fixed Wireless Internet"},
    },
    "AC-3004": {
        "lines": [
            {"line_id": "L1", "phone": "(555) 010-3041", "device": "iPhone 16", "device_type": "phone", "plan": "Unlimited Welcome", "upgrade_eligible": False},
        ],
        "home_internet": None,
    },
    "AC-5001": {
        "lines": [
            {"line_id": "L1", "phone": "(555) 010-5011", "device": "Galaxy S24", "device_type": "phone", "plan": "Unlimited Plus", "upgrade_eligible": True},
            {"line_id": "L2", "phone": "(555) 010-5012", "device": "iPad (10th gen)", "device_type": "tablet", "plan": "Tablet Data", "upgrade_eligible": True},
        ],
        "home_internet": None,
    },
    "AC-5002": {
        "lines": [
            {"line_id": "L1", "phone": "(555) 010-5021", "device": "iPhone 15", "device_type": "phone", "plan": "Unlimited Ultimate", "upgrade_eligible": True},
            {"line_id": "L2", "phone": "(555) 010-5022", "device": "iPhone 15", "device_type": "phone", "plan": "Unlimited Ultimate", "upgrade_eligible": True},
            {"line_id": "L3", "phone": "(555) 010-5023", "device": "Galaxy Watch 6", "device_type": "watch", "plan": "Number Share", "upgrade_eligible": False},
            {"line_id": "L4", "phone": "(555) 010-5024", "device": "iPad Air", "device_type": "tablet", "plan": "Tablet Data", "upgrade_eligible": True},
        ],
        "home_internet": {"product": "fiber", "name": "Fiber Home Internet", "plan": "Fiber Home Internet"},
    },
    "AC-5003": {
        "lines": [
            {"line_id": "L1", "phone": "(555) 010-5031", "device": "iPhone 14", "device_type": "phone", "plan": "Unlimited Welcome", "upgrade_eligible": True},
        ],
        "home_internet": None,
    },
}

_DEFAULT_PROFILE = {
    "lines": [
        {"line_id": "L1", "phone": "(555) 010-0001", "device": "iPhone 15", "device_type": "phone", "plan": "Unlimited Plus", "upgrade_eligible": True},
    ],
    "home_internet": None,
}


def account_summary(account_id: str | None) -> dict:
    """Full, rep-facing account snapshot: name, plan headline, current lines
    (device + type + plan), home internet, and the sales opportunities to
    position. Returns a sensible default for an unknown/anonymous account so the
    shopping flow always has something to show."""
    acct = ACCOUNTS.get((account_id or "").strip().upper(), {}) if account_id else {}
    profile = _PROFILES.get((account_id or "").strip().upper(), _DEFAULT_PROFILE)
    elig = resolve_eligibility(account_id)
    return {
        "account_id": (account_id or "").strip().upper() or None,
        "name": acct.get("name", "Guest"),
        "tenure_months": acct.get("tenure_months"),
        "lines": profile["lines"],
        "home_internet": profile.get("home_internet"),
        "eligibility": elig,
    }


# --------------------------------------------------------------------------- #
# Catalog lookup helpers (used by the shop node + its offline fallback)
# --------------------------------------------------------------------------- #
def find_device(query: str | None) -> dict | None:
    """Best-effort match a device by (fuzzy) name from free text."""
    if not query:
        return None
    q = query.lower()
    for d in DEVICES:
        if d["name"].lower() in q or d["id"].replace("-", " ") in q:
            return d
    # token overlap fallback (e.g. "pixel", "galaxy watch")
    best, score = None, 0
    for d in DEVICES:
        toks = set(d["name"].lower().split())
        overlap = len(toks & set(q.split()))
        if overlap > score:
            best, score = d, overlap
    return best if score else None


def find_plan(query: str | None, device_type: str = "phone") -> dict | None:
    if not query:
        return None
    q = query.lower()
    for p in PLANS:
        if p["name"].lower() in q:
            return p
    # keyword shortcuts
    if "ultimate" in q:
        return _plan("unlimited-ultimate")
    if "plus" in q:
        return _plan("unlimited-plus")
    if "welcome" in q:
        return _plan("unlimited-welcome")
    return None


def default_plan_for_type(device_type: str) -> dict:
    for p in PLANS:
        if device_type in p["for"]:
            return p
    return PLANS[0]


def _plan(plan_id: str) -> dict | None:
    return next((p for p in PLANS if p["id"] == plan_id), None)


def plan_by_name(name: str | None) -> dict | None:
    if not name:
        return None
    return next((p for p in PLANS if p["name"].lower() == name.lower()), None)


def find_promo(query: str | None) -> dict | None:
    if not query:
        return None
    q = query.lower()
    for pr in PROMOS:
        if pr["label"].lower() in q or pr["id"].replace("-", " ") in q:
            return pr
    if "trade" in q:
        return next((pr for pr in PROMOS if pr["kind"] == "trade_in"), None)
    return None


def promo_by_label(label: str | None) -> dict | None:
    if not label:
        return None
    return next((pr for pr in PROMOS if pr["label"].lower() == label.lower()), None)
