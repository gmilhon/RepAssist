"""Geography, channel and cloud-environment reference data for the Production
Monitor's impact map and P1–P4 severity model.

Every escalation now captures three new dimensions — the **cloud environment**
the reporting rep was connected to (AWS East / AWS West), the **store** they
reported from, and the sales **channel** they belong to. This module is the
single source of truth that ties those together:

- a synthetic roster of retail/indirect/D2D/inside-sales locations across the
  US, each with real-ish coordinates so the map plots believably;
- the two AWS regions with their map coordinates and red/yellow/green
  thresholds; and
- pure helpers that assign a rep to a store, spread a simulated incident across
  stores/channels/clouds, and derive the P-level from the aggregated impact.

Everything is synthetic but internally coherent (a store's cloud follows its
longitude, east vs. west of ~-100°), and consistent with the rest of the
prototype's zero-credential, offline-safe design. Swap `STORES` for the real
location master and `store_for_rep` for the real rep→location assignment later
without changing the API contract.
"""
from __future__ import annotations

import hashlib
from typing import Iterable, Optional

# --------------------------------------------------------------------------- #
# Channels — the sales orgs a reporting user can belong to
# --------------------------------------------------------------------------- #
CHANNELS: list[str] = ["retail", "indirect", "d2d", "inside_sales"]
CHANNEL_LABEL: dict[str, str] = {
    "retail": "Retail",
    "indirect": "Indirect",
    "d2d": "Door-to-Door",
    "inside_sales": "Inside Sales",
}
TOTAL_CHANNELS = len(CHANNELS)

# --------------------------------------------------------------------------- #
# Cloud environments — where the reporting rep's session was connected
# --------------------------------------------------------------------------- #
# Cloud health is RELATIVE to each region's own recent baseline (its trailing
# average in-window volume) rather than an absolute count — so a busy-but-normal
# region reads green and only a genuine spike above normal lights up. A small
# floor keeps a burst from a quiet region (or an empty-history dev DB) from
# needing an unrealistic multiple.
CLOUD_MIN_BASELINE = 3.0    # floor for the comparison scale
CLOUD_YELLOW_RATIO = 1.5    # >= 1.5x the region's baseline → elevated (yellow)
CLOUD_RED_RATIO = 2.5       # >= 2.5x the region's baseline → critical (red)

CLOUD_REGIONS: dict[str, dict] = {
    "aws_east": {
        "id": "aws_east",
        "label": "AWS East",
        "aws_region": "us-east-1",
        "site": "N. Virginia",
        "lat": 38.95, "lng": -77.45,
    },
    "aws_west": {
        "id": "aws_west",
        "label": "AWS West",
        "aws_region": "us-west-2",
        "site": "Oregon",
        "lat": 45.87, "lng": -119.69,
    },
}


def cloud_status(count: float, baseline: float = 0.0) -> str:
    """Red/yellow/green for a region: how far its in-window volume sits above its
    own recent baseline. `baseline` is the region's expected in-window volume
    (trailing daily average); the min floor avoids over-reacting to tiny numbers."""
    scale = max(baseline, CLOUD_MIN_BASELINE)
    ratio = count / scale if scale else 0.0
    if ratio >= CLOUD_RED_RATIO:
        return "red"
    if ratio >= CLOUD_YELLOW_RATIO:
        return "yellow"
    return "green"


def cloud_for_lng(lng: float) -> str:
    """A store west of ~-100° routes to AWS West; everything else to AWS East."""
    return "aws_west" if lng < -100.0 else "aws_east"


