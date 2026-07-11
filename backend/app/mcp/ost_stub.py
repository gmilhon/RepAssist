"""Stub 'OST' (One Source of Truth) MCP server — the knowledge repository.

Answers knowledge-gap questions raised during triage — promo details, how to
perform a system function (apply a discount, process a return), policy, and
billing explanations — by returning the best-matching **article** as a
`knowledge_article` A2UI card.

Two tools:
  - search_articles → best-matching article for a free-text query
  - get_article     → a specific article by id (used by Morning Huddle links)

Mock content only. Swap for a real MCP server backed by the knowledge base.
"""
from __future__ import annotations

from .client import MCPClient

# article_id → article. `keywords` drive the (mock) search ranking.
_ARTICLES: dict[str, dict] = {
    "OST-1001": {
        "article_id": "OST-1001",
        "title": "How to apply a discount at the point of sale",
        "category": "How-to",
        "updated_label": "Updated Jul 2026",
        "summary": "Apply an eligible discount or promo code to a customer's order in a few steps.",
        "keywords": ["apply", "discount", "promo code", "how", "pos", "point of sale", "coupon"],
        "sections": [
            {"heading": "Before you start",
             "body": "Confirm the line/account is eligible and the promo hasn't already been applied."},
            {"heading": "Steps",
             "body": "1. Open the order in the sales app. 2. Go to Pricing → Add discount. "
                     "3. Enter the promo code or pick from eligible offers. 4. Review the "
                     "adjusted total and confirm. The credit shows on the next bill cycle."},
            {"heading": "If it won't apply",
             "body": "Check eligibility dates and that the device-payment agreement meets the "
                     "promo terms. Still stuck? Describe it in the chat and Rep Assist will diagnose it."},
        ],
    },
    "OST-1002": {
        "article_id": "OST-1002",
        "title": "Unlimited Ultimate BOGO — eligibility & terms",
        "category": "Promo",
        "updated_label": "Updated Jul 2026",
        "summary": "Who qualifies for the buy-one-get-one flagship promo and how the credit is applied.",
        "keywords": ["bogo", "buy one get one", "unlimited ultimate", "promo", "promotion",
                     "eligibility", "terms", "flagship", "free"],
        "sections": [
            {"heading": "Eligibility",
             "body": "Requires a new line on Unlimited Ultimate and the purchase of a qualifying "
                     "flagship device on a device-payment agreement."},
            {"heading": "How the credit works",
             "body": "The second device is credited monthly over 36 months. Credits begin within "
                     "1–2 bill cycles; cancelling the line ends remaining credits."},
            {"heading": "Deadline",
             "body": "Runs through Sunday. Orders must be completed and activated before end of day."},
        ],
    },
    "OST-1003": {
        "article_id": "OST-1003",
        "title": "Why a first bill looks high (proration explained)",
        "category": "Billing",
        "updated_label": "Updated Jun 2026",
        "summary": "The first bill includes partial-month charges plus a month in advance.",
        "keywords": ["first bill", "high bill", "proration", "prorated", "charge", "explain",
                     "billing", "why", "expensive"],
        "sections": [
            {"heading": "What's on it",
             "body": "The first bill is prorated from the activation date, plus one full month billed "
                     "in advance, plus any one-time fees. That's why it's higher than the plan price."},
            {"heading": "What to tell the customer",
             "body": "It normalizes on the second cycle to the expected monthly amount."},
        ],
    },
    "OST-1004": {
        "article_id": "OST-1004",
        "title": "How to process a device return or exchange",
        "category": "How-to",
        "updated_label": "Updated Jul 2026",
        "summary": "Return or exchange a device within the 30-day window.",
        "keywords": ["return", "exchange", "refund", "how", "device", "restocking"],
        "sections": [
            {"heading": "Window",
             "body": "Returns and exchanges are accepted within 30 days of purchase (updated from 14)."},
            {"heading": "Steps",
             "body": "1. Verify the device is in returnable condition. 2. Open the order → Returns. "
                     "3. Select return or exchange and confirm. A restocking fee may apply per policy."},
        ],
    },
    "OST-1005": {
        "article_id": "OST-1005",
        "title": "Trade-in credit: how it's calculated and applied",
        "category": "Promo",
        "updated_label": "Updated Jul 2026",
        "summary": "How trade-in value is assessed and credited to the account.",
        "keywords": ["trade-in", "trade in", "credit", "promo", "device value", "how"],
        "sections": [
            {"heading": "Assessment",
             "body": "Trade-in value is based on device model and condition at drop-off, up to the "
                     "promo maximum for eligible flagships."},
            {"heading": "How it's applied",
             "body": "Credit is spread monthly across the device-payment agreement. It appears within "
                     "1–2 bill cycles after the trade-in is received and graded."},
        ],
    },
    "OST-1006": {
        "article_id": "OST-1006",
        "title": "Activating an eSIM: step-by-step",
        "category": "How-to",
        "updated_label": "Updated Jun 2026",
        "summary": "Provision and activate an eSIM profile on a new device.",
        "keywords": ["esim", "activate", "activation", "provision", "qr", "how", "sim"],
        "sections": [
            {"heading": "Steps",
             "body": "1. Confirm the device supports eSIM. 2. Generate the eSIM profile in the sales app. "
                     "3. Scan the QR on the device. 4. Wait for provisioning to complete (usually < 2 min)."},
            {"heading": "If it stalls",
             "body": "If the line is stuck after 2 minutes, Rep Assist can re-send the activation — "
                     "describe the order in the chat."},
        ],
    },
    "OST-1007": {
        "article_id": "OST-1007",
        "title": "Upgrade eligibility rules",
        "category": "Policy",
        "updated_label": "Updated May 2026",
        "summary": "When a line becomes eligible to upgrade.",
        "keywords": ["upgrade", "eligible", "eligibility", "device payment", "policy", "when"],
        "sections": [
            {"heading": "Rule",
             "body": "A line is upgrade-eligible once the device-payment agreement is 50% paid, or once "
                     "the trade-in window opens. Look for the 'Upgrade eligible' badge on the Device tab."},
        ],
    },
}


def _element(article: dict) -> dict:
    """Wrap a raw article as a knowledge_article A2UI element."""
    return {
        "type": "knowledge_article",
        "source": "One Source of Truth",
        **{k: v for k, v in article.items() if k != "keywords"},
    }


def search_articles(arguments: dict) -> dict:
    """MCP tool: best-matching article for a free-text query."""
    query = (arguments.get("query") or "").lower()
    words = [w for w in query.replace("?", " ").replace(",", " ").split() if len(w) > 2]

    best, best_score = None, 0
    for art in _ARTICLES.values():
        hay = art["title"].lower() + " " + " ".join(art["keywords"])
        score = sum(1 for kw in art["keywords"] if kw in query)          # phrase hits
        score += sum(1 for w in words if w in hay)                        # word hits
        if score > best_score:
            best, best_score = art, score

    if not best or best_score == 0:
        return {"elements": []}
    return {"elements": [_element(best)]}


def get_article(arguments: dict) -> dict:
    """MCP tool: a specific article by id."""
    art = _ARTICLES.get((arguments.get("article_id") or "").upper())
    return {"elements": [_element(art)] if art else []}


def register(client: MCPClient) -> None:
    client.register_tool("ost", "search_articles", search_articles)
    client.register_tool("ost", "get_article", get_article)
