"""Live Listen: a read-only AI watcher over a live rep–customer conversation.

The rep picks a checked-in customer from the store queue, live transcription
streams utterances in, and each analyze pass surfaces suggestion cards for
issues the existing agent intents can triage. Accepting a card sends a
prepared prompt through the NORMAL chat flow — this module never calls
orchestrator.start_or_continue, never creates tickets, and never calls
agents_client.execute. Enrichment stops at the read-only diagnose.
"""
from __future__ import annotations

import logging
import threading
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import email_reports
from .. import llm
from ..graph.nodes import INTENT_CAPABILITY, NEEDS_ID
from ..integrations import agents_client
from ..mock_services.data import eligibility_badges, resolve_eligibility
from ..schemas import DiagnoseRequest, Intent
from ..store import db
from ..store.models import ListenSession

logger = logging.getLogger("repassist.listen")

router = APIRouter(prefix="/api/listen", tags=["listen"])

# Rolling analysis window: only the most recent utterances go to the model.
WINDOW_UTTERANCES = 12
# Post-validation of model output — never trust the model.
MIN_CONFIDENCE = 0.55
MAX_SUGGESTIONS_PER_CALL = 2
# Bounds on untrusted (voice) transcript input.
MAX_UTTERANCE_CHARS = 2000
MAX_UTTERANCES_PER_CALL = 50

# Shopping intents (add_line/upgrade) are handled by the live cart path
# (_cart_from_listen), not surfaced as issue-suggestion cards.
_VALID_INTENTS = {i.value for i in Intent} - {Intent.ADD_LINE.value, Intent.UPGRADE.value}

# Per-session locks serialize the read-analyze-record sequence so two
# overlapping analyze calls on one session can't race on the JSON columns
# (duplicate suggestion cards / lost transcript appends). Keyed by session id;
# the map is process-local and only grows by the number of live sessions.
_session_locks: dict[str, threading.Lock] = defaultdict(threading.Lock)


class StartListenRequest(BaseModel):
    rep_id: str
    queue_entry_id: str
    thread_id: Optional[str] = None
    mode: str = "mic"  # "mic" | "demo"


class ListenUtterance(BaseModel):
    speaker: Optional[str] = Field(default=None, max_length=60)
    text: str = Field(max_length=MAX_UTTERANCE_CHARS)


class AnalyzeRequest(BaseModel):
    utterances: list[ListenUtterance] = Field(default_factory=list, max_length=MAX_UTTERANCES_PER_CALL)
    # Record the utterances into the transcript WITHOUT running the watcher or
    # cart builder — used by chat-mode demos to seed a gradeable transcript while
    # the rep drives the cart/resolution directly through the chat.
    record_only: bool = False


def _aware(dt: datetime) -> datetime:
    # SQLite round-trips lose tzinfo; all naive datetimes are UTC by
    # construction (models._now) — same normalization as store.db._aware.
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _duration_label(start: datetime, end: datetime) -> str:
    total = max(0, int((_aware(end) - _aware(start)).total_seconds()))
    minutes, seconds = divmod(total, 60)
    return f"{minutes}m {seconds}s" if minutes else f"{seconds}s"


def _session_entities(session: ListenSession) -> dict:
    """The entity keys the queue-assist hand-off pre-fills. Includes the known
    account/order so agents are called with them instead of re-prompting the
    rep for ids the customer's record already carries."""
    entities = {"visit_reason": session.reason}
    if session.customer_name:
        entities["customer_name"] = session.customer_name
    if session.customer_phone:
        entities["customer_phone"] = session.customer_phone
    if session.account_id:
        entities["account_id"] = session.account_id
    if session.order_id:
        entities["order_id"] = session.order_id
    return entities


