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

# Device protection (insurance) — ALWAYS offered when a device is added to the
# cart. Priced per month; `for` gates which device types each tier covers.
PROTECTION = [
    {"id": "protect-total", "name": "Total Mobile Protection", "monthly": 17.0,
     "for": ["phone"], "blurb": "Loss, theft, damage + same-day replacement & tech support"},
    {"id": "protect-tablet", "name": "Tablet Protection", "monthly": 11.0,
     "for": ["tablet"], "blurb": "Damage, malfunction & battery coverage"},
    {"id": "protect-watch", "name": "Wearable Protection", "monthly": 5.0,
     "for": ["watch"], "blurb": "Damage & malfunction coverage for watches"},
]

# Perks / add-ons — optional streaming & service subscriptions sold at the
# wireless "perk" price ($10/mo each) regardless of retail value.
PERK_PRICE = 10.0
PERKS = [
    {"id": "youtube-tv", "name": "YouTube TV", "monthly": PERK_PRICE, "blurb": "Live TV streaming"},
    {"id": "netflix", "name": "Netflix", "monthly": PERK_PRICE, "blurb": "Netflix Standard, ad-free"},
    {"id": "max", "name": "Max", "monthly": PERK_PRICE, "blurb": "HBO Max — ad-free movies & series"},
    {"id": "apple-one", "name": "Apple One", "monthly": PERK_PRICE, "blurb": "Apple Music, TV+, Arcade & iCloud+"},
    {"id": "disney-bundle", "name": "Disney+ Bundle", "monthly": PERK_PRICE, "blurb": "Disney+, Hulu & ESPN+"},
]

# Accessories — one-time-charge items (collected today and taxed).
ACCESSORIES = [
    {"id": "case", "name": "Protective Case", "price": 39.99, "blurb": "Drop-tested rugged case"},
    {"id": "screen-protector", "name": "Screen Protector", "price": 24.99, "blurb": "Tempered glass, installed in-store"},
    {"id": "fast-charger", "name": "Fast Charger", "price": 29.99, "blurb": "35W USB-C wall charger"},
    {"id": "earbuds", "name": "Wireless Earbuds", "price": 99.99, "blurb": "Noise-cancelling earbuds"},
]

# Fees & tax — one-time charges ALWAYS collected at checkout ("due today").
ACTIVATION_FEE = 35.0   # per new line / upgrade
TAX_RATE = 0.0825       # sales tax on device retail + accessories, collected upfront

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
    # Existing customer only: an estimate of what they pay today (plans + home
    # internet), so checkout can show current vs. new "View Together" totals.
    existing = account_id and (account_id or "").strip().upper() in _PROFILES
    return {
        "account_id": (account_id or "").strip().upper() or None,
        "name": acct.get("name", "Guest"),
        "tenure_months": acct.get("tenure_months"),
        "lines": profile["lines"],
        "home_internet": profile.get("home_internet"),
        "eligibility": elig,
        "current_monthly": current_monthly(profile) if existing else None,
        "primary_phone": profile["lines"][0]["phone"] if profile.get("lines") else None,
    }


def current_monthly(profile: dict) -> float:
    """Estimate an account's current recurring bill from its existing lines'
    plans + home internet (illustrative — device payments aren't tracked here)."""
    total = 0.0
    for ln in profile.get("lines", []):
        p = plan_by_name(ln.get("plan"))
        if p:
            total += p["price"]
    hi = profile.get("home_internet")
    if hi:
        prod = HOME_INTERNET.get(hi.get("product"))
        if prod:
            total += prod["price"]
    return round(total, 2)


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


# ---- Protection / perks / accessories lookups (device add-ons + one-times) ---- #
def protection_for_type(device_type: str | None) -> dict | None:
    """The default protection tier offered for a device type (phone/tablet/watch)."""
    if not device_type:
        return None
    return next((p for p in PROTECTION if device_type in p["for"]), None)


def find_protection(query: str | None) -> dict | None:
    if not query:
        return None
    q = query.lower()
    for p in PROTECTION:
        if p["name"].lower() in q or p["id"].replace("-", " ") in q:
            return p
    # Full words only — avoid matching "protective case" (an accessory).
    if "protection" in q or "insurance" in q or "coverage" in q or "warranty" in q:
        return PROTECTION[0]
    return None


def protection_by_name(name: str | None) -> dict | None:
    if not name:
        return None
    return next((p for p in PROTECTION if p["name"].lower() == name.lower()), None)


def find_perk(query: str | None) -> dict | None:
    if not query:
        return None
    q = query.lower()
    for pk in PERKS:
        if pk["name"].lower() in q or pk["id"].replace("-", " ") in q:
            return pk
    if "youtube" in q:
        return _perk("youtube-tv")
    if "hbo" in q:
        return _perk("max")
    if "disney" in q or "hulu" in q:
        return _perk("disney-bundle")
    if "apple" in q and ("one" in q or "music" in q):
        return _perk("apple-one")
    return None


def perk_by_name(name: str | None) -> dict | None:
    if not name:
        return None
    return next((pk for pk in PERKS if pk["name"].lower() == name.lower()), None)


def _perk(pid: str) -> dict | None:
    return next((pk for pk in PERKS if pk["id"] == pid), None)


def find_accessory(query: str | None) -> dict | None:
    if not query:
        return None
    q = query.lower()
    for a in ACCESSORIES:
        if a["name"].lower() in q or a["id"].replace("-", " ") in q:
            return a
    if "case" in q:
        return _acc("case")
    if "charger" in q:
        return _acc("fast-charger")
    if "screen" in q or "protector" in q:
        return _acc("screen-protector")
    if "earbud" in q or "buds" in q or "headphone" in q:
        return _acc("earbuds")
    return None


def accessory_by_name(name: str | None) -> dict | None:
    if not name:
        return None
    return next((a for a in ACCESSORIES if a["name"].lower() == name.lower()), None)


def _acc(aid: str) -> dict | None:
    return next((a for a in ACCESSORIES if a["id"] == aid), None)
