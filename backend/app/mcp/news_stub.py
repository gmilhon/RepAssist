"""Stub 'News' MCP server — The Opener (start-of-shift briefing).

A curated feed reps see at the start of their shift: a To-Do checklist plus
field news (new promos, device launches, policy changes, network updates).
Managed from the Settings page and stored in SQLite; items can link to a One
Source of Truth article. Returned as a morning_huddle A2UI card.

(The element type stays `morning_huddle` internally; the product name is
"The Opener".)
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Session, select

from ..store.db import _engine
from ..store.models import HuddleItem
from .client import MCPClient

# category → semantic tone the client maps to a colour.
CATEGORY_TONE = {
    "To-Do":   "warn",
    "Promo":   "danger",
    "Device":  "info",
    "Policy":  "warn",
    "Network": "ok",
    "News":    "info",
}

# Default feed, inserted once when the table is empty. (category, title, blurb, article_id)
_DEFAULTS = [
    # ── To-Do ──
    ("To-Do", "🎓 Complete the Q3 compliance training",
     "Due Friday · ~20 min. Knock it out before your first customer.", None),
    ("To-Do", "🎯 Review this week's promo talk track",
     "Two minutes to nail the BOGO pitch — see the article.", "OST-1002"),
    ("To-Do", "📱 Set up the Galaxy S26 demo unit",
     "Front table by 10am so it's ready for foot traffic.", None),
    # ── News ──
    ("Promo", "🚀 Unlimited Ultimate BOGO is live",
     "Buy a flagship, get one free with a new line. Runs through Sunday — 🔥 crush "
     "those family-plan upgrades!", "OST-1002"),
    ("Device", "🔥 iPhone 17 Pro — all colors in stock",
     "Trade-in bonus up to $1,000. Lead with the titanium finishes — they sell "
     "themselves! 💪", "OST-1005"),
    ("Device", "📲 Galaxy S26 pre-orders open Friday",
     "Reserve for day-one pickup. Pre-order = free storage upgrade. 🎁", None),
    ("Policy", "📋 Return window is now 30 days",
     "Moved from 14 → 30 days on all devices and accessories, effective today.", "OST-1004"),
    ("Network", "📶 5G Ultra Wideband just expanded",
     "Live in three more neighborhoods this week — 🚀 great upgrade talking point!", None),
]


def seed_defaults_if_empty() -> None:
    """Populate The Opener with a default feed on first run."""
    with Session(_engine) as s:
        if s.exec(select(HuddleItem)).first():
            return
        for i, (cat, title, blurb, art) in enumerate(_DEFAULTS):
            s.add(HuddleItem(category=cat, title=title, blurb=blurb,
                             article_id=art, sort_order=i))
        s.commit()


def get_morning_huddle(arguments: dict) -> dict:
    """MCP tool: The Opener — a To-Do checklist + field news — as an A2UI element."""
    seed_defaults_if_empty()
    with Session(_engine) as s:
        rows = list(s.exec(
            select(HuddleItem)
            .where(HuddleItem.active == True)  # noqa: E712
            .order_by(HuddleItem.sort_order, HuddleItem.id)
        ).all())

    todos = [
        {"title": r.title, "detail": r.blurb, "article_id": r.article_id}
        for r in rows if r.category == "To-Do"
    ]
    items = [
        {
            "category":   r.category,
            "tone":       CATEGORY_TONE.get(r.category, "info"),
            "title":      r.title,
            "blurb":      r.blurb,
            "article_id": r.article_id,
        }
        for r in rows if r.category != "To-Do"
    ]
    today = datetime.now(timezone.utc).strftime("%A, %b %-d")
    return {
        "elements": [
            {
                "type": "morning_huddle",
                "title": "The Opener",
                "subtitle": f"Your start-of-shift brief · {today} — let's go! 🚀",
                "todos": todos,
                "items": items,
            }
        ]
    }


def register(client: MCPClient) -> None:
    client.register_tool("news", "get_morning_huddle", get_morning_huddle)
