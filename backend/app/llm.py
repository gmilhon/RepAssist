"""LLM access for triage (classification) and reply composition.

Uses the official Anthropic SDK when ANTHROPIC_API_KEY is set, and otherwise
falls back to a deterministic, rule-based implementation so the whole system
runs offline with zero credentials. Any runtime error from the live API also
degrades gracefully to the mock path rather than failing the conversation.
"""
from __future__ import annotations

import logging
import re

from .config import get_settings
from .schemas import ExecutiveSummary, Resolution, TriageResult

logger = logging.getLogger("repassist.llm")

# Entity patterns shared by both the live and mock paths.
ORDER_RE = re.compile(r"\b((?:ACT|ORD)-\d{3,})\b", re.IGNORECASE)
ACCOUNT_RE = re.compile(r"\b(AC-\d{3,})\b", re.IGNORECASE)
MTN_RE = re.compile(r"\b(\d{10})\b")

TRIAGE_SYSTEM = (
    "You are the triage classifier for a Verizon retail point-of-sale support "
    "assistant. Reps describe an order or service problem. Classify the request "
    "into exactly one intent:\n"
    "- activation: a line/device is stuck activating or not provisioning\n"
    "- pending_order: an existing order is blocking a new order\n"
    "- promo: a promotion/discount/rebate/BOGO is missing or wrong\n"
    "- occ: a fee waiver, bill credit, account credit, or goodwill credit request "
    "(e.g. waived activation fee, credit for a service outage, courtesy credit)\n"
    "- billing: a billing or charge question that is not a credit request\n"
    "- general: a how-to / policy question answerable from knowledge\n"
    "- other: anything that needs a human and does not fit above\n"
    "Extract any order id (ACT-#### or ORD-####) and account id (AC-####). "
    "Be calibrated: use low confidence when the request is vague."
)

COMPOSE_SYSTEM = (
    "You are Rep Assist, helping a Verizon retail rep resolve a customer order "
    "issue. Write a short, concrete, friendly reply (2-4 sentences) the rep can "
    "act on. State what was found and what was done or what happens next. Never "
    "invent data beyond the structured context you are given."
)


def extract_entities(text: str) -> dict:
    out: dict = {}
    if m := ORDER_RE.search(text):
        out["order_id"] = m.group(1).upper()
    if m := ACCOUNT_RE.search(text):
        out["account_id"] = m.group(1).upper()
    if m := MTN_RE.search(text):
        out["mtn"] = m.group(1)
    return out


def _client():
    import anthropic  # imported lazily so offline mode needs no install of creds

    return anthropic.Anthropic(api_key=get_settings().anthropic_api_key)


# --------------------------------------------------------------------------- #
# Triage / classification
# --------------------------------------------------------------------------- #
def classify(text: str) -> TriageResult:
    settings = get_settings()
    if not settings.llm_enabled:
        return _mock_classify(text)
    try:
        client = _client()
        resp = client.messages.parse(
            model=settings.anthropic_model,
            max_tokens=1024,
            system=TRIAGE_SYSTEM,
            messages=[{"role": "user", "content": text}],
            output_format=TriageResult,
        )
        result = resp.parsed_output
        if result is None:
            raise ValueError("empty parsed_output")
        return result
    except Exception as exc:  # noqa: BLE001 - intentional graceful degradation
        logger.warning("Live triage failed (%s); using rule-based fallback", exc)
        return _mock_classify(text)


def _mock_classify(text: str) -> TriageResult:
    t = text.lower()
    ents = extract_entities(text)

    def has(*words: str) -> bool:
        return any(w in t for w in words)

    if has("activat", "provision", "sim card", "won't turn on", "not active", "no service"):
        intent, conf = "activation", 0.82
    elif has("pending", "blocking", "blocked", "stuck order", "can't order"):
        intent, conf = "pending_order", 0.82
    elif has("waiv", "activation fee", "fee waiver", "bill credit", "courtesy credit",
             "service credit", "account credit", "occ", "other charge"):
        intent, conf = "occ", 0.82
    elif has("promo", "promotion", "discount", "bogo", "rebate", "deal"):
        intent, conf = "promo", 0.8
    elif has("bill", "charge", "invoice", "overcharge", "refund"):
        intent, conf = "billing", 0.7
    elif has("how do", "how to", "policy", "where do", "can i"):
        intent, conf = "general", 0.6
    else:
        intent, conf = "other", 0.3

    return TriageResult(
        intent=intent,
        confidence=conf,
        order_id=ents.get("order_id"),
        account_id=ents.get("account_id"),
        summary=text.strip()[:160] or "Rep submitted a request.",
    )


