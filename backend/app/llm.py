"""LLM access for triage (classification) and reply composition.

Uses the official Anthropic SDK when ANTHROPIC_API_KEY is set, and otherwise
falls back to a deterministic, rule-based implementation so the whole system
runs offline with zero credentials. Any runtime error from the live API also
degrades gracefully to the mock path rather than failing the conversation.
"""
from __future__ import annotations

import json
import logging
import re
import time

from . import guardrail
from .config import get_settings
from .schemas import (
    ExecutiveSummary,
    ProductionAnalysis,
    Resolution,
    SystemEnhancementsDoc,
    TicketClassificationBatch,
    TriageResult,
)
from .store import db

logger = logging.getLogger("repassist.llm")

# Entity patterns shared by both the live and mock paths.
ORDER_RE = re.compile(r"\b((?:ACT|ORD)-\d{3,})\b", re.IGNORECASE)
ACCOUNT_RE = re.compile(r"\b(AC-\d{3,})\b", re.IGNORECASE)
MTN_RE = re.compile(r"\b(\d{10})\b")
TICKET_RE = re.compile(r"\b(TCK-[A-F0-9]{6,})\b", re.IGNORECASE)

TRIAGE_SYSTEM = (
    "You are the triage classifier for a retail Assisted Sales & Service support "
    "assistant. Reps describe an order or service problem. Classify the request "
    "into exactly one intent:\n"
    "- activation: a line/device is stuck activating or not provisioning\n"
    "- pending_order: an existing order is blocking a new order\n"
    "- promo: a promotion/discount/rebate/BOGO is missing or wrong\n"
    "- occ: a fee waiver, bill credit, account credit, or goodwill credit request "
    "(e.g. waived activation fee, credit for a service outage, courtesy credit)\n"
    "- billing: a billing or charge question that is not a credit request\n"
    "- general: a how-to, policy, or 'what is / details about' question answerable "
    "from the One Source of Truth knowledge base (e.g. how to apply a discount, "
    "promo eligibility/details, why a first bill is high, how to process a return). "
    "Prefer this when the rep is asking how/what rather than reporting something broken.\n"
    "- system: a question about Rep Assist itself — its features, recent "
    "enhancements/updates, or how to use the assistant\n"
    "- other: anything that needs a human and does not fit above\n"
    "Extract any order id (ACT-#### or ORD-####) and account id (AC-####). "
    "Be calibrated: use low confidence when the request is vague."
)

COMPOSE_SYSTEM = (
    "You are Rep Assist, helping a retail rep resolve a customer order "
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
    if m := TICKET_RE.search(text):
        out["ticket_ref_id"] = m.group(1).upper()
    return out


# Sales-motion tagging — a deterministic keyword heuristic, not an LLM
# classifier (a second model call per turn is too expensive for this signal,
# and reps rarely narrate their own sales motion in so many words anyway).
# Recognizes only NSE/AAL/UP; anything else stays unclassified rather than
# guess. This is a first-pass, low-precision signal — validate against real
# order/account "is this a new customer / new line / device swap" data before
# using it for reporting decisions. See docs/16-observability.md.
_SALES_INTENT_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("nse", ("new customer", "new account", "brand new line", "sign up for service",
             "signing up", "new to the network", "starting new service", "walk-in new",
             "open a new account", "new service and equipment", "brand new customer")),
    ("aal", ("add a line", "additional line", "another line", "add line",
             "adding a line", "new line on the account", "extra line", "add-a-line")),
    ("up", ("upgrade", "trade in", "trade-in", "eligible for upgrade",
            "device upgrade", "new phone for", "swap the device", "replace the device",
            "upgrading")),
]


def tag_sales_intent(text: str) -> str | None:
    """Best-effort sales-motion tag (nse | aal | up | None). See module note above."""
    t = text.lower()
    for code, keywords in _SALES_INTENT_RULES:
        if any(k in t for k in keywords):
            return code
    return None


def _client():
    import anthropic

    client = anthropic.Anthropic(api_key=get_settings().anthropic_api_key)
    # Wrap with LangSmith instrumentation when tracing is configured — this
    # makes every Anthropic call appear as a child LLM run in LangSmith with
    # token counts that roll up to the root conversation trace.
    try:
        if get_settings().langsmith_enabled:
            from langsmith.wrappers import wrap_anthropic
            client = wrap_anthropic(client)
    except Exception:
        pass
    return client


