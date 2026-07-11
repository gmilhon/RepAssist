"""Stub 'System' MCP server.

Exposes what's new in Rep Assist itself, in plain language for entry-level reps,
and answers follow-up questions about the assistant. Two tools:

  - get_system_enhancements → a system_enhancements A2UI card
  - answer_system_question  → a plain-language answer (the orchestrator routes
                              "system" intent questions here)

Mock content only; swap for a real MCP server backed by release notes / a docs
knowledge base when available.
"""
from __future__ import annotations

from .client import MCPClient

# (tag, title, plain-language detail)
_ENHANCEMENTS = [
    ("New", "Auto-fix for stuck activations",
     "If a line is stuck activating, Rep Assist can re-send the activation for "
     "you — you just approve it. No more calling the activation line."),
    ("New", "Missing-promo detector",
     "When a promo or credit didn't show up, Rep Assist finds why and can "
     "re-apply it with your approval."),
    ("Improved", "Recent orders in the chat",
     "Tap “Recent orders” to instantly pull up the customers you've serviced "
     "today — no searching by account number."),
    ("Improved", "Your open tickets, front and center",
     "See the tickets assigned to you right in the chat and pick up where you "
     "left off with one tap."),
    ("New", "Morning Huddle",
     "A daily feed of new promos, device launches, and field news so you start "
     "your shift in the know."),
]

# Suggested follow-up questions shown on the card (phrased to route to "system").
_SUGGESTIONS = [
    "What's new in Rep Assist this week?",
    "What can Rep Assist do for me now?",
    "How does the promo fixer work?",
]

# Keyword → answer for answer_system_question (first match wins).
_ANSWERS = [
    (("activation", "activate", "stuck", "provision"),
     "For stuck activations, Rep Assist now diagnoses the line and can re-send "
     "the activation request for you — it shows you exactly what it will do and "
     "waits for your approval before making the change."),
    (("promo", "promotion", "discount", "bogo", "rebate"),
     "The missing-promo detector checks why a promo or credit didn't apply and, "
     "when it's a fixable case, re-applies it after you approve. If it can't, it "
     "opens a ticket with all the context attached."),
    (("ticket", "open tickets", "escalat"),
     "Your open tickets now appear right in the chat — tap “My open tickets” to "
     "see them, and tap one to get a recap and next steps."),
    (("order", "recent order", "look up", "customer"),
     "Tap “Recent orders” to instantly pull up customers you've serviced "
     "recently, then tap an order to start working it — no account lookup needed."),
    (("huddle", "news", "promo feed", "launch"),
     "The Morning Huddle is a daily brief of new promos, device launches, and "
     "field news. Tap it at the start of your shift to see what's changed."),
]


def get_system_enhancements(arguments: dict) -> dict:
    """MCP tool: recent system enhancements as an A2UI element."""
    enhancements = [
        {"tag": tag, "title": title, "detail": detail}
        for (tag, title, detail) in _ENHANCEMENTS
    ]
    return {
        "elements": [
            {
                "type": "system_enhancements",
                "title": "What's new in Rep Assist",
                "subtitle": "Recent improvements, in plain language — ask me anything about them",
                "enhancements": enhancements,
                "suggestions": _SUGGESTIONS,
            }
        ]
    }


def answer_system_question(arguments: dict) -> dict:
    """MCP tool: answer a plain-language question about the assistant."""
    q = (arguments.get("question") or "").lower()
    for keywords, answer in _ANSWERS:
        if any(k in q for k in keywords):
            return {"answer": answer}
    # Default: summarise the headline enhancements.
    top = "; ".join(f"{title}" for (_tag, title, _d) in _ENHANCEMENTS[:3])
    return {
        "answer": (
            "Here's what's new in Rep Assist: " + top + ". "
            "Ask me about any of them — for example, how the stuck-activation fix "
            "or the missing-promo detector works."
        )
    }


def register(client: MCPClient) -> None:
    client.register_tool("system", "get_system_enhancements", get_system_enhancements)
    client.register_tool("system", "answer_system_question", answer_system_question)