# --------------------------------------------------------------------------- #
# Reply composition
# --------------------------------------------------------------------------- #
def compose_reply(resolution: Resolution, order_context: dict | None, ticket_id: str | None) -> str:
    settings = get_settings()
    if not settings.llm_enabled:
        return _mock_compose(resolution, ticket_id)
    try:
        client = _client()
        context = {
            "resolution": resolution.model_dump(),
            "order_context": order_context,
            "ticket_id": ticket_id,
        }
        resp = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=512,
            system=COMPOSE_SYSTEM,
            messages=[{"role": "user", "content": f"Context:\n{context}\n\nWrite the rep-facing reply."}],
        )
        parts = [b.text for b in resp.content if getattr(b, "type", "") == "text"]
        text = "".join(parts).strip()
        return text or _mock_compose(resolution, ticket_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Live compose failed (%s); using template fallback", exc)
        return _mock_compose(resolution, ticket_id)


EXEC_SUMMARY_SYSTEM = (
    "You are an operations analyst for Verizon's Rep Assist POS support solution. "
    "You will receive structured KPI and capability-gap data. Write a crisp executive summary "
    "for the Performance dashboard read by VP-level operations leaders. "
    "Be specific with numbers and percentages. Write in plain prose — no bullet points, "
    "no markdown, no headers. Each field should be 2-3 sentences."
)


def generate_executive_summary(overview: dict, gaps: list[dict]) -> dict:
    """Call Claude to produce an AI-generated executive summary of current KPIs.

    Falls back to a deterministic rule-based summary when no API key is set or
    any live call fails — same offline-safe guarantee as the rest of the LLM layer.
    """
    settings = get_settings()
    if not settings.llm_enabled:
        return _mock_executive_summary(overview, gaps)
    try:
        client = _client()
        prompt = _build_summary_prompt(overview, gaps)
        resp = client.messages.parse(
            model=settings.anthropic_model,
            max_tokens=2048,
            system=EXEC_SUMMARY_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            output_format=ExecutiveSummary,
        )
        result = resp.parsed_output
        if result is None:
            raise ValueError("empty parsed_output")
        return result.model_dump()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Executive summary generation failed (%s); using fallback", exc)
        return _mock_executive_summary(overview, gaps)


def _build_summary_prompt(overview: dict, gaps: list[dict]) -> str:
    e = overview.get("engagement", {})
    out = overview.get("outcomes", {})
    ts = overview.get("timeseries", [])
    intents = overview.get("intents", [])
    tickets_data = overview.get("tickets", {})

    # Compute recent vs prior escalation trend
    trend_note = "Insufficient timeseries data for a trend comparison."
    if len(ts) >= 4:
        half = len(ts) // 2
        r_esc = sum(d.get("escalated", 0) for d in ts[-half:])
        p_esc = sum(d.get("escalated", 0) for d in ts[:half])
        if p_esc > 0:
            delta = round((r_esc - p_esc) / p_esc * 100)
            direction = "up" if delta > 0 else "down"
            trend_note = f"Escalations are {direction} {abs(delta)}% vs the prior {half}-day period."

    intent_lines = []
    for it in intents[:6]:
        contain_pct = round(it.get("auto_resolved", 0) / max(1, it.get("count", 1)) * 100)
        intent_lines.append(
            f"  {it['intent']}: {it['count']} interactions, "
            f"{it.get('auto_resolved', 0)} auto-resolved ({contain_pct}% containment), "
            f"{it.get('escalated', 0)} escalated"
        )

    gap_lines = []
    for g in gaps[:5]:
        best_gap = max(g.get("gap_types", {}).items(), key=lambda x: x[1], default=("none", 0))[0]
        gap_lines.append(
            f"  {g['capability']}: score={g['score']}, {g['ticket_count']} tickets, "
            f"primary gap: {best_gap}"
        )

    return (
        f"OPERATIONAL DATA — {len(ts)}-day window:\n\n"
        f"Engagement: {e.get('conversations', 0)} conversations, "
        f"{e.get('interactions', 0)} interactions, {e.get('active_reps', 0)} active reps\n"
        f"Outcomes: {round(out.get('containment_rate', 0) * 100)}% containment, "
        f"{round(out.get('escalation_rate', 0) * 100)}% escalation rate, "
        f"{out.get('auto_resolved', 0)} auto-resolved, {out.get('escalated', 0)} escalated\n"
        f"Avg triage confidence: {round(e.get('avg_confidence', 0) * 100)}%\n"
        f"Escalation trend: {trend_note}\n\n"
        f"Volume by intent:\n" + ("\n".join(intent_lines) or "  (no data)") + "\n\n"
        f"Ticket health: {tickets_data.get('open', 0)} open, "
        f"{tickets_data.get('in_review', 0)} in review, "
        f"avg resolution {tickets_data.get('avg_resolution_hours', 'N/A')}h\n\n"
        f"Capability backlog (ranked by score):\n"
        + ("\n".join(gap_lines) or "  (no resolved gaps yet)") + "\n\n"
        f"Produce the executive summary with:\n"
        f"- headline: 1 bold sentence describing overall solution health\n"
        f"- trending_issues: 2-3 sentences on which intents/issues are most pressing\n"
        f"- containment_escalation: 2-3 sentences on containment health and escalation trends\n"
        f"- backlog_priorities: 2-3 sentences on the most important capability investments\n"
        f"Be specific with numbers. No markdown, no bullet points, no headers."
    )


def _mock_executive_summary(overview: dict, gaps: list[dict]) -> dict:
    e = overview.get("engagement", {})
    out = overview.get("outcomes", {})
    ts = overview.get("timeseries", [])
    intents = overview.get("intents", [])
    tickets_data = overview.get("tickets", {})

    containment_pct = round(out.get("containment_rate", 0) * 100)
    esc_pct = round(out.get("escalation_rate", 0) * 100)
    esc_quality = "healthy" if esc_pct < 20 else ("moderate" if esc_pct < 35 else "elevated")

    high_esc = max(intents, key=lambda i: i.get("escalated", 0), default={})
    high_esc_name = (high_esc.get("intent") or "other").replace("_", " ") if high_esc else "other"
    high_esc_count = high_esc.get("escalated", 0) if high_esc else 0

    trend_note = ""
    if len(ts) >= 4:
        half = len(ts) // 2
        r_esc = sum(d.get("escalated", 0) for d in ts[-half:])
        p_esc = sum(d.get("escalated", 0) for d in ts[:half])
        if p_esc > 0:
            delta = round((r_esc - p_esc) / p_esc * 100)
            direction = "up" if delta > 0 else "down"
            trend_note = f" Escalations are {direction} {abs(delta)}% vs the prior period."

    top_gap = gaps[0] if gaps else None
    gap_text = (
        f"The top investment priority is {top_gap['capability']} "
        f"(backlog score {top_gap['score']}, {top_gap['ticket_count']} tickets requiring capability work). "
        f"Addressing this gap would directly reduce escalation volume in the affected intents."
        if top_gap else
        "No resolved capability gaps are on record yet. Resolve and categorize tickets in the Resolution Desk "
        "to surface the highest-value agent and knowledge investments."
    )

    return {
        "headline": (
            f"Rep Assist handled {e.get('interactions', 0)} interactions across "
            f"{e.get('conversations', 0)} conversations with a {containment_pct}% containment rate "
            f"over the last {len(ts)} days."
        ),
        "trending_issues": (
            f"{high_esc_name.title()} issues are generating the most escalations with {high_esc_count} tickets "
            f"opened, suggesting either a capability gap or low-confidence triage in this intent. "
            f"Triage confidence averages {round(e.get('avg_confidence', 0) * 100)}% across all intents, "
            f"indicating most requests are reaching the correct resolution path."
        ),
        "containment_escalation": (
            f"The {esc_quality} escalation rate of {esc_pct}% means {out.get('escalated', 0)} interactions "
            f"required a human specialist out of {out.get('total', 0)} total outcomes.{trend_note} "
            f"The Resolution Desk has {tickets_data.get('open', 0)} open tickets "
            f"with an average resolution time of {tickets_data.get('avg_resolution_hours', '—')} hours."
        ),
        "backlog_priorities": gap_text,
    }


def _mock_compose(resolution: Resolution, ticket_id: str | None) -> str:
    if resolution.status == "resolved":
        actions = " ".join(resolution.actions_taken)
        return f"✅ {resolution.summary} {actions}".strip()
    if resolution.status == "proposed":
        return f"I found the likely cause: {resolution.root_cause}. {resolution.summary}"
    if resolution.status == "cancelled":
        return f"No problem — I did not make any changes. {resolution.summary}"
    if resolution.status == "escalated":
        return (
            f"I couldn't resolve this automatically, so I opened ticket "
            f"{ticket_id} for a Tier 1/2 specialist. {resolution.summary}"
        )
    return resolution.summary
