"""Production Monitor — real-time escalation inflow + AI issue detection.

Watches the inflow of tickets the agents could not resolve (escalations to the
Resolution Desk), streams them to the Production dashboard over SSE, and runs
AI analysis (Claude, with an offline deterministic fallback) that clusters the
inflow into systemic issues:

- **critical** (order-blocking burst — payments, ETNI/number inventory,
  activation/provisioning, other backend failures) → dashboard alert card +
  email alert to alert subscribers, with problem statement and recommended fix.
- **non_critical** (recurring theme) → defect filed on the stubbed JIRA MCP
  board, detailed with the problem statement, recommended fix, and per-ticket
  examples.

Analysis runs on demand from the dashboard and automatically once enough new
escalations arrive since the last pass.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from .. import llm
from ..mcp.client import get_mcp_client
from ..store import db
from ..store.db import _engine
from ..store.models import ProductionIssue, Ticket
from .email_reports import send_production_alert

logger = logging.getLogger("repassist.production")

router = APIRouter(prefix="/api/production", tags=["production"])

# Analysis window and auto-trigger threshold
_WINDOW_HOURS = 48
_MAX_TICKETS = 80
_AUTO_ANALYZE_EVERY = 5   # new escalations since last analysis


# --------------------------------------------------------------------------- #
# SSE — live inflow + analysis events (thread-safe broadcast)
# --------------------------------------------------------------------------- #
# (queue, loop) per connected client; ticket creation happens on worker
# threads (sync graph nodes), so events hop onto each client's event loop
# via call_soon_threadsafe.
_subscribers: list[tuple[asyncio.Queue, asyncio.AbstractEventLoop]] = []


def _offer(q: asyncio.Queue, payload: str) -> None:
    try:
        q.put_nowait(payload)
    except asyncio.QueueFull:
        pass


def _broadcast(event_type: str, data: dict) -> None:
    payload = f"event: {event_type}\ndata: {json.dumps(data, default=str)}\n\n"
    for q, loop in list(_subscribers):
        try:
            loop.call_soon_threadsafe(_offer, q, payload)
        except Exception:  # noqa: BLE001 - loop closed; drop the subscriber
            try:
                _subscribers.remove((q, loop))
            except ValueError:
                pass


@router.get("/events")
async def sse_events(request: Request) -> StreamingResponse:
    queue: asyncio.Queue = asyncio.Queue(maxsize=64)
    entry = (queue, asyncio.get_running_loop())
    _subscribers.append(entry)

    async def stream() -> AsyncGenerator[str, None]:
        try:
            yield ": connected\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    yield queue.get_nowait()
                except asyncio.QueueEmpty:
                    await asyncio.sleep(0.25)
        finally:
            try:
                _subscribers.remove(entry)
            except ValueError:
                pass

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --------------------------------------------------------------------------- #
# Inflow hook — called whenever an escalation ticket is created
# --------------------------------------------------------------------------- #
_analysis_lock = threading.Lock()
_state: dict = {"last_analysis_at": None, "new_since_analysis": 0, "running": False}


def _ticket_brief(t: Ticket) -> dict:
    return {
        "id": t.id,
        "created_at": t.created_at.isoformat() if t.created_at else "",
        "intent": t.intent,
        "priority": t.priority,
        "rep_id": t.rep_id,
        "summary": t.summary,
    }


def notify_ticket_created(ticket: Ticket) -> None:
    """Broadcast a new escalation and auto-run analysis on a burst.

    Best-effort: never raises into the conversation path.
    """
    try:
        _broadcast("ticket_created", _ticket_brief(ticket))
        _state["new_since_analysis"] += 1
        if _state["new_since_analysis"] >= _AUTO_ANALYZE_EVERY and not _state["running"]:
            threading.Thread(target=_run_analysis, kwargs={"auto": True}, daemon=True).start()
    except Exception:  # noqa: BLE001
        logger.exception("notify_ticket_created failed")


# --------------------------------------------------------------------------- #
# Analysis — cluster inflow, alert criticals, file defects for the rest
# --------------------------------------------------------------------------- #
def _recent_tickets(session: Session) -> list[Ticket]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=_WINDOW_HOURS)
    rows = session.exec(
        select(Ticket).where(Ticket.created_at >= cutoff)
        .order_by(Ticket.created_at.desc()).limit(_MAX_TICKETS)
    ).all()
    return list(rows)


def _defect_description(issue: ProductionIssue, examples: list[dict]) -> str:
    lines = [
        "h2. Problem",
        issue.problem_statement,
        "",
        "h2. Recommended Fix",
        issue.recommended_fix,
        "",
        f"h2. Escalated Ticket Examples ({len(examples)})",
    ]
    for t in examples:
        lines += [
            f"* {t['id']} — {t['created_at'][:16].replace('T', ' ')} UTC — "
            f"rep {t.get('rep_id') or '—'} — priority {t['priority']} — intent {t['intent']}",
            f"  Summary: {t['summary']}",
        ]
    lines += ["", f"_Filed automatically by Rep Assist Production Monitor (issue {issue.id})._"]
    return "\n".join(lines)


def _file_defect(issue: ProductionIssue, examples: list[dict]) -> Optional[str]:
    try:
        result = get_mcp_client().call_tool("jira", "create_issue", {
            "summary": f"[Rep Assist] {issue.title}",
            "description": _defect_description(issue, examples),
            "priority": "High" if issue.order_blocking else "Medium",
            "labels": ["rep-assist", "production-monitor", issue.category],
            "issue_id": issue.id,
        })
        return result.get("key")
    except Exception:  # noqa: BLE001
        logger.exception("JIRA defect filing failed for %s", issue.id)
        return None


def _run_analysis(auto: bool = False) -> dict:
    """One analysis pass. Serialized by a lock; safe from threads."""
    if not _analysis_lock.acquire(blocking=False):
        return {"status": "already_running"}
    _state["running"] = True
    try:
        with Session(_engine) as s:
            tickets = _recent_tickets(s)
            briefs = [_ticket_brief(t) for t in tickets]
            by_id = {b["id"]: b for b in briefs}

            findings = llm.analyze_production_issues(briefs, _WINDOW_HOURS)

            now = datetime.now(timezone.utc)
            alerts: list[dict] = []
            new_defects: list[str] = []

            active = list(s.exec(
                select(ProductionIssue).where(ProductionIssue.status == "active")
            ).all())
            by_category = {i.category: i for i in active}

            for f in findings:
                examples = [by_id[tid] for tid in f["ticket_ids"] if tid in by_id]
                existing = by_category.get(f["category"])

                if existing:
                    # Update the active issue for this category in place.
                    merged = sorted(set((existing.ticket_ids or []) + f["ticket_ids"]))
                    upgraded = existing.severity != "critical" and f["severity"] == "critical"
                    existing.title = f["title"]
                    existing.severity = f["severity"]
                    existing.order_blocking = f["order_blocking"]
                    existing.problem_statement = f["problem_statement"]
                    existing.recommended_fix = f["recommended_fix"]
                    existing.ticket_ids = merged
                    existing.ticket_count = len(merged)
                    existing.updated_at = now
                    issue = existing
                else:
                    issue = ProductionIssue(
                        detected_at=now, updated_at=now,
                        severity=f["severity"], category=f["category"], title=f["title"],
                        problem_statement=f["problem_statement"],
                        recommended_fix=f["recommended_fix"],
                        order_blocking=f["order_blocking"],
                        ticket_ids=f["ticket_ids"], ticket_count=len(f["ticket_ids"]),
                    )
                    upgraded = False
                    by_category[issue.category] = issue

                # Critical → email alert, once per issue.
                if issue.severity == "critical" and (not issue.alert_sent or upgraded):
                    result = send_production_alert({
                        "id": issue.id, "title": issue.title, "category": issue.category,
                        "order_blocking": issue.order_blocking,
                        "problem_statement": issue.problem_statement,
                        "recommended_fix": issue.recommended_fix,
                        "ticket_count": issue.ticket_count,
                        "detected_at": issue.detected_at.isoformat(),
                    }, examples)
                    issue.alert_sent = result.get("sent", 0) > 0
                    alerts.append({"issue_id": issue.id, "title": issue.title, **result})

                # Non-critical recurring theme → JIRA defect, once per issue.
                if issue.severity == "non_critical" and not issue.defect_key:
                    key = _file_defect(issue, examples)
                    if key:
                        issue.defect_key = key
                        new_defects.append(key)

                s.add(issue)

            s.commit()

        _state["last_analysis_at"] = now.isoformat()
        _state["new_since_analysis"] = 0

        summary = {
            "analyzed_tickets": len(briefs),
            "window_hours": _WINDOW_HOURS,
            "issues_found": len(findings),
            "critical": sum(1 for f in findings if f["severity"] == "critical"),
            "non_critical": sum(1 for f in findings if f["severity"] == "non_critical"),
            "alerts": alerts,
            "new_defects": new_defects,
            "auto": auto,
            "last_analysis_at": _state["last_analysis_at"],
        }
        _broadcast("analysis_complete", {k: v for k, v in summary.items() if k != "alerts"})
        return summary
    finally:
        _state["running"] = False
        _analysis_lock.release()


@router.post("/analyze")
def analyze() -> dict:
    """Run an analysis pass now (the dashboard's 'Analyze now' button)."""
    return _run_analysis(auto=False)


# --------------------------------------------------------------------------- #
# Dashboard data
# --------------------------------------------------------------------------- #
def _issue_dict(i: ProductionIssue) -> dict:
    return {
        "id": i.id,
        "detected_at": i.detected_at.isoformat() if i.detected_at else None,
        "updated_at": i.updated_at.isoformat() if i.updated_at else None,
        "severity": i.severity, "category": i.category, "title": i.title,
        "problem_statement": i.problem_statement, "recommended_fix": i.recommended_fix,
        "order_blocking": i.order_blocking,
        "ticket_ids": i.ticket_ids or [], "ticket_count": i.ticket_count,
        "status": i.status, "alert_sent": i.alert_sent, "defect_key": i.defect_key,
    }


@router.get("/overview")
def overview() -> dict:
    now = datetime.now(timezone.utc)
    cutoff24 = now - timedelta(hours=24)

    with Session(_engine) as s:
        recent = s.exec(
            select(Ticket).where(Ticket.created_at >= cutoff24)
            .order_by(Ticket.created_at.desc())
        ).all()

        issues = s.exec(
            select(ProductionIssue).order_by(ProductionIssue.detected_at.desc()).limit(30)
        ).all()

    # Hourly buckets, oldest → newest (24 buckets ending this hour)
    buckets: list[dict] = []
    for h in range(23, -1, -1):
        b_start = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=h)
        b_end = b_start + timedelta(hours=1)
        count = sum(1 for t in recent if t.created_at and b_start <= _aware(t.created_at) < b_end)
        buckets.append({"hour": b_start.strftime("%H:00"), "count": count})

    last_hour = buckets[-1]["count"] if buckets else 0
    prev_hour = buckets[-2]["count"] if len(buckets) > 1 else 0

    return {
        "generated_at": now.isoformat(),
        "inflow": {
            "last_24h": len(recent),
            "last_hour": last_hour,
            "prev_hour": prev_hour,
            "buckets": buckets,
            "recent": [_ticket_brief(t) for t in recent[:12]],
        },
        "issues": [_issue_dict(i) for i in issues],
        "monitor": {
            "last_analysis_at": _state["last_analysis_at"],
            "new_since_analysis": _state["new_since_analysis"],
            "auto_analyze_every": _AUTO_ANALYZE_EVERY,
            "running": _state["running"],
            "window_hours": _WINDOW_HOURS,
        },
    }


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@router.get("/defects")
def defects() -> dict:
    """The stubbed JIRA board (defects filed by the monitor)."""
    return get_mcp_client().call_tool("jira", "list_issues", {"limit": 50})