# --------------------------------------------------------------------------- #
# Store roster — reporting locations across the US
# --------------------------------------------------------------------------- #
# (id, name, city, state, lat, lng, channel). `cloud` is derived from longitude
# below so a location and the region it connects to never disagree.
_RAW_STORES: list[tuple] = [
    # ---- East of -100° → AWS East ----
    ("R-1012", "Midtown Flagship",     "New York",     "NY", 40.7128,  -74.0060, "retail"),
    ("R-1027", "Back Bay",             "Boston",       "MA", 42.3555,  -71.0656, "retail"),
    ("R-1039", "Center City",          "Philadelphia", "PA", 39.9526,  -75.1652, "indirect"),
    ("R-1044", "Capital Gallery",      "Washington",   "DC", 38.9072,  -77.0369, "inside_sales"),
    ("R-1058", "Peachtree Walk",       "Atlanta",      "GA", 33.7490,  -84.3880, "retail"),
    ("R-1063", "Brickell Bay",         "Miami",        "FL", 25.7617,  -80.1918, "d2d"),
    ("R-1071", "Lake Eola",            "Orlando",      "FL", 28.5383,  -81.3792, "retail"),
    ("R-1086", "Uptown Charlotte",     "Charlotte",    "NC", 35.2271,  -80.8431, "indirect"),
    ("R-1090", "Music Row",            "Nashville",    "TN", 36.1627,  -86.7816, "retail"),
    ("R-1104", "Short North",          "Columbus",     "OH", 39.9612,  -82.9988, "d2d"),
    ("R-1112", "Riverfront",           "Detroit",      "MI", 42.3314,  -83.0458, "indirect"),
    ("R-1125", "Mag Mile",             "Chicago",      "IL", 41.8781,  -87.6298, "retail"),
    ("R-1133", "North Loop",           "Minneapolis",  "MN", 44.9778,  -93.2650, "inside_sales"),
    ("R-1147", "Circle Centre",        "Indianapolis", "IN", 39.7684,  -86.1581, "retail"),
    ("R-1156", "Strip District",       "Pittsburgh",   "PA", 40.4406,  -79.9959, "indirect"),
    ("R-1168", "Bayshore",             "Tampa",        "FL", 27.9506,  -82.4572, "retail"),
    ("R-1172", "Galleria",             "Houston",      "TX", 29.7604,  -95.3698, "d2d"),
    ("R-1184", "Deep Ellum",           "Dallas",       "TX", 32.7767,  -96.7970, "retail"),
    ("R-1195", "Gateway Arch",         "St. Louis",    "MO", 38.6270,  -90.1994, "inside_sales"),
    ("R-1203", "Country Club Plaza",   "Kansas City",  "MO", 39.0997,  -94.5786, "indirect"),
    # ---- West of -100° → AWS West ----
    ("R-2011", "Sunset Strip",         "Los Angeles",  "CA", 34.0522, -118.2437, "retail"),
    ("R-2024", "Union Square",         "San Francisco","CA", 37.7749, -122.4194, "retail"),
    ("R-2036", "Gaslamp Quarter",      "San Diego",    "CA", 32.7157, -117.1611, "indirect"),
    ("R-2048", "Pike Place",           "Seattle",      "WA", 47.6062, -122.3321, "retail"),
    ("R-2055", "Pearl District",       "Portland",     "OR", 45.5152, -122.6784, "d2d"),
    ("R-2063", "Camelback",            "Phoenix",      "AZ", 33.4484, -112.0740, "retail"),
    ("R-2077", "The Strip",            "Las Vegas",    "NV", 36.1699, -115.1398, "inside_sales"),
    ("R-2089", "LoDo",                 "Denver",       "CO", 39.7392, -104.9903, "indirect"),
    ("R-2094", "City Creek",           "Salt Lake City","UT", 40.7608, -111.8910, "d2d"),
    ("R-2108", "Old Town",             "Albuquerque",  "NM", 35.0844, -106.6504, "retail"),
]

STORES: list[dict] = [
    {
        "id": sid, "name": name, "city": city, "state": state,
        "lat": lat, "lng": lng, "channel": channel,
        "cloud": cloud_for_lng(lng),
    }
    for (sid, name, city, state, lat, lng, channel) in _RAW_STORES
]

STORE_BY_ID: dict[str, dict] = {s["id"]: s for s in STORES}


def store(store_id: Optional[str]) -> Optional[dict]:
    return STORE_BY_ID.get(store_id) if store_id else None


# --------------------------------------------------------------------------- #
# Assignment helpers
# --------------------------------------------------------------------------- #
def store_for_rep(rep_id: Optional[str]) -> dict:
    """Deterministically map a rep to their home store.

    Stable across restarts (hash-based), so an organic escalation from the same
    rep always plots at the same location — no DB of rep→store needed for the
    prototype.
    """
    key = (rep_id or "rep.unknown").encode("utf-8")
    idx = int(hashlib.md5(key).hexdigest(), 16) % len(STORES)
    return STORES[idx]


def stores_matching(
    channels: Optional[Iterable[str]] = None,
    clouds: Optional[Iterable[str]] = None,
) -> list[dict]:
    chan = set(channels) if channels else None
    cld = set(clouds) if clouds else None
    return [
        s for s in STORES
        if (chan is None or s["channel"] in chan)
        and (cld is None or s["cloud"] in cld)
    ]


# --------------------------------------------------------------------------- #
# P1–P4 severity — derived from the aggregated impact of a cluster
# --------------------------------------------------------------------------- #
# P1  all channels, sales-blocking
# P2  more than one channel, sales-blocking
# P3  multiple locations/channels, not sales-blocking, no workaround
# P4  some locations/channels, not sales-blocking, workaround provided
PRIORITY_LABEL: dict[str, str] = {
    "P1": "P1 · Critical",
    "P2": "P2 · High",
    "P3": "P3 · Medium",
    "P4": "P4 · Low",
}


def compute_priority_level(
    n_channels: int,
    n_stores: int,
    order_blocking: bool,
    workaround_available: bool,
) -> str:
    """The P-level for a cluster from its channel/location breadth, whether it
    blocks sales, and whether a workaround exists."""
    if order_blocking:
        # Sales-blocking is always P1/P2. All channels → P1, otherwise P2.
        return "P1" if n_channels >= TOTAL_CHANNELS else "P2"
    # Not sales-blocking → P3/P4. A workaround pulls it down to P4; otherwise
    # any spread across multiple channels or locations is P3.
    if workaround_available:
        return "P4"
    if n_channels >= 2 or n_stores >= 2:
        return "P3"
    return "P4"


def severity_for_priority(priority_level: str) -> str:
    """Map the P-level onto the monitor's internal critical/non_critical axis
    (which drives email alerts vs. JIRA defect filing). P1/P2 are sales-blocking
    → critical; P3/P4 → non_critical."""
    return "critical" if priority_level in ("P1", "P2") else "non_critical"
