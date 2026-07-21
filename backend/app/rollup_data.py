"""District & Territory rollup data for field-leadership dashboards.

Two consolidated views that sit above the single store:

- **District rollup** (District Manager) — a DAILY operating picture across the
  stores in one district. The DM touches base with each store manager every day,
  so this leans operational and current: today's traffic, live coverage gaps,
  sales pace, at-risk deals and the operational backlog that needs action today.

- **Territory rollup** (Director) — a WEEKLY trajectory across the districts in
  one territory. The Director syncs weekly, so this leans strategic: week-to-date
  attainment, week-over-week trend, and which districts/stores are the outliers
  to manage (both the ones slipping and the ones to replicate).

Everything is synthetic but internally coherent, and consistent with the single
store view: Riverside Commons is store #4 of 9 in District 7, which is 1 of 6
districts (54 stores) in North Territory. Riverside's operational row is pulled
live from `store_manager_data` so the rollup and the store view never disagree.
Swap the store/district tables for the real sales datamart later without changing
the API contract.
"""
from __future__ import annotations

from datetime import datetime, timezone

from . import store_manager_data as smd

DIRECTOR = "Elena Vasquez"          # North Territory
DISTRICT_MANAGER = "Marcus Webb"    # District 7 (Riverside Commons' DM)

# --------------------------------------------------------------------------- #
# Store roster for District 7 (composite scorecard index: 100 = on plan/pace).
# `pga` / `upgrades` / `mobile_home` are attainment-to-target (0-1.2) — the same
# metrics the store manager sees, so a DM can spot which store lags on which
# motion. Riverside Commons' operational fields are overlaid live below.
# --------------------------------------------------------------------------- #
_STORES = [
    {"id": "R-2210", "name": "Summit Crossing",  "manager": "Alicia Fontaine", "index": 112,
     "pga": 1.02, "upgrades": 1.08, "mobile_home": 0.95, "traffic": 240, "coverage": "ok",
     "gap_hours": 0, "on_floor": 8, "scheduled": 11, "needs_break": 0, "ops_alerts": 1,
     "at_risk_deals": 0, "training_pct": 1.0, "open_positions": 0, "trend": "up"},
    {"id": "R-3187", "name": "Harbor Point",     "manager": "Ben Ortiz", "index": 104,
     "pga": 0.94, "upgrades": 1.0, "mobile_home": 0.88, "traffic": 210, "coverage": "ok",
     "gap_hours": 0, "on_floor": 7, "scheduled": 10, "needs_break": 0, "ops_alerts": 2,
     "at_risk_deals": 1, "training_pct": 0.9, "open_positions": 1, "trend": "up"},
    {"id": "R-5540", "name": "Oakdale Center",   "manager": "Priyanka Rao", "index": 97,
     "pga": 0.82, "upgrades": 0.9, "mobile_home": 0.8, "traffic": 190, "coverage": "ok",
     "gap_hours": 0, "on_floor": 6, "scheduled": 9, "needs_break": 1, "ops_alerts": 3,
     "at_risk_deals": 0, "training_pct": 0.89, "open_positions": 0, "trend": "flat"},
    # Riverside Commons — operational fields overlaid from the live store view.
    {"id": smd.STORE["id"], "name": smd.STORE["name"], "manager": "Jordan Ellis", "index": 92,
     "pga": 0.58, "upgrades": 0.68, "mobile_home": 0.59, "traffic": 204, "coverage": "gap",
     "gap_hours": 1, "on_floor": 7, "scheduled": 9, "needs_break": 1, "ops_alerts": 6,
     "at_risk_deals": 1, "training_pct": 0.78, "open_positions": 2, "trend": "up", "is_self": True},
    {"id": "R-4490", "name": "Lakeview Mall",    "manager": "Carlos Mendez", "index": 88,
     "pga": 0.72, "upgrades": 0.79, "mobile_home": 0.7, "traffic": 175, "coverage": "thin",
     "gap_hours": 1, "on_floor": 6, "scheduled": 8, "needs_break": 1, "ops_alerts": 4,
     "at_risk_deals": 1, "training_pct": 0.85, "open_positions": 1, "trend": "down"},
    {"id": "R-6612", "name": "Metro Station",    "manager": "Dana Whitfield", "index": 84,
     "pga": 0.68, "upgrades": 0.74, "mobile_home": 0.66, "traffic": 160, "coverage": "thin",
     "gap_hours": 1, "on_floor": 5, "scheduled": 8, "needs_break": 2, "ops_alerts": 3,
     "at_risk_deals": 2, "training_pct": 0.8, "open_positions": 1, "trend": "flat"},
    {"id": "R-7008", "name": "Northgate",        "manager": "Sam Reilly", "index": 79,
     "pga": 0.62, "upgrades": 0.7, "mobile_home": 0.6, "traffic": 150, "coverage": "gap",
     "gap_hours": 2, "on_floor": 5, "scheduled": 7, "needs_break": 1, "ops_alerts": 5,
     "at_risk_deals": 2, "training_pct": 0.75, "open_positions": 3, "trend": "down"},
    {"id": "R-7731", "name": "Pine Hollow",      "manager": "Grace Abbott", "index": 74,
     "pga": 0.55, "upgrades": 0.64, "mobile_home": 0.55, "traffic": 140, "coverage": "gap",
     "gap_hours": 2, "on_floor": 4, "scheduled": 7, "needs_break": 2, "ops_alerts": 6,
     "at_risk_deals": 2, "training_pct": 0.7, "open_positions": 2, "trend": "down"},
    {"id": "R-8853", "name": "Westfield Gate",   "manager": "Victor Cho", "index": 61,
     "pga": 0.44, "upgrades": 0.52, "mobile_home": 0.41, "traffic": 120, "coverage": "gap",
     "gap_hours": 3, "on_floor": 3, "scheduled": 6, "needs_break": 2, "ops_alerts": 9,
     "at_risk_deals": 3, "training_pct": 0.6, "open_positions": 4, "trend": "down"},
]