def _build_prompt(intent: str, entities: dict) -> str:
    """A natural first-person rep request for the Accept hand-off, worded so
    the normal chat triage (live or mock) classifies it back to `intent`."""
    order_id = entities.get("order_id")
    account_id = entities.get("account_id")
    if intent == "activation":
        if order_id:
            return (f"Order {order_id} came up — the customer's activation looks stuck. "
                    "Can you check it?")
        return "The customer's activation sounds stuck. Can you help me check it?"
    if intent == "pending_order":
        if order_id:
            return (f"The customer's new order sounds blocked by a pending order — "
                    f"order {order_id}. Can you take a look?")
        return "The customer's new order sounds blocked by a pending order. Can you take a look?"
    if intent == "promo":
        if account_id:
            return (f"The customer is missing a promo credit on account {account_id}. "
                    "Can you check what happened?")
        return "The customer is missing a promo credit. Can you check what happened?"
    if intent == "occ":
        if account_id:
            return (f"The customer is asking for a fee waiver on account {account_id} — "
                    "can we get that credit applied?")
        return "The customer is asking for a fee waiver — can we get that credit applied?"
    if intent == "billing":
        return ("The customer says their bill looks higher than expected this month — "
                "can you help me figure out why?")
    if intent == "general":
        return "The customer has a how-to question — can you walk me through the right answer?"
    if intent == "system":
        return "What's new in Rep Assist? The customer asked what the assistant can do."
    return "Something came up in this conversation I could use help with — can you take a look?"


@router.post("/start")
def start(req: StartListenRequest) -> dict:
    entry = db.get_queue_entry(req.queue_entry_id)
    if not entry:
        raise HTTPException(404, "Queue entry not found")
    thread_id = req.thread_id or f"thr-{uuid.uuid4().hex[:10]}"
    db.assist_queue_entry(req.queue_entry_id, req.rep_id, thread_id)
    eligibility = resolve_eligibility(entry.account_id)
    session = db.create_listen_session(
        rep_id=req.rep_id,
        thread_id=thread_id,
        queue_entry_id=entry.id,
        customer_name=entry.customer_name,
        customer_phone=entry.customer_phone,
        reason=entry.reason,
        account_id=entry.account_id,
        order_id=entry.order_id,
        eligibility=eligibility,
        mode=req.mode,
    )
    return {
        "session": session,
        "thread_id": thread_id,
        "entities": _session_entities(session),
        "eligibility": eligibility,
        "opportunities": eligibility_badges(eligibility),
    }


@router.post("/{session_id}/analyze")
def analyze(session_id: str, req: AnalyzeRequest) -> dict:
    session = db.get_listen_session(session_id)
    if not session:
        raise HTTPException(404, "Listen session not found")
    if session.status != "active":
        raise HTTPException(409, "Listen session has ended")

    utterances = [
        {"speaker": u.speaker, "text": u.text.strip()}
        for u in req.utterances
        if u.text.strip()
    ]
    # Nothing new to analyze — don't re-run a (paid) LLM pass over the stored
    # window. The frontend only calls analyze after buffering fresh utterances,
    # so this just rejects empty/whitespace-only calls.
    if not utterances:
        known = {**_session_entities(session), **llm.extract_entities(
            " ".join(u["text"] for u in (session.transcript or [])[-WINDOW_UTTERANCES:]))}
        return {"suggestions": [], "entities": known, "cart": None}

    with _session_locks[session_id]:
        # Re-read under the lock so overlapping calls see each other's appends
        # and prior_intents, and re-check the session didn't end mid-flight.
        session = db.get_listen_session(session_id)
        if not session or session.status != "active":
            raise HTTPException(409, "Listen session has ended")
        session = db.append_listen_utterances(session_id, utterances)
        # Transcript-only: seed the visit transcript for end-of-visit grading
        # without surfacing suggestions or mutating the cart.
        if req.record_only:
            return {"suggestions": [], "entities": _session_entities(session), "cart": None}
        result = _run_analysis(session)
        # Also fold any cart mutations heard in the NEW utterances into the
        # thread's shopping cart (idempotent — only the new batch is interpreted).
        result["cart"] = _cart_from_listen(session, " ".join(u["text"] for u in utterances))
        return result


# Cheap pre-filter: only spend an LLM cart-interpret call when the new
# utterances actually mention a device/plan or a cart verb.
_CART_VERBS = ("swap", "change", "switch", "instead", "add", "remove", "drop",
               "take off", "upgrade", "plan", "trade", "protection", "insurance",
               "perk", "case", "charger")