def _log_usage(
    function: str,
    model: str,
    latency_ms: int,
    *,
    thread_id: str | None = None,
    resp=None,
    success: bool = True,
    fallback: bool = False,
) -> None:
    """Persist the full token taxonomy + cost for one LLM call attempt —
    live (resp set) or fallback/mock (resp=None, zero-cost). Best-effort;
    analytics must never break the caller, same guarantee as
    db.record_engagement.
    """
    input_tok = output_tok = thinking_tok = cache_creation = cache_read = 0
    cost = 0.0
    if resp is not None:
        usage = getattr(resp, "usage", None)
        input_tok = getattr(usage, "input_tokens", 0) or 0
        output_tok = getattr(usage, "output_tokens", 0) or 0
        cache_creation = getattr(usage, "cache_creation_input_tokens", 0) or 0
        cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
        details = getattr(usage, "output_tokens_details", None)
        thinking_tok = (getattr(details, "thinking_tokens", 0) or 0) if details else 0

        settings = get_settings()
        in_rate = settings.langsmith_input_cost_per_million / 1_000_000
        out_rate = settings.langsmith_output_cost_per_million / 1_000_000
        # Anthropic doesn't return line-item cache pricing on the response —
        # approximate the standard surcharge/discount: cache writes ~1.25x the
        # base input rate (5-minute TTL), cache reads ~0.1x.
        cost = (
            input_tok * in_rate
            + cache_creation * in_rate * 1.25
            + cache_read * in_rate * 0.1
            + output_tok * out_rate
        )

    db.record_llm_call(
        thread_id=thread_id, function=function, model=model or "mock",
        success=success, fallback=fallback,
        input_tokens=input_tok, output_tokens=output_tok, thinking_tokens=thinking_tok,
        cache_creation_tokens=cache_creation, cache_read_tokens=cache_read,
        latency_ms=latency_ms, cost_usd=round(cost, 6),
    )

    if fallback:
        # Only worth checking the window on a fresh fallback — a run of
        # successes can't newly cross the threshold.
        try:
            spike = db.check_fallback_spike()
            if spike:
                from .api import system_health
                system_health.maybe_auto_degrade(
                    f"Elevated LLM fallback rate: {spike['fallback_rate'] * 100:.0f}% over the last "
                    f"{spike['window_minutes']} min ({spike['fallback_calls']}/{spike['calls']} calls)."
                )
        except Exception:  # noqa: BLE001 - alerting must never break the caller
            pass


def _scan_and_log(
    text: str, node: str, source: str, *, thread_id: str | None = None, rep_id: str | None = None,
) -> None:
    """Log-only prompt-injection pattern scan (see docs/16-observability.md
    — never blocks or alters the turn). Best-effort; must never break the
    caller.
    """
    try:
        hit = guardrail.scan_for_injection(text)
        if hit:
            pattern, snippet = hit
            db.record_guardrail_event(
                thread_id=thread_id, rep_id=rep_id, node=node, source=source,
                pattern=pattern, snippet=snippet,
            )
    except Exception:  # noqa: BLE001
        pass


# --------------------------------------------------------------------------- #
# Triage / classification
# --------------------------------------------------------------------------- #
def classify(text: str, thread_id: str | None = None, rep_id: str | None = None) -> TriageResult:
    _scan_and_log(text, node="triage", source="direct", thread_id=thread_id, rep_id=rep_id)
    settings = get_settings()
    if not settings.llm_enabled:
        _log_usage("classify", settings.anthropic_model, 0, thread_id=thread_id, fallback=True)
        return _mock_classify(text)
    t0 = time.monotonic()
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
        _log_usage("classify", settings.anthropic_model, int((time.monotonic() - t0) * 1000),
                   thread_id=thread_id, resp=resp)
        return result
    except Exception as exc:  # noqa: BLE001 - intentional graceful degradation
        logger.warning("Live triage failed (%s); using rule-based fallback", exc)
        _log_usage("classify", settings.anthropic_model, int((time.monotonic() - t0) * 1000),
                   thread_id=thread_id, success=False, fallback=True)
        return _mock_classify(text)


