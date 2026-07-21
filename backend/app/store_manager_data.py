"""Store Manager daily-brief data.

Builds a coherent, hour-aware snapshot of one retail store's day — staffing,
traffic forecast, sales performance, and operations — for the Store Manager
dashboard. Everything here is synthetic mock data (there is no real WFM / HR /
inventory system behind this prototype), but it is *internally consistent*:
staffing states, break timing and the traffic-vs-coverage gaps are all derived
from a single "effective" store-local clock, so the view reads like a live
store at whatever time it is loaded.

Swap individual sections for real integrations later (WFM for `staffing`, the
POS/vol forecaster for `traffic`, the sales datamart for `sales`, and the
inventory/RMA systems for `operations`) without changing the API contract.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# The demo store. In a real deployment these come from the signed-in manager's
# assigned location; here they anchor the rankings and labels.
STORE = {
    "id": "R-4821",
    "name": "Riverside Commons",
    "market": "Greater Metro",
    "district": "District 7",
    "territory": "North Territory",
    "open_hour": 10,   # 10:00 AM
    "close_hour": 20,  # 8:00 PM
    "timezone": "America/New_York",
}

# --------------------------------------------------------------------------- #
# Effective store clock
# --------------------------------------------------------------------------- #
def _effective_now() -> datetime:
    """Store-local 'now', wrapped into business hours so the demo always reads
    as a live mid-shift store.

    The container may run in UTC (Cloud Run) or any local zone; converting to
    the store's timezone keeps hour-of-day labels sensible. When the real local
    time is before open or after close, we wrap to a lively mid-afternoon so the
    dashboard is never showing an empty/closed store during a demo.
    """
    now = datetime.now(timezone.utc).astimezone(ZoneInfo(STORE["timezone"]))
    if not (STORE["open_hour"] <= now.hour < STORE["close_hour"]):
        now = now.replace(hour=13, minute=24, second=0, microsecond=0)
    return now


def _eff_decimal(now: datetime) -> float:
    """Effective time as a decimal hour, e.g. 13:24 -> 13.4."""
    return now.hour + now.minute / 60.0


def _fmt_hour(h: int) -> str:
    """24h int -> '10a' / '12p' / '7p'."""
    suffix = "a" if h < 12 else "p"
    hr = h % 12 or 12
    return f"{hr}{suffix}"


def _fmt_clock(dec: float) -> str:
    """Decimal hour -> '1:30 PM'."""
    h = int(dec) % 24
    m = int(round((dec - int(dec)) * 60))
    if m == 60:
        h, m = h + 1, 0
    ap = "AM" if h < 12 else "PM"
    hr = h % 12 or 12
    return f"{hr}:{m:02d} {ap}"


# --------------------------------------------------------------------------- #
# Staffing
# --------------------------------------------------------------------------- #
# One row per team member on today's schedule. Hours are store-local decimals.
# `lunch` is the scheduled meal start (30 min); None for short shifts (a paid
# 15-min break is modeled instead). Break/lunch timing plus the effective clock
# drive each person's live state — nothing here is hardcoded to a single hour.
_ROSTER = [
    # Marcus opens early on a truck day (inbound shipment lands by 3 PM), so by
    # early afternoon he is the one overdue for a meal.
    {"name": "Marcus Bell",   "role": "Assistant Manager",   "start": 8,  "end": 16, "lunch": 13.75, "specialty": "Ops · Keyholder"},
    {"name": "Grace Kim",     "role": "Service Expert",      "start": 10, "end": 16, "lunch": None, "specialty": "Returns · Repairs"},
    {"name": "Devon Clark",   "role": "Sales Consultant",    "start": 10, "end": 18, "lunch": 12.75, "specialty": "Home Internet"},
    {"name": "Priya Nair",    "role": "Sales Lead",          "start": 10, "end": 18, "lunch": 13.5, "specialty": "Business · Coaching"},
    {"name": "Sofia Reyes",   "role": "Sales Consultant",    "start": 11, "end": 18, "lunch": 14.0, "specialty": "Upgrades"},
    {"name": "Tariq Hassan",  "role": "Sales Consultant",    "start": 12, "end": 20, "lunch": 13.25, "specialty": "Accessories · Perks"},
    {"name": "Emma Lin",      "role": "Sales Consultant",    "start": 12, "end": 20, "lunch": 15.5, "specialty": "New Activations"},
    {"name": "Jalen Wright",  "role": "Solutions Specialist","start": 12, "end": 20, "lunch": 15.75, "specialty": "Trade-in · Financing"},
    {"name": "Noah Bennett",  "role": "Sales Consultant",    "start": 14, "end": 20, "lunch": None, "specialty": "Closer · Wireless"},
]

_BREAK_LEN = 0.5      # 30-min meal
_SHORT_BREAK = 0.25   # 15-min paid break (short shifts), taken ~3h in
_BREAK_DUE_AFTER = 5.0  # flag for a meal once someone has worked 5h without one


def _initials(name: str) -> str:
    parts = name.split()
    return (parts[0][0] + parts[-1][0]).upper() if len(parts) >= 2 else name[:2].upper()


def _segment(start: int, end: int) -> str:
    if start <= STORE["open_hour"]:
        return "opener"
    if end >= STORE["close_hour"]:
        return "closer"
    return "mid"


def _person_state(p: dict, eff: float) -> dict:
    """Resolve one roster row into a live status at the effective time."""
    start, end, lunch = p["start"], p["end"], p["lunch"]
    seg = _segment(start, end)
    worked = round(max(0.0, eff - start), 1)
    state = "working"
    until: str | None = None
    break_due = False

    if eff < start:
        state = "scheduled"                       # coming in later
        until = _fmt_clock(start)                 # arrives at
    elif eff >= end:
        state = "done"                            # clocked out for the day
        until = _fmt_clock(end)
    elif lunch is not None and lunch <= eff < lunch + _BREAK_LEN:
        state = "lunch"
        until = _fmt_clock(lunch + _BREAK_LEN)    # back at
    elif lunch is None and start + 3 <= eff < start + 3 + _SHORT_BREAK:
        state = "break"
        until = _fmt_clock(start + 3 + _SHORT_BREAK)
    else:
        # On the floor. Overdue for a meal if they have worked 5h+ and either
        # have no meal scheduled or their meal is still ahead of them.
        if worked >= _BREAK_DUE_AFTER and (lunch is None or eff < lunch):
            break_due = True

    return {
        "name": p["name"],
        "initials": _initials(p["name"]),
        "role": p["role"],
        "specialty": p["specialty"],
        "segment": seg,
        "shift": f"{_fmt_clock(start)} – {_fmt_clock(end)}",
        "start_label": _fmt_clock(start),
        "end_label": _fmt_clock(end),
        "state": state,
        "until": until,
        "worked_hours": worked,
        "break_due": break_due,
    }


def _staffing(now: datetime) -> dict:
    eff = _eff_decimal(now)
    people = [_person_state(p, eff) for p in _ROSTER]

    on_now = [p for p in people if p["state"] in ("working", "break", "lunch")]
    working = [p for p in people if p["state"] == "working"]
    on_break = [p for p in people if p["state"] in ("lunch", "break")]
    scheduled = [p for p in people if p["state"] == "scheduled"]
    done = [p for p in people if p["state"] == "done"]
    needs_break = [p for p in working if p["break_due"]]
    closers = [p for p in people if p["segment"] == "closer" and p["state"] != "done"]
    engagements = _live_engagements({p["name"] for p in working})

    # Mark, on each roster row, whether they are currently with a customer — so
    # the team list can show a live "with a customer" state inline.
    assisting_names = {e["rep"] for e in engagements}
    for p in people:
        p["with_customer"] = p["name"] in assisting_names

    return {
        "counts": {
            "scheduled_today": len(people),
            "on_floor": len(working),
            "assisting": len(engagements),
            "at_risk": len([e for e in engagements if e["risk_level"] == "high"]),
            "on_break": len(on_break),
            "needs_break": len(needs_break),
            "coming_later": len(scheduled),
            "done": len(done),
            "closers": len(closers),
        },
        "people": people,
        "next_in": scheduled[0] if scheduled else None,
        "assisting": engagements,
    }


# --------------------------------------------------------------------------- #
# Live floor — who is with a customer right now, opportunity vs. cart, and risk
# --------------------------------------------------------------------------- #
# One template per rep who could be mid-engagement. `opportunity_value` is what
# the visit could reach if fully attached; `cart_value` is what is actually in
# the cart now. The gap between them, plus `risk_level`, is the manager's
# intervene-or-not signal. Only reps who are actually working right now surface.
_ENGAGEMENTS = [
    {
        "rep": "Sofia Reyes", "customer": "M. Alvarez", "reason": "Upgrade", "since_min": 22,
        "stage": "Building cart",
        "opportunity_value": 1880, "opportunity_items": ["2-line upgrade", "Protection ×2", "Streaming perk"],
        "cart_value": 999, "cart_items": ["iPhone 15 Pro"],
        "gap": ["2nd eligible line not added", "Protection declined on line 1"],
        "risk_level": "high",
        "risk_reason": "Two lines are upgrade-eligible but only one is in the cart, and protection was declined — a coach-in before checkout protects the attach.",
    },
    {
        "rep": "Devon Clark", "customer": "The Okonkwos", "reason": "Home Internet", "since_min": 14,
        "stage": "Quoting",
        "opportunity_value": 1240, "opportunity_items": ["Home Internet", "Mobile + Home discount", "Router protection"],
        "cart_value": 600, "cart_items": ["Home Internet 5G"],
        "gap": ["Mobile + Home bundle discount not applied"],
        "risk_level": "watch",
        "risk_reason": "Customer is comparing to a competitor's fiber price — the Mobile + Home bundle math would close the gap.",
    },
    {
        "rep": "Jalen Wright", "customer": "R. Delgado", "reason": "Trade-in", "since_min": 31,
        "stage": "Checkout",
        "opportunity_value": 1420, "opportunity_items": ["Device upgrade", "Trade-in credit", "12-mo financing"],
        "cart_value": 1360, "cart_items": ["iPhone 15", "Trade-in: iPhone 12", "AppleCare"],
        "gap": [],
        "risk_level": "none",
        "risk_reason": "High-value deal on track and near close — no intervention needed.",
    },
    {
        "rep": "Emma Lin", "customer": "Walk-in (new)", "reason": "New activation", "since_min": 8,
        "stage": "Building cart",
        "opportunity_value": 820, "opportunity_items": ["New line", "Streaming perk", "Case + charger"],
        "cart_value": 520, "cart_items": ["New line — Unlimited"],
        "gap": ["No perk attached", "No accessories"],
        "risk_level": "watch",
        "risk_reason": "New activation with nothing attached yet — perks and accessories are the easy adds while the account is open.",
    },
]


def _live_engagements(working_names: set[str]) -> list[dict]:
    """Active customer engagements for reps who are on the floor right now."""
    out = []
    for e in _ENGAGEMENTS:
        if e["rep"] not in working_names:
            continue
        attach = round(e["cart_value"] / e["opportunity_value"], 2) if e["opportunity_value"] else 0.0
        out.append({
            **e,
            "initials": _initials(e["rep"]),
            "attach_ratio": attach,          # cart / opportunity (0-1)
            "gap_value": e["opportunity_value"] - e["cart_value"],
        })
    # Surface the riskiest, highest-gap engagements first.
    risk_rank = {"high": 0, "watch": 1, "none": 2}
    out.sort(key=lambda e: (risk_rank[e["risk_level"]], -e["gap_value"]))
    return out


# --------------------------------------------------------------------------- #
# Traffic forecast (staffing adequacy by hour)
# --------------------------------------------------------------------------- #
# Expected walk-in customers per hour — a realistic bimodal retail curve
# (lunch bump + after-work evening peak). Appointments and in-store pickups
# (ISPU) are the scheduled load on top of walk-ins.
_TRAFFIC = {
    10: {"forecast": 9,  "appts": 1, "ispu": 2},
    11: {"forecast": 16, "appts": 2, "ispu": 3},
    12: {"forecast": 24, "appts": 3, "ispu": 4},
    13: {"forecast": 27, "appts": 4, "ispu": 5},
    14: {"forecast": 19, "appts": 2, "ispu": 3},
    15: {"forecast": 16, "appts": 2, "ispu": 2},
    16: {"forecast": 18, "appts": 3, "ispu": 3},
    17: {"forecast": 25, "appts": 4, "ispu": 4},
    18: {"forecast": 30, "appts": 5, "ispu": 5},
    19: {"forecast": 20, "appts": 3, "ispu": 3},
}

_CUSTOMERS_PER_REP = 7  # above this ratio for an hour, the floor is thin


def _floor_staff_at(hour: int, eff: float) -> int:
    """How many consultants are on the floor for a given hour (excludes anyone
    whose scheduled meal overlaps that hour)."""
    n = 0
    for p in _ROSTER:
        if not (p["start"] <= hour < p["end"]):
            continue
        lunch = p["lunch"]
        if lunch is not None and int(lunch) == hour:
            continue
        n += 1
    return n


def _traffic(now: datetime) -> dict:
    eff = _eff_decimal(now)
    cur = now.hour
    hours = []
    peak_hour = cur
    peak_val = -1
    total_appts = total_ispu = 0
    gaps = 0
    for h in range(STORE["open_hour"], STORE["close_hour"]):
        t = _TRAFFIC[h]
        staff = _floor_staff_at(h, eff)
        ratio = t["forecast"] / max(1, staff)
        gap = ratio > _CUSTOMERS_PER_REP
        if gap:
            gaps += 1
        total_appts += t["appts"]
        total_ispu += t["ispu"]
        if t["forecast"] > peak_val:
            peak_val, peak_hour = t["forecast"], h
        hours.append({
            "hour": h,
            "label": _fmt_hour(h),
            "forecast": t["forecast"],
            "appointments": t["appts"],
            "ispu": t["ispu"],
            "staffed": staff,
            "ratio": round(ratio, 1),
            "gap": gap,
            "is_current": h == cur,
            "is_past": h < cur,
        })
    return {
        "hours": hours,
        "current_hour": cur,
        "current_label": _fmt_hour(cur),
        "peak_hour_label": _fmt_hour(peak_hour),
        "peak_forecast": peak_val,
        "appointments_today": total_appts,
        "ispu_today": total_ispu,
        "gap_hours": gaps,
        "max_forecast": max(v["forecast"] for v in _TRAFFIC.values()),
    }


# --------------------------------------------------------------------------- #
# Sales performance
# --------------------------------------------------------------------------- #
def _pace(attain: float, expected: float) -> str:
    """ahead / on / behind vs. where MTD pacing should be by now."""
    if attain >= expected + 0.04:
        return "ahead"
    if attain <= expected - 0.06:
        return "behind"
    return "on"


def _sales(now: datetime) -> dict:
    # Month-to-date pacing: how far through the month we are sets the "expected"
    # attainment a healthy store would be at by now.
    dim = 30
    day = min(now.day, dim)
    month_progress = day / dim

    # (key, label, unit, actual, target, hint). Attainment = actual/target.
    raw = [
        ("pga", "Phone Gross Adds", "count", 128, 220,
         "Biggest gap to plan — prioritize new-line offers on every eligible visit."),
        ("upgrades", "Upgrades", "count", 176, 260,
         "Work the high-priority upgrade list; 9 at-risk lines are upgrade-eligible today."),
        ("mobile_home", "Mobile + Home", "count", 41, 70,
         "Attach Home Internet on qualifying addresses — checker is on the POS home tab."),
        ("perk_attach", "Perk Attach Rate", "pct", 0.47, 0.60,
         "Perks lag plan — bundle a streaming perk on new activations and upgrades."),
        ("premium_mix", "Premium Plan Mix", "pct", 0.58, 0.55,
         "Ahead of plan — keep leading with the premium tier on new lines."),
        ("pull_through", "Pull-Through Sales", "pct", 0.72, 0.80,
         "8 quoted deals from this week are unclosed — follow up before they age out."),
    ]
    targets = []
    for key, label, unit, actual, target, hint in raw:
        attain = actual / target if target else 0.0
        if unit == "count":
            # MTD count metrics: pace against how far through the month we are.
            pace = _pace(attain, month_progress)
        else:
            # Rate metrics (perk attach, premium mix, pull-through): graded on
            # reaching the full target — at/over target is ahead, well under is behind.
            pace = "ahead" if attain >= 1.0 else ("behind" if attain < 0.92 else "on")
        targets.append({
            "key": key,
            "label": label,
            "unit": unit,
            "actual": actual,
            "target": target,
            "attainment": round(attain, 3),
            "pace": pace,
            "hint": hint,
        })

    # High-priority upgrades — upgrade-eligible lines flagged at churn risk.
    at_risk = [
        {"customer": "R. Okafor",   "account": "AC-2043", "device": "iPhone 12 · 34 mo", "reason": "Competitor port-out quote on file", "value": "$1,240 CLV", "priority": "high"},
        {"customer": "L. Marchetti","account": "AC-3388", "device": "Galaxy S21 · 29 mo", "reason": "2 dropped-call tickets in 30 days", "value": "$980 CLV", "priority": "high"},
        {"customer": "D. Nguyen",   "account": "AC-1177", "device": "iPhone 13 · 26 mo", "reason": "EIP paid off · no upgrade in 24 mo", "value": "$1,510 CLV", "priority": "high"},
        {"customer": "S. Patel",    "account": "AC-5521", "device": "Pixel 6 · 31 mo",   "reason": "Autopay lapsed twice", "value": "$860 CLV", "priority": "medium"},
        {"customer": "B. Coleman",  "account": "AC-6790", "device": "iPhone 12 · 33 mo", "reason": "Warranty expiring · cracked screen", "value": "$1,090 CLV", "priority": "medium"},
    ]

    return {
        # Store rank widens with scope: 9 stores in the district, ~54 across the
        # territory's 6 districts, ~140 in the market. Consistent with the
        # District/Territory rollups (Riverside is store #4 of 9 in District 7).
        "rankings": [
            {"scope": "District",  "name": STORE["district"],  "rank": 4, "of": 9, "trend": "up", "delta": 1},
            {"scope": "Territory", "name": STORE["territory"], "rank": 14, "of": 54, "trend": "up", "delta": 3},
            {"scope": "Market",    "name": STORE["market"],    "rank": 38, "of": 140, "trend": "up", "delta": 6},
        ],
        "period": now.strftime("%B") + " MTD",
        "month_progress": round(month_progress, 2),
        "targets": targets,
        "at_risk_upgrades": at_risk,
    }


# --------------------------------------------------------------------------- #
# Operations
# --------------------------------------------------------------------------- #
def _operations(now: datetime) -> dict:
    today = now.date()

    def d(offset: int) -> str:
        return (today + timedelta(days=offset)).strftime("%b %-d")

    shipments = [
        {"id": "SHP-88213", "carrier": "OnTrac", "summary": "iPhone 15 Pro (12) · Pixel 9 (6)", "eta": "Today · by 3 PM", "status": "out_for_delivery", "units": 18},
        {"id": "SHP-88240", "carrier": "FedEx",  "summary": "Accessories restock · 4 cartons", "eta": d(1), "status": "in_transit", "units": 96},
        {"id": "SHP-88301", "carrier": "UPS",    "summary": "Galaxy S24 demo units (3)", "eta": d(2), "status": "label_created", "units": 3},
    ]

    exchanges = [
        {"device": "iPhone 14 Pro", "imei_tail": "··· 4471", "rma": "RMA-5521", "reason": "DOA swap", "days_left": 1},
        {"device": "Galaxy S23",    "imei_tail": "··· 9082", "rma": "RMA-5530", "reason": "14-day return", "days_left": 2},
        {"device": "Pixel 8",       "imei_tail": "··· 1120", "rma": "RMA-5544", "reason": "Defective screen", "days_left": 4},
    ]

    # Unpicked in-store pickups — the ones aging toward auto-cancel need a call
    # to the customer first. Countdown is relative to the effective clock.
    unpicked = [
        {"customer": "A. Reyes",   "order": "ORD-77120", "item": "iPhone 15 · Blue 256GB", "days_waiting": 5, "auto_cancel": "Tomorrow 9 AM", "call_first": True,  "phone": "555-0142"},
        {"customer": "M. Foster",  "order": "ORD-77188", "item": "Galaxy S24 · 128GB",     "days_waiting": 4, "auto_cancel": "In 2 days",     "call_first": True,  "phone": "555-0197"},
        {"customer": "T. Brooks",  "order": "ORD-77205", "item": "AirPods Pro 2",          "days_waiting": 2, "auto_cancel": "In 4 days",     "call_first": False, "phone": "555-0168"},
        {"customer": "K. Alvarez", "order": "ORD-77240", "item": "Watch Ultra · 49mm",     "days_waiting": 1, "auto_cancel": "In 5 days",     "call_first": False, "phone": "555-0111"},
    ]

    planogram = [
        {"name": "Q3 Accessory Wall reset", "date": d(2), "status": "kit_received", "note": "New endcap for cases + chargers"},
        {"name": "Fall device table refresh", "date": d(6), "status": "scheduled", "note": "Front table → new flagship lineup"},
    ]

    launches = [
        {"device": "Pixel 9 Pro Fold", "launch_date": d(9), "preorder_date": d(2), "note": "Preorders open — capture interest list"},
        {"device": "Galaxy Z Flip refresh", "launch_date": d(24), "preorder_date": d(17), "note": "Merch kit arrives week prior"},
    ]

    training = {
        "compliant": 7,
        "total": 9,
        "pct": round(7 / 9, 2),
        "overdue": [
            {"rep": "Sofia Reyes", "course": "Fraud & ID Verification 2026", "due": "Overdue 2 days"},
            {"rep": "Tariq Hassan", "course": "Home Internet Certification", "due": "Due today"},
        ],
    }

    positions = [
        {"title": "Sales Consultant (FT)", "stage": "Interviewing", "candidates": 3, "days_open": 12},
        {"title": "Solutions Specialist (PT)", "stage": "Posted", "candidates": 1, "days_open": 5},
    ]

    return {
        "shipments": shipments,
        "exchanges_to_return": exchanges,
        "unpicked_ispu": unpicked,
        "planogram_changes": planogram,
        "device_launches": launches,
        "training": training,
        "open_positions": positions,
        "counts": {
            "inbound_units": sum(s["units"] for s in shipments),
            "exchanges_due": len([e for e in exchanges if e["days_left"] <= 2]),
            "ispu_call_first": len([u for u in unpicked if u["call_first"]]),
            "training_overdue": len(training["overdue"]),
            "open_positions": len(positions),
        },
    }


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
def build_overview() -> dict:
    """Assemble the full Store Manager snapshot for right now."""
    now = _effective_now()
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "store": {
            "id": STORE["id"],
            "name": STORE["name"],
            "market": STORE["market"],
            "district": STORE["district"],
            "territory": STORE["territory"],
        },
        "as_of": now.isoformat(),
        "as_of_label": _fmt_clock(_eff_decimal(now)),
        "day_label": now.strftime("%A, %B %-d"),
        "hours_label": f"{_fmt_hour(STORE['open_hour'])}–{_fmt_hour(STORE['close_hour'])}",
        "staffing": _staffing(now),
        "traffic": _traffic(now),
        "sales": _sales(now),
        "operations": _operations(now),
    }