# --------------------------------------------------------------------------- #
# District roster for North Territory (6 districts, 54 stores). District 7 is
# derived from its store rows above; the rest are seeded. `wow` = week-over-week
# index change (points) — the Director's key weekly signal.
# --------------------------------------------------------------------------- #
_OTHER_DISTRICTS = [
    {"id": "D-03", "name": "District 3",  "dm": "Renee Coleman",  "stores": 9,  "index": 96, "wow": 1.8,
     "top": "Cedar Point", "bottom": "Rowan Square", "red_stores": 1, "training_pct": 0.94,
     "open_positions": 4, "at_risk_deals": 6, "trend": "up"},
    {"id": "D-11", "name": "District 11", "dm": "Tanya Brooks",   "stores": 8,  "index": 91, "wow": -2.4,
     "top": "Grand Mesa", "bottom": "Ferndale", "red_stores": 2, "training_pct": 0.88,
     "open_positions": 5, "at_risk_deals": 9, "trend": "down"},
    {"id": "D-14", "name": "District 14", "dm": "Derek Osei",     "stores": 10, "index": 85, "wow": 0.4,
     "top": "Kingsway", "bottom": "Ash Grove", "red_stores": 3, "training_pct": 0.82,
     "open_positions": 7, "at_risk_deals": 11, "trend": "flat"},
    {"id": "D-19", "name": "District 19", "dm": "Lauren Kim",     "stores": 10, "index": 79, "wow": -3.1,
     "top": "Belmont", "bottom": "Sutter Row", "red_stores": 4, "training_pct": 0.74,
     "open_positions": 9, "at_risk_deals": 14, "trend": "down"},
    {"id": "D-22", "name": "District 22", "dm": "Paul Nakamura",  "stores": 8,  "index": 99, "wow": 3.2,
     "top": "Vista Ridge", "bottom": "Copperfield", "red_stores": 0, "training_pct": 0.95,
     "open_positions": 3, "at_risk_deals": 4, "trend": "up"},
]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _pace(index: int) -> str:
    """Composite index → ahead / on / behind (100 = on plan)."""
    if index >= 100:
        return "ahead"
    if index >= 90:
        return "on"
    return "behind"


def _store_flags(s: dict) -> list[str]:
    """Short outlier tags used in the district table + callouts."""
    flags = []
    if s["index"] < 75:
        flags.append("Well behind plan")
    elif s["index"] < 90:
        flags.append("Behind plan")
    if s["pga"] < 0.6:
        flags.append("PGA lagging")
    if s["mobile_home"] < 0.6:
        flags.append("Mobile+Home soft")
    if s["coverage"] == "gap":
        flags.append("Coverage gap")
    if s["ops_alerts"] >= 6:
        flags.append("Ops backlog")
    if s["training_pct"] < 0.75:
        flags.append("Training gaps")
    if s["at_risk_deals"] >= 2:
        flags.append("Live deals at risk")
    return flags


def _live_riverside() -> dict:
    """Overlay Riverside Commons' operational fields from the live store view so
    the district rollup and the single store view always agree."""
    try:
        o = smd.build_overview()
        st = o["staffing"]["counts"]
        opsc = o["operations"]["counts"]
        return {
            "traffic": sum(h["forecast"] for h in o["traffic"]["hours"]),
            "coverage": "gap" if o["traffic"]["gap_hours"] else "ok",
            "gap_hours": o["traffic"]["gap_hours"],
            "on_floor": st["on_floor"],
            "scheduled": st["scheduled_today"],
            "needs_break": st["needs_break"],
            "at_risk_deals": st.get("at_risk", 0),
            "ops_alerts": opsc["ispu_call_first"] + opsc["exchanges_due"] + opsc["training_overdue"],
            "training_pct": o["operations"]["training"]["pct"],
            "open_positions": opsc["open_positions"],
        }
    except Exception:  # noqa: BLE001 — never let the live overlay break the rollup
        return {}