@router.post("/issues/{issue_id}/resolve")
def resolve_issue(issue_id: str) -> dict:
    with Session(_engine) as s:
        issue = s.get(ProductionIssue, issue_id)
        if not issue:
            raise HTTPException(404, "Issue not found")
        issue.status = "resolved"
        issue.updated_at = datetime.now(timezone.utc)
        s.add(issue)
        s.commit()
        s.refresh(issue)
        result = _issue_dict(issue)
    _broadcast("issue_resolved", {"id": issue_id})
    return result


# --------------------------------------------------------------------------- #
# Demo: simulate a production incident (burst of escalations)
# --------------------------------------------------------------------------- #
_SCENARIOS: dict[str, dict] = {
    "etni": {
        "intent": "activation",
        "summaries": [
            "New line order failing — ETNI number reservation timeout (ERR-ETNI-504)",
            "Cannot assign telephone number, ETNI inventory lookup returns 500",
            "Order stuck at number selection — ETNI TN reservation failed",
            "ETNI reports 'no inventory available' but the region has numbers",
            "Number assignment spinner never completes; backend shows ETNI timeout",
            "Port-in blocked — ETNI reservation session stuck open",
            "ETNI 503 on TN lookup during upgrade with a new line",
            "Telephone number inventory service unreachable at checkout",
        ],
    },
    "payment": {
        "intent": "billing",
        "summaries": [
            "Card declined for multiple customers — gateway AUTH_5003",
            "Payment authorization timeout at checkout",
            "Every card declined since this morning — payment gateway error",
            "Checkout fails at the payment step with PROC-TIMEOUT",
            "Customer charged but the order shows payment failed",
            "Payment page spins, then 'authorization failed'",
            "Gateway 502 on payment submit for an in-store order",
            "Declined with 'processor unavailable' on a known-good card",
        ],
    },
    "activation": {
        "intent": "activation",
        "summaries": [
            "eSIM profile downloads but the line never activates",
            "Activation stuck 'in progress' for 3 hours",
            "New iPhone won't activate — provisioning error PROV-121",
            "SIM provisioned but no service after 2 hours",
            "Activation queue not moving — multiple customers waiting in store",
            "Line activation failing with a carrier API timeout",
            "Device shows active on the account but the network rejects it",
            "Provisioning job failed twice for a new line",
        ],
    },
    # Non-critical recurring theme — exercises the defect-filing path.
    "promo": {
        "intent": "promo",
        "summaries": [
            "BOGO promo credit missing from qualifying order",
            "Trade-in promo not applied at checkout",
            "Loyalty discount dropped off the current bill",
            "Summer promo code rejected for an eligible account",
        ],
    },
}

