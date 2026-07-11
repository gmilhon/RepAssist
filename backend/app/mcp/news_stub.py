"""Stub 'News' MCP server — the Morning Huddle.

A curated field-news feed: new promos, device launches, policy changes, and
network updates the rep should know at the start of a shift. Returned as a
morning_huddle A2UI card. Mock content only.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .client import MCPClient

# (category, tone, title, blurb)
_ITEMS = [
    ("Promo", "promo", "Unlimited Ultimate BOGO is live",
     "Buy a flagship, get one free with a new line on Unlimited Ultimate. Runs "
     "through Sunday — great for family-plan upgrades."),
    ("Device", "device", "iPhone 17 Pro — all colors in stock",
     "Trade-in bonus up to $1,000 with an eligible device. Lead with the "
     "titanium finishes; demo units are on the front table."),
    ("Device", "device", "Galaxy S26 pre-orders open Friday",
     "Reserve now for day-one pickup. Pre-order customers get the storage "
     "upgrade free."),
    ("Policy", "policy", "Return window is now 30 days",
     "The standard return/exchange window moved from 14 to 30 days on all "
     "devices and accessories, effective today."),
    ("Network", "network", "5G Ultra Wideband expanded in-market",
     "Coverage went live in three more neighborhoods this week — good talking "
     "point for customers on the fence about upgrading."),
]

_TONES = {"promo": "danger", "device": "info", "policy": "warn", "network": "ok"}


def get_morning_huddle(arguments: dict) -> dict:
    """MCP tool: today's field news as an A2UI element."""
    items = [
        {"category": cat, "tone": _TONES.get(tone, "info"), "title": title, "blurb": blurb}
        for (cat, tone, title, blurb) in _ITEMS
    ]
    today = datetime.now(timezone.utc).strftime("%A, %b %-d")
    return {
        "elements": [
            {
                "type": "morning_huddle",
                "title": "Morning Huddle",
                "subtitle": f"Today's promos, launches, and field news · {today}",
                "items": items,
            }
        ]
    }


def register(client: MCPClient) -> None:
    client.register_tool("news", "get_morning_huddle", get_morning_huddle)