def _stores_ranked() -> list[dict]:
    """The 9 District-7 stores, Riverside overlaid live, ranked by index."""
    rows = [dict(s) for s in _STORES]
    for r in rows:
        if r.get("is_self"):
            r.update(_live_riverside())
        r["pace"] = _pace(r["index"])
        r["flags"] = _store_flags(r)
    rows.sort(key=lambda r: -r["index"])
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


# --------------------------------------------------------------------------- #
# District rollup (District Manager — daily)
# --------------------------------------------------------------------------- #
def build_district_rollup() -> dict:
    now = datetime.now(timezone.utc)
    stores = _stores_ranked()
    n = len(stores)
    behind = [s for s in stores if s["index"] < 90]
    coverage_issues = [s for s in stores if s["coverage"] in ("gap", "thin")]
    district_index = round(sum(s["index"] for s in stores) / n)

    # Outliers to manage today: worst + best by index, plus any store that is
    # both understaffed and busy (needs help now).
    worst = stores[-1]
    best = stores[0]

    return {
        "generated_at": now.isoformat(),
        "level": "district",
        "scope": {
            "name": smd.STORE["district"],
            "leader_role": "District Manager",
            "leader": DISTRICT_MANAGER,
            "territory": smd.STORE["territory"],
        },
        "cadence": "daily",
        "day_label": smd.build_overview()["day_label"],
        "period": datetime.now(timezone.utc).strftime("%B") + " MTD",
        "kpis": {
            "stores": n,
            "district_index": district_index,
            "pace": _pace(district_index),
            "stores_behind": len(behind),
            "traffic_today": sum(s["traffic"] for s in stores),
            "coverage_gaps": len(coverage_issues),
            "ops_alerts": sum(s["ops_alerts"] for s in stores),
            "at_risk_deals": sum(s["at_risk_deals"] for s in stores),
            "needs_break": sum(s["needs_break"] for s in stores),
            "open_positions": sum(s["open_positions"] for s in stores),
        },
        "stores": stores,
        "outliers": {
            "lagging": [s for s in stores if s["index"] < 80],
            "leading": [s for s in stores if s["index"] >= 100],
            "worst": worst,
            "best": best,
        },
    }


# --------------------------------------------------------------------------- #
# Territory rollup (Director — weekly)
# --------------------------------------------------------------------------- #
def _district7_summary(stores: list[dict]) -> dict:
    """Roll District 7's store rows up into a district-level record so it sits
    alongside the seeded districts in the territory view."""
    n = len(stores)
    return {
        "id": "D-07", "name": smd.STORE["district"], "dm": DISTRICT_MANAGER, "stores": n,
        "index": round(sum(s["index"] for s in stores) / n), "wow": 0.9,
        "top": max(stores, key=lambda s: s["index"])["name"],
        "bottom": min(stores, key=lambda s: s["index"])["name"],
        "red_stores": len([s for s in stores if s["index"] < 75]),
        "training_pct": round(sum(s["training_pct"] for s in stores) / n, 2),
        "open_positions": sum(s["open_positions"] for s in stores),
        "at_risk_deals": sum(s["at_risk_deals"] for s in stores),
        "trend": "up", "is_home": True,
    }


def build_territory_rollup() -> dict:
    now = datetime.now(timezone.utc)
    stores = _stores_ranked()
    districts = [_district7_summary(stores)] + [dict(d) for d in _OTHER_DISTRICTS]
    for d in districts:
        d["pace"] = _pace(d["index"])
    districts.sort(key=lambda d: -d["index"])
    for i, d in enumerate(districts, 1):
        d["rank"] = i

    n = len(districts)
    total_stores = sum(d["stores"] for d in districts)
    territory_index = round(sum(d["index"] for d in districts) / n)
    behind = [d for d in districts if d["index"] < 90]
    declining = [d for d in districts if d["wow"] <= -1.0]
    rising = [d for d in districts if d["wow"] >= 1.5]

    return {
        "generated_at": now.isoformat(),
        "level": "territory",
        "scope": {
            "name": smd.STORE["territory"],
            "leader_role": "Director",
            "leader": DIRECTOR,
            "market": smd.STORE["market"],
        },
        "cadence": "weekly",
        "period": "Week to date",
        "kpis": {
            "districts": n,
            "stores": total_stores,
            "territory_index": territory_index,
            "pace": _pace(territory_index),
            "districts_behind": len(behind),
            "wow": round(sum(d["wow"] for d in districts) / n, 1),
            "red_stores": sum(d["red_stores"] for d in districts),
            "training_pct": round(sum(d["training_pct"] for d in districts) / n, 2),
            "open_positions": sum(d["open_positions"] for d in districts),
            "at_risk_deals": sum(d["at_risk_deals"] for d in districts),
        },
        "districts": districts,
        # Weakest store anywhere in the territory is worth the Director's eye.
        "worst_store": min(stores, key=lambda s: s["index"]),
        "outliers": {
            "declining": sorted(declining, key=lambda d: d["wow"]),
            "rising": sorted(rising, key=lambda d: -d["wow"]),
            "behind": sorted(behind, key=lambda d: d["index"]),
        },
    }