def _has_cart_hint(text: str) -> bool:
    from .. import shop as shop_engine
    cat = shop_engine.cat
    return bool(
        cat.find_device(text) or cat.find_plan(text) or cat.find_perk(text)
        or cat.find_accessory(text) or cat.find_protection(text)
        or any(v in text.lower() for v in _CART_VERBS)
    )


def _cart_from_listen(session: ListenSession, text: str) -> dict | None:
    """During Live Listen, interpret the NEWEST utterances for cart mutations
    (swap device, change plan, add/remove) and apply them to the thread's DRAFT
    cart, so the cart drawer updates as the conversation happens. Read-only
    w.r.t. the account — the order still requires the confirm gate. Only runs
    while a cart is in progress, and only when the text hints at shopping."""
    if not text.strip() or not _has_cart_hint(text):
        return None
    from .. import shop as shop_engine
    from ..mock_services import shop_data
    cart_row = db.get_cart(session.thread_id)
    items = list(cart_row.items) if cart_row else []
    # Build a NEW cart from the conversation only for shopping visits (new
    # service / upgrade); otherwise only EDIT an existing cart, so an ambient
    # "I might upgrade someday" in a support call never spawns a cart.
    shopping_visit = (session.reason or "").lower() in ("new_service", "upgrade")
    if not items and not shopping_visit:
        return None
    account = shop_data.account_summary(session.account_id)
    try:
        turn = llm.interpret_shop_turn(text, account, items,
                                       thread_id=session.thread_id, rep_id=session.rep_id)
    except Exception as exc:  # noqa: BLE001 - listening must never break
        logger.warning("Listen cart interpret failed (%s)", exc)
        return None
    ops = [o for o in turn.ops if o.op != "none"]
    if not ops:
        return None
    new_items, notes = shop_engine.apply_ops(items, ops, account)
    db.save_cart(session.thread_id, new_items, account_id=account.get("account_id"))
    return {"cart": shop_engine.cart_view(new_items), "notes": notes}


def _run_analysis(session: ListenSession) -> dict:
    transcript = session.transcript or []
    session_id = session.id
    window_utterances = transcript[-WINDOW_UTTERANCES:]
    window = "\n".join(
        f"{u['speaker']}: {u['text']}" if u.get("speaker") else u["text"]
        for u in window_utterances
    )
    # Extract ids from the recent window, not the whole transcript: a stale id
    # spoken early in the visit should not bind to a later, unrelated issue.
    window_text = " ".join(u["text"] for u in window_utterances)
    known_entities = {**_session_entities(session), **llm.extract_entities(window_text)}
    prior_intents = [s["intent"] for s in (session.suggestions or [])]

    result = llm.analyze_live_transcript(
        window,
        context={
            "customer_name": session.customer_name,
            "customer_phone": session.customer_phone,
            "visit_reason": session.reason,
            "entities": known_entities,
        },
        prior_intents=prior_intents,
        thread_id=session.thread_id,
        rep_id=session.rep_id,
    )

    # Post-validate the model output in Python — never trust the model: only
    # known intents, nothing already surfaced, nothing low-confidence, and at
    # most two new cards per pass so the rep is never flooded mid-conversation.
    seen = set(prior_intents)
    suggestions: list[dict] = []
    for raw in result.suggestions:
        if raw.intent not in _VALID_INTENTS or raw.intent in seen:
            continue
        if raw.confidence < MIN_CONFIDENCE:
            continue
        seen.add(raw.intent)

        # Only the keys the chat hand-off understands — notably NOT
        # ticket_ref_id, which would reroute the accepted prompt to a ticket
        # recap instead of triaging the suggested intent.
        entities = {
            k: known_entities[k]
            for k in ("order_id", "account_id", "customer_name", "customer_phone", "visit_reason")
            if known_entities.get(k)
        }
        if raw.order_id:
            entities["order_id"] = raw.order_id.upper()
        if raw.account_id:
            entities["account_id"] = raw.account_id.upper()

        # Read-only diagnose enrichment: only for intents with a real resolver
        # AND when the id that resolver needs is already known. NEVER execute.
        diagnosis = None
        intent = Intent(raw.intent)
        needed = NEEDS_ID.get(raw.intent)
        if intent in agents_client.CAPABILITY_PATHS and needed and entities.get(needed):
            try:
                diag = agents_client.diagnose(intent, DiagnoseRequest(
                    order_id=entities.get("order_id"),
                    account_id=entities.get("account_id"),
                    mtn=known_entities.get("mtn"),
                    notes=raw.summary,
                ))
                diagnosis = {
                    "can_resolve": diag.can_resolve,
                    "root_cause": diag.root_cause,
                    "human_prompt": diag.proposed_action.human_prompt
                    if diag.proposed_action else None,
                }
            except Exception as exc:  # noqa: BLE001 - card still ships without enrichment
                logger.warning("Listen diagnose enrichment failed (%s); skipping", exc)

        suggestions.append({
            "id": f"SG-{uuid.uuid4().hex[:6].upper()}",
            "intent": raw.intent,
            "capability": INTENT_CAPABILITY[raw.intent],
            "title": raw.title,
            "summary": raw.summary,
            "prompt": _build_prompt(raw.intent, entities),
            "entities": entities,
            "confidence": raw.confidence,
            "tone": raw.tone,
            "diagnosis": diagnosis,
        })
        if len(suggestions) >= MAX_SUGGESTIONS_PER_CALL:
            break

    if suggestions:
        db.record_listen_suggestions(session_id, suggestions)

    return {"suggestions": suggestions, "entities": known_entities}


