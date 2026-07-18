"""Stub 'System' MCP server.

Exposes what's new in Rep Assist itself, in plain language for entry-level reps,
and answers follow-up questions about the assistant. Two tools:

  - get_system_enhancements → a system_enhancements A2UI card
  - answer_system_question  → a plain-language answer (the orchestrator routes
                              "system" intent questions here)

Content is generated from the app's own git commit history by
`scripts/generate_enhancements.py` (run on each deploy — see deploy.sh) and
published to `enhancements_data.json`, checked into git so it ships inside the
Docker image alongside the code it describes. `_FALLBACK` below is the seed
content used only if that file has never been generated (fresh clone, no
ANTHROPIC_API_KEY available at deploy time yet).
"""
from __future__ import annotations

import json
from pathlib import Path

from .client import MCPClient

_DATA_FILE = Path(__file__).parent / "enhancements_data.json"

# (tag, title, plain-language detail, keywords, answer) — used only when
# enhancements_data.json doesn't exist yet.
_FALLBACK = {
    "enhancements": [
        {"tag": "New", "title": "Auto-fix for stuck activations",
         "detail": "If a line is stuck activating, Rep Assist can re-send the activation for "
                    "you — you just approve it. No more calling the activation line.",
         "keywords": ["activation", "activate", "stuck", "provision"],
         "answer": "For stuck activations, Rep Assist diagnoses the line and can re-send "
                    "the activation request for you — it shows you exactly what it will do "
                    "and waits for your approval before making the change."},
        {"tag": "New", "title": "Missing-promo detector",
         "detail": "When a promo or credit didn't show up, Rep Assist finds why and can "
                    "re-apply it with your approval.",
         "keywords": ["promo", "promotion", "discount", "bogo", "rebate"],
         "answer": "The missing-promo detector checks why a promo or credit didn't apply "
                    "and, when it's a fixable case, re-applies it after you approve. If it "
                    "can't, it opens a ticket with all the context attached."},
        {"tag": "Improved", "title": "Recent orders in the chat",
         "detail": "Tap “Recent orders” to instantly pull up the customers you've serviced "
                    "today — no searching by account number.",
         "keywords": ["order", "recent order", "look up", "customer"],
         "answer": "Tap “Recent orders” to instantly pull up customers you've serviced "
                    "recently, then tap an order to start working it — no account lookup needed."},
        {"tag": "Improved", "title": "Your open tickets, front and center",
         "detail": "See the tickets assigned to you right in the chat and pick up where you "
                    "left off with one tap.",
         "keywords": ["ticket", "open tickets", "escalat"],
         "answer": "Your open tickets appear right in the chat — tap “My open tickets” to "
                    "see them, and tap one to get a recap and next steps."},
        {"tag": "New", "title": "The Opener",
         "detail": "A daily feed of new promos, device launches, and field news so you "
                    "start your shift in the know.",
         "keywords": ["huddle", "opener", "news", "promo feed", "launch"],
         "answer": "The Opener is a daily brief of new promos, device launches, and field "
                    "news. Tap it at the start of your shift to see what's changed."},
    ],
    "suggestions": [
        "What's new in Rep Assist this week?",
        "What can Rep Assist do for me now?",
        "How does the promo fixer work?",
    ],
}


def _load() -> dict:
    try:
        if _DATA_FILE.exists():
            data = json.loads(_DATA_FILE.read_text())
            if data.get("enhancements"):
                return data
    except Exception:
        pass
    return _FALLBACK


# Loaded once per process — content is baked into the image at deploy time
# (or written to disk by a local script run), so a fresh read per request
# would just re-parse the same file. Restart the server to pick up changes
# written while it's running.
_data: dict = _load()


def _ensure_walkthrough(e: dict) -> dict:
    """Return the stored walkthrough, or synthesize a minimal one for data that
    predates deploy-time walkthrough generation."""
    wt = e.get("walkthrough")
    if wt and wt.get("steps"):
        return wt
    return {
        "intro": e.get("detail", ""),
        "steps": [
            {"title": "Open Rep Assist",
             "detail": "Head to the Rep Assist chat to get started.", "tip": None},
            {"title": f"Use {e.get('title', 'the feature')}",
             "detail": e.get("answer") or e.get("detail", ""), "tip": None},
        ],
    }


def _video_url_for(title: str) -> str | None:
    """URL of the latest uploaded training video for an enhancement, if any."""
    from ..store import db  # local import to avoid an import cycle at module load
    v = db.latest_video_for_title(title)
    return f"/api/training/video/{v.id}" if v else None


def all_enhancements() -> list[dict]:
    """Full enhancement records (incl. walkthrough/answer/video) for the Training UI."""
    return [
        {**e, "walkthrough": _ensure_walkthrough(e), "video_url": _video_url_for(e.get("title", ""))}
        for e in (_data.get("enhancements") or [])
    ]


def get_system_enhancements(arguments: dict) -> dict:
    """MCP tool: recent system enhancements as an A2UI element."""
    data = _data
    enhancements = [
        {"tag": e["tag"], "title": e["title"], "detail": e["detail"],
         "walkthrough": _ensure_walkthrough(e), "video_url": _video_url_for(e["title"])}
        for e in data["enhancements"]
    ]
    return {
        "elements": [
            {
                "type": "system_enhancements",
                "title": "What's new in Rep Assist",
                "subtitle": "Recent improvements, in plain language — ask me anything about them",
                "enhancements": enhancements,
                "suggestions": data.get("suggestions") or _FALLBACK["suggestions"],
            }
        ]
    }


def answer_system_question(arguments: dict) -> dict:
    """MCP tool: answer a plain-language question about the assistant."""
    data = _data
    q = (arguments.get("question") or "").lower()
    for e in data["enhancements"]:
        if any(k in q for k in e.get("keywords", [])):
            return {"answer": e["answer"]}
    # Default: summarise the headline enhancements.
    top = "; ".join(e["title"] for e in data["enhancements"][:3])
    return {
        "answer": (
            "Here's what's new in Rep Assist: " + top + ". "
            "Ask me about any of them for more detail."
        )
    }


def register(client: MCPClient) -> None:
    client.register_tool("system", "get_system_enhancements", get_system_enhancements)
    client.register_tool("system", "answer_system_question", answer_system_question)