def _mock_classify(text: str) -> TriageResult:
    t = text.lower()
    ents = extract_entities(text)

    def has(*words: str) -> bool:
        return any(w in t for w in words)

    # Ticket reference — if a TCK- id is present this is a recap request.
    # Route to ticket_recap regardless of other keywords ("blocked", etc.).
    if ents.get("ticket_ref_id"):
        intent, conf = "other", 0.9
    # System/product questions first — distinctive phrasing so normal order
    # requests never match here.
    elif has("rep assist", "what's new", "whats new", "new feature", "enhancement",
           "how does this system", "what can you do", "how do i use", "the assistant"):
        intent, conf = "system", 0.85
    # Knowledge / how-to / "details about" questions → One Source of Truth. Checked
    # before the task intents so "how do I apply a discount" is a lookup, not a fix.
    elif has("how do", "how to", "how can", "how does", "what is", "what are",
             "what's the", "whats the", "explain", "details about", "details of",
             "tell me about", "walk me through", "steps to", "where do", "policy",
             "eligib"):
        intent, conf = "general", 0.8
    elif has("activat", "provision", "sim card", "won't turn on", "not active", "no service"):
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
def compose_reply(
    resolution: Resolution, order_context: dict | None, ticket_id: str | None,
    thread_id: str | None = None, rep_id: str | None = None,
) -> str:
    if order_context:
        # Indirect vector — order_context is assembled from a downstream
        # service, not typed by the rep, but flows into the prompt unfiltered.
        _scan_and_log(str(order_context), node="compose", source="indirect",
                      thread_id=thread_id, rep_id=rep_id)
    settings = get_settings()
    if not settings.llm_enabled:
        _log_usage("compose", settings.anthropic_model, 0, thread_id=thread_id, fallback=True)
        return _mock_compose(resolution, ticket_id)
    t0 = time.monotonic()
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
        _log_usage("compose", settings.anthropic_model, int((time.monotonic() - t0) * 1000),
                   thread_id=thread_id, resp=resp)
        return text or _mock_compose(resolution, ticket_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Live compose failed (%s); using template fallback", exc)
        _log_usage("compose", settings.anthropic_model, int((time.monotonic() - t0) * 1000),
                   thread_id=thread_id, success=False, fallback=True)
        return _mock_compose(resolution, ticket_id)


EXEC_SUMMARY_SYSTEM = (
    "You are an operations analyst for the Rep Assist Assisted Sales & Service solution. "
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
        _log_usage("executive_summary", settings.anthropic_model, 0, fallback=True)
        return _mock_executive_summary(overview, gaps)
    t0 = time.monotonic()
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
        _log_usage("executive_summary", settings.anthropic_model, int((time.monotonic() - t0) * 1000), resp=resp)
        return result.model_dump()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Executive summary generation failed (%s); using fallback", exc)
        _log_usage("executive_summary", settings.anthropic_model, int((time.monotonic() - t0) * 1000),
                   success=False, fallback=True)
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


# --------------------------------------------------------------------------- #
# Production-issue analysis (Production Monitor)
# --------------------------------------------------------------------------- #

PROD_ANALYSIS_SYSTEM = (
    "You are a production reliability analyst for a telecom retail Assisted Sales "
    "& Service platform. You receive escalated support tickets that the AI agents "
    "could not resolve. Detect SYSTEMIC production issues from clusters of related "
    "tickets — payment processor failures, backend system errors (e.g. ETNI, the "
    "telephone number inventory system), activation/provisioning failures, promo "
    "engine defects. Mark an issue critical only when it is order-blocking AND "
    "shows a burst of related tickets (roughly 5+ in the window); recurring themes "
    "that are not blocking orders are non_critical. Only report clusters of 2 or "
    "more tickets that plausibly share one root cause; return an empty list when "
    "inflow shows no systemic pattern. Problem statements and fixes must be "
    "specific and operational. Only reference ticket ids you were given."
)


def analyze_production_issues(tickets: list[dict], window_hours: int) -> list[dict]:
    """Cluster recent escalated tickets into systemic production issues.

    Falls back to deterministic keyword clustering when no API key is set or a
    live call fails — same offline-safe guarantee as the rest of the LLM layer.
    """
    if not tickets:
        return []
    settings = get_settings()
    if not settings.llm_enabled:
        _log_usage("production_analysis", settings.anthropic_model, 0, fallback=True)
        return _mock_production_analysis(tickets)
    t0 = time.monotonic()
    try:
        client = _client()
        lines = [
            f"- {t['id']} | {t['created_at']} | intent={t['intent']} | "
            f"priority={t['priority']} | rep={t.get('rep_id') or '—'} | {t['summary']}"
            for t in tickets
        ]
        prompt = (
            f"ESCALATED TICKET INFLOW — last {window_hours}h, {len(tickets)} tickets "
            f"(newest first):\n\n" + "\n".join(lines)
        )
        resp = client.messages.parse(
            model=settings.anthropic_model,
            max_tokens=4096,
            system=PROD_ANALYSIS_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            output_format=ProductionAnalysis,
        )
        result = resp.parsed_output
        if result is None:
            raise ValueError("empty parsed_output")
        _log_usage("production_analysis", settings.anthropic_model, int((time.monotonic() - t0) * 1000), resp=resp)
        known = {t["id"] for t in tickets}
        findings = []
        for issue in result.issues:
            issue.ticket_ids = [tid for tid in issue.ticket_ids if tid in known]
            if len(issue.ticket_ids) >= 2:
                findings.append(issue.model_dump())
        return findings
    except Exception as exc:  # noqa: BLE001
        logger.warning("Production analysis failed (%s); using fallback", exc)
        _log_usage("production_analysis", settings.anthropic_model, int((time.monotonic() - t0) * 1000),
                   success=False, fallback=True)
        return _mock_production_analysis(tickets)


# Keyword rules checked in order; first hit wins. (category, keywords)
_PROD_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("etni",       ("etni", "number inventory", "tn inventory", "telephone number",
                    "number assignment", "number reservation")),
    ("payment",    ("payment", "card declined", "declined", "authorization", "checkout",
                    "gateway", "charge failed")),
    ("activation", ("activation", "activate", "provision", "esim", "sim", "no service",
                    "no signal", "port")),
    ("promo",      ("promo", "bogo", "discount", "trade-in", "credit never", "loyalty")),
    ("billing",    ("bill", "proration", "autopay", "overcharge")),
]

_PROD_COPY: dict[str, tuple[str, str, str]] = {
    # category -> (title, problem_statement, recommended_fix)
    "etni": (
        "ETNI number-inventory failures blocking orders",
        "Escalations reference failures reaching ETNI (telephone number inventory): "
        "TN lookups and number reservations are erroring or timing out during order "
        "flows. Reps cannot assign numbers to new lines, so affected orders cannot "
        "be completed at the point of sale.",
        "Symptoms point at the ETNI service or its connection pool being degraded. "
        "Engage the ETNI on-call, verify service health and connection saturation, "
        "and release stuck TN reservation sessions. Queue affected orders for "
        "automatic retry once inventory lookups recover.",
    ),
    "payment": (
        "Payment authorization failures at checkout",
        "A cluster of escalations shows payment authorizations failing at checkout — "
        "cards declined or the payment step erroring for multiple unrelated customers. "
        "Reps cannot take payment, which blocks order completion.",
        "Check payment-gateway health and recent config/credential changes (merchant "
        "certificate expiry is a common cause). If the gateway error rate stays "
        "elevated, fail over to the secondary processor and replay the failed "
        "authorizations from the retry queue.",
    ),
    "activation": (
        "Activation/provisioning failures across new lines",
        "Multiple escalations show lines stuck between SIM/eSIM provisioning and "
        "network activation — devices provision but never gain service. Customers "
        "leave the store with non-working lines and orders cannot be closed out.",
        "Inspect the activation orchestration queue and the carrier provisioning "
        "API status page for elevated latency or stuck jobs. Clear wedged workflow "
        "jobs and reprocess the affected activations; escalate to the network "
        "provisioning team if the failure rate does not drop.",
    ),
    "promo": (
        "Promo credits not applying",
        "A recurring theme of promotion credits (BOGO, trade-in, loyalty) not "
        "applying to qualifying orders. Not order-blocking, but it is generating "
        "repeat escalations and bill-shock complaints.",
        "Audit the promo rules engine for the affected campaign codes — the usual "
        "cause is an eligibility window or SKU list that no longer matches the "
        "live catalog. Correct the rule and backfill the missing credits.",
    ),
    "billing": (
        "Billing discrepancy theme",
        "Several escalations describe unexpected charges — proration, missing "
        "autopay discounts, or duplicate charges on the current cycle. Recurring "
        "theme rather than an order-blocking incident.",
        "Review the rating/proration job output for the current bill cycle and "
        "re-run the discount pass for the affected accounts; issue corrections "
        "where charges were duplicated.",
    ),
    "other": (
        "Recurring escalation theme (uncategorized)",
        "A cluster of similar escalations that does not map to a known system "
        "category. Review the example tickets to identify the shared root cause.",
        "Triage the example tickets with the Tier 2 team to name the failing "
        "component, then route a defect to the owning team.",
    ),
}

# Order-blocking categories become critical on a burst.
_PROD_CRITICAL = {"etni", "payment", "activation", "backend"}


def _mock_production_analysis(tickets: list[dict]) -> list[dict]:
    """Deterministic keyword clustering for offline mode."""
    clusters: dict[str, list[dict]] = {}
    for t in tickets:
        text = (t.get("summary") or "").lower()
        category = "other"
        for cat, words in _PROD_RULES:
            if any(w in text for w in words):
                category = cat
                break
        clusters.setdefault(category, []).append(t)

    findings: list[dict] = []
    for category, members in clusters.items():
        if len(members) < 3:
            continue
        critical = category in _PROD_CRITICAL and len(members) >= 5
        title, problem, fix = _PROD_COPY[category]
        findings.append({
            "title": title,
            "category": category,
            "severity": "critical" if critical else "non_critical",
            "order_blocking": category in _PROD_CRITICAL,
            "problem_statement": problem,
            "recommended_fix": fix,
            "ticket_ids": [m["id"] for m in members],
        })
    findings.sort(key=lambda f: (f["severity"] != "critical", -len(f["ticket_ids"])))
    return findings


# --------------------------------------------------------------------------- #
# Resolution Desk — AI-assisted ticket triage (education / agent action / defect)
# --------------------------------------------------------------------------- #

# Intents with a real automated resolver behind agents_client.diagnose/execute.
_AGENT_ACTION_INTENTS = {"activation", "pending_order", "promo", "occ"}

RESOLUTION_CLASSIFY_SYSTEM = (
    "You triage escalated Tier 1/2 support tickets for a retail Assisted Sales & "
    "Service assistant into exactly one of three buckets:\n"
    "- education: the customer needs an explanation, how-to, or policy answer — "
    "nothing needs to change on the account/order, just knowledge shared back.\n"
    "- agent_action: an existing automated resolver can likely fix this. ONLY use "
    "this bucket when the ticket's intent is activation, pending_order, promo, or "
    "occ — those are the only intents with a real automated resolver behind them. "
    "Never use agent_action for any other intent.\n"
    "- system_defect: something is actually broken (an error, a stuck workflow, "
    "bad data, a missing capability) and needs the dev team's attention — this is "
    "the default when the ticket isn't a pure knowledge question and isn't one of "
    "the four automatable intents above.\n"
    "Classify every ticket given. Give one sentence of reasoning per ticket."
)


def classify_resolution_tickets(tickets: list[dict]) -> list[dict]:
    """Bucket a batch of escalated tickets for the Resolution Desk's Analyze pass.

    Falls back to a deterministic intent-based rule set when no API key is set
    or a live call fails — same offline-safe guarantee as the rest of the LLM layer.
    """
    if not tickets:
        return []
    settings = get_settings()
    if not settings.llm_enabled:
        _log_usage("resolution_classification", settings.anthropic_model, 0, fallback=True)
        return _mock_classify_resolution(tickets)
    t0 = time.monotonic()
    try:
        client = _client()
        lines = [
            f"- {t['id']} | intent={t['intent']} | priority={t['priority']} | {t['summary']}"
            for t in tickets
        ]
        prompt = f"ESCALATED TICKETS TO CLASSIFY ({len(tickets)}):\n\n" + "\n".join(lines)
        resp = client.messages.parse(
            model=settings.anthropic_model,
            max_tokens=4096,
            system=RESOLUTION_CLASSIFY_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            output_format=TicketClassificationBatch,
        )
        result = resp.parsed_output
        if result is None:
            raise ValueError("empty parsed_output")
        _log_usage("resolution_classification", settings.anthropic_model,
                   int((time.monotonic() - t0) * 1000), resp=resp)
        by_id = {t["id"]: t for t in tickets}
        out = []
        for c in result.classifications:
            ticket = by_id.get(c.ticket_id)
            if not ticket:
                continue
            category = c.category
            if category == "agent_action" and ticket["intent"] not in _AGENT_ACTION_INTENTS:
                category = "system_defect"  # guardrail: no automated resolver exists for this intent
            out.append({"ticket_id": c.ticket_id, "category": category, "reasoning": c.reasoning})
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("Resolution classification failed (%s); using fallback", exc)
        _log_usage("resolution_classification", settings.anthropic_model,
                   int((time.monotonic() - t0) * 1000), success=False, fallback=True)
        return _mock_classify_resolution(tickets)


_MOCK_REASONING = {
    "agent_action": "Intent has an automated resolver that can likely fix this without a manual fix.",
    "education": "This reads as a how-to/policy question the knowledge base already answers.",
    "system_defect": "Doesn't match a knowledge question or an automatable intent — looks like a real defect.",
}


def _mock_classify_resolution(tickets: list[dict]) -> list[dict]:
    """Deterministic intent-based bucketing for offline mode."""
    out = []
    for t in tickets:
        intent = t.get("intent") or "other"
        if intent in _AGENT_ACTION_INTENTS:
            category = "agent_action"
        elif intent in ("billing", "general"):
            category = "education"
        else:
            category = "system_defect"
        out.append({"ticket_id": t["id"], "category": category, "reasoning": _MOCK_REASONING[category]})
    return out


# --------------------------------------------------------------------------- #
# System Enhancements — "What's new in Rep Assist", generated from git log
# --------------------------------------------------------------------------- #

ENHANCEMENTS_SYSTEM = (
    "You maintain the 'What's new in Rep Assist' card that retail sales reps see "
    "inside the Rep Assist app. You are given the app's recent git commit history "
    "and the previously published list of enhancements. Produce an updated list "
    "for rep consumption.\n\n"
    "Rules:\n"
    "- Only include changes a retail rep would notice or care about: new things "
    "Rep Assist can do for them, or visible improvements to existing behavior.\n"
    "- SKIP internal-only changes: bug fixes to deploy scripts/CI/infra, refactors, "
    "dependency bumps, test additions, documentation, config plumbing, admin-only "
    "tooling, and anything with no rep-visible effect.\n"
    "- Write for an entry-level retail rep: plain language, no code terms, no "
    "internal system names unless a rep would recognize them (e.g. 'ETNI' is fine "
    "since reps hear it from Tier 2; 'SSE' or 'API' are not).\n"
    "- Merge/carry-forward: keep still-relevant items from the previous list, "
    "update ones that were expanded on by newer commits, and drop items that are "
    "no longer accurate. Newest and most rep-impactful first.\n"
    "- Cap at 8 items total."
)


def generate_system_enhancements(commit_log: str, previous: list[dict] | None = None) -> dict:
    """Regenerate the 'What's new' card content from recent commit history.

    Unlike the other LLM helpers this has no meaningful offline fallback (there
    is nothing to deterministically summarize from commit subjects alone) — the
    caller (scripts/generate_enhancements.py) is expected to skip the refresh
    entirely when no API key is configured, leaving the existing published
    content untouched rather than overwriting it with a mock.
    """
    settings = get_settings()
    if not settings.llm_enabled:
        raise RuntimeError("ANTHROPIC_API_KEY not configured — cannot generate enhancements")

    client = _client()
    # ensure_ascii=False: keep real Unicode chars (em-dash, curly quotes) as
    # literal text in the prompt. With the default ensure_ascii=True they'd
    # appear as \uXXXX escapes, which the model then treats as literal text
    # rather than an escape and re-escapes on the next round — compounding
    # backslashes on every subsequent regeneration.
    prev_json = json.dumps(previous or [], indent=2, ensure_ascii=False)
    prompt = (
        f"PREVIOUSLY PUBLISHED ENHANCEMENTS:\n{prev_json}\n\n"
        f"RECENT COMMIT HISTORY (newest first):\n{commit_log}\n\n"
        f"Produce the updated enhancements list and 3 suggested follow-up questions."
    )
    t0 = time.monotonic()
    resp = client.messages.parse(
        model=settings.anthropic_model,
        max_tokens=8192,
        system=ENHANCEMENTS_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        output_format=SystemEnhancementsDoc,
    )
    result = resp.parsed_output
    if result is None:
        _log_usage("enhancements", settings.anthropic_model, int((time.monotonic() - t0) * 1000),
                   resp=resp, success=False)
        raise ValueError("empty parsed_output")
    _log_usage("enhancements", settings.anthropic_model, int((time.monotonic() - t0) * 1000), resp=resp)
    return result.model_dump()