@router.post("/{session_id}/stop")
def stop(session_id: str) -> dict:
    session = db.end_listen_session(session_id)
    if not session:
        raise HTTPException(404, "Listen session not found")
    # Generate the customer-facing visit summary once, at stop, and persist it
    # so the rep-triggered send reuses it. Best-effort — a summary failure must
    # never block ending the session.
    summary = session.summary
    if summary is None:
        try:
            summary = llm.generate_visit_summary(
                session.customer_name, session.reason,
                session.transcript or [], session.suggestions or [],
                thread_id=session.thread_id, rep_id=session.rep_id,
            ).model_dump()
            db.save_listen_summary(session_id, summary)
        except Exception as exc:  # noqa: BLE001 - summary is a nicety, not required
            logger.warning("Visit summary generation failed (%s)", exc)
            summary = None

    # Grade the conversation against the active Playbook (stars + breakdown),
    # persist it, and hand it back for the rep-facing score card. Best-effort.
    grade = session.playbook_grade
    if grade is None:
        try:
            guidelines = [
                {"id": g.id, "category": g.category, "text": g.text}
                for g in db.list_playbook_guidelines(active_only=True)
            ]
            result = llm.grade_playbook(
                session.transcript or [], session.suggestions or [],
                session.eligibility or {}, guidelines,
                thread_id=session.thread_id, rep_id=session.rep_id,
            )
            grade = result.model_dump()
            db.save_listen_grade(session_id, result.stars, grade)
        except Exception as exc:  # noqa: BLE001 - grade is a nicety, not required
            logger.warning("Playbook grading failed (%s)", exc)
            grade = None

    recap = {
        "utterances": len(session.transcript or []),
        "suggestions": len(session.suggestions or []),
        "duration_label": _duration_label(session.created_at, session.ended_at or session.created_at),
        "summary": summary,
        "grade": grade,
    }
    return {"session": session, "recap": recap}


@router.post("/{session_id}/send-summary")
def send_summary(session_id: str) -> dict:
    """Email the visit summary to Live Listen subscribers (rep-triggered from
    the recap). Reuses the summary generated at stop; regenerates on demand if
    a session predates that."""
    session = db.get_listen_session(session_id)
    if not session:
        raise HTTPException(404, "Listen session not found")
    summary = session.summary
    if summary is None:
        summary = llm.generate_visit_summary(
            session.customer_name, session.reason,
            session.transcript or [], session.suggestions or [],
            thread_id=session.thread_id, rep_id=session.rep_id,
        ).model_dump()
        db.save_listen_summary(session_id, summary)
    result = email_reports.send_visit_summary(summary, session.customer_name)
    return {"summary": summary, **result}