_SIM_REPS = ["rep.alvarez", "rep.chen", "rep.patel", "rep.okafor", "rep.santos", "rep.kim"]


class SimulateBody(BaseModel):
    scenario: str = "etni"


@router.post("/simulate", status_code=201)
def simulate_incident(body: SimulateBody) -> dict:
    """DEMO — inject a burst of escalated tickets for one failure scenario so
    the real-time inflow, analysis, alerting and defect flow can be exercised
    without driving dozens of chat conversations."""
    scenario = _SCENARIOS.get(body.scenario)
    if not scenario:
        raise HTTPException(400, f"Unknown scenario. Use one of: {', '.join(_SCENARIOS)}")

    now = datetime.now(timezone.utc)
    created: list[dict] = []
    for i, summary in enumerate(scenario["summaries"]):
        ts = now - timedelta(minutes=random.uniform(1, 25))
        rep = random.choice(_SIM_REPS)
        thread = f"sim-{uuid.uuid4().hex[:8]}"
        ticket = db.create_ticket(
            created_at=ts, updated_at=ts,
            rep_id=rep, thread_id=thread,
            intent=scenario["intent"], priority="high",
            summary=summary,
            conversation=[{"role": "user", "content": summary}],
        )
        db.record_engagement(
            created_at=ts, thread_id=thread, rep_id=rep, kind="message",
            intent=scenario["intent"], confidence=0.4, status="escalated",
            resolution_status="escalated", capability="human-tier-2",
            ticket_id=ticket.id,
        )
        created.append(_ticket_brief(ticket))
        notify_ticket_created(ticket)

    return {"scenario": body.scenario, "created": len(created), "tickets": created}
