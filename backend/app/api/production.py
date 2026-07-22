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
from sqlalchemy import func
from sqlmodel import Session, select

from .. import llm
from .. import production_geo_data as geo
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

# The map's red/yellow/green health compares each region's current 24h volume to
# a day-of-week-aligned baseline: the average of the SAME rolling-24h window over
# the previous BASELINE_WEEKS weeks. Aligning on day-of-week means a naturally
# busy weekday (or a quiet Sunday) reads as normal — only an abnormal spike
# versus recent same-days lights the region up.
BASELINE_WEEKS = 4


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
    st = geo.store(t.store_id)
    return {
        "id": t.id,
        "created_at": t.created_at.isoformat() if t.created_at else "",
        "intent": t.intent,
        "priority": t.priority,
        "rep_id": t.rep_id,
        "summary": t.summary,
        # Production Monitor dimensions (captured at escalation time)
        "cloud_env": t.cloud_env,
        "channel": t.channel,
        "channel_label": geo.CHANNEL_LABEL.get(t.channel or "", t.channel),
        "store_id": t.store_id,
        "store_name": st["name"] if st else None,
        "city": st["city"] if st else None,
        "state": st["state"] if st else None,
        "lat": st["lat"] if st else None,
        "lng": st["lng"] if st else None,
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


def _impact_line(issue: ProductionIssue) -> str:
    """Compact one-line impact summary for alerts/defects."""
    chans = ", ".join(geo.CHANNEL_LABEL.get(c, c) for c in (issue.channels or [])) or "—"
    clouds = ", ".join(
        geo.CLOUD_REGIONS[c]["label"] for c in (issue.clouds or []) if c in geo.CLOUD_REGIONS
    ) or "—"
    n = issue.store_count or 0
    return (
        f"{geo.PRIORITY_LABEL.get(issue.priority_level, issue.priority_level)} · "
        f"channels: {chans} · cloud: {clouds} · {n} store{'' if n == 1 else 's'}"
    )


def _defect_description(issue: ProductionIssue, examples: list[dict]) -> str:
    lines = [
        "h2. Problem",
        issue.problem_statement,
        "",
        "h2. Impact",
        _impact_line(issue),
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

            processed_priorities: list[str] = []
            for f in findings:
                examples = [by_id[tid] for tid in f["ticket_ids"] if tid in by_id]
                order_blocking = bool(f.get("order_blocking"))
                workaround = bool(f.get("workaround_available"))

                # Aggregate this cluster's impact from its member tickets — the
                # channels/clouds/stores actually reported, not the model's guess.
                chans = {e["channel"] for e in examples if e.get("channel")}
                clouds = {e["cloud_env"] for e in examples if e.get("cloud_env")}
                store_ids = {e["store_id"] for e in examples if e.get("store_id")}

                existing = by_category.get(f["category"])
                if existing:
                    # Update the active issue for this category in place; its
                    # impact only widens, so accumulate the aggregates + tickets.
                    issue = existing
                    issue.ticket_ids = sorted(set((existing.ticket_ids or []) + f["ticket_ids"]))
                    issue.ticket_count = len(issue.ticket_ids)
                    issue.updated_at = now
                    chans |= set(existing.channels or [])
                    clouds |= set(existing.clouds or [])
                    store_ids |= set(existing.store_ids or [])
                else:
                    issue = ProductionIssue(
                        detected_at=now, updated_at=now, category=f["category"],
                        ticket_ids=f["ticket_ids"], ticket_count=len(f["ticket_ids"]),
                    )
                    by_category[issue.category] = issue

                # P-level from the aggregated breadth; severity (alert vs. defect)
                # follows from it.
                priority = geo.compute_priority_level(
                    len(chans), len(store_ids), order_blocking, workaround
                )
                severity = geo.severity_for_priority(priority)
                upgraded = issue.severity != "critical" and severity == "critical"

                issue.title = f["title"]
                issue.severity = severity
                issue.priority_level = priority
                issue.order_blocking = order_blocking
                issue.workaround_available = workaround
                issue.problem_statement = f["problem_statement"]
                issue.recommended_fix = f["recommended_fix"]
                issue.channels = sorted(chans)
                issue.clouds = sorted(clouds)
                issue.store_ids = sorted(store_ids)
                issue.store_count = len(store_ids)
                processed_priorities.append(priority)

                # Critical (P1/P2, sales-blocking) → email alert, once per issue.
                if issue.severity == "critical" and (not issue.alert_sent or upgraded):
                    result = send_production_alert({
                        "id": issue.id, "title": issue.title, "category": issue.category,
                        "order_blocking": issue.order_blocking,
                        "priority_level": issue.priority_level,
                        "problem_statement": issue.problem_statement,
                        "recommended_fix": issue.recommended_fix,
                        "ticket_count": issue.ticket_count,
                        "impact": _impact_line(issue),
                        "detected_at": issue.detected_at.isoformat(),
                    }, examples)
                    issue.alert_sent = result.get("sent", 0) > 0
                    alerts.append({"issue_id": issue.id, "title": issue.title, **result})

                # Non-critical (P3/P4) recurring theme → JIRA defect, once per issue.
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
            "critical": sum(1 for p in processed_priorities if p in ("P1", "P2")),
            "non_critical": sum(1 for p in processed_priorities if p in ("P3", "P4")),
            "by_priority": {p: processed_priorities.count(p) for p in ("P1", "P2", "P3", "P4")},
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
        "severity": i.severity,
        "priority_level": i.priority_level,
        "priority_label": geo.PRIORITY_LABEL.get(i.priority_level, i.priority_level),
        "category": i.category, "title": i.title,
        "problem_statement": i.problem_statement, "recommended_fix": i.recommended_fix,
        "order_blocking": i.order_blocking,
        "workaround_available": i.workaround_available,
        "channels": i.channels or [],
        "channel_labels": [geo.CHANNEL_LABEL.get(c, c) for c in (i.channels or [])],
        "clouds": i.clouds or [],
        "cloud_labels": [
            geo.CLOUD_REGIONS[c]["label"] for c in (i.clouds or []) if c in geo.CLOUD_REGIONS
        ],
        "store_ids": i.store_ids or [], "store_count": i.store_count,
        "ticket_ids": i.ticket_ids or [], "ticket_count": i.ticket_count,
        "status": i.status, "alert_sent": i.alert_sent, "defect_key": i.defect_key,
    }


def _build_geo(recent: list[Ticket], baselines: dict[str, float]) -> dict:
    """Aggregate the in-window escalation inflow by store, cloud region and
    channel for the impact map. `baselines` maps a cloud region to its expected
    in-window volume (trailing daily average) so health reads relative to normal."""
    store_counts: dict[str, int] = {}
    channel_counts: dict[str, int] = {c: 0 for c in geo.CHANNELS}
    cloud_counts: dict[str, int] = {c: 0 for c in geo.CLOUD_REGIONS}

    for t in recent:
        if t.store_id and t.store_id in geo.STORE_BY_ID:
            store_counts[t.store_id] = store_counts.get(t.store_id, 0) + 1
        if t.channel in channel_counts:
            channel_counts[t.channel] += 1
        if t.cloud_env in cloud_counts:
            cloud_counts[t.cloud_env] += 1

    stores = []
    for sid, count in sorted(store_counts.items(), key=lambda kv: -kv[1]):
        st = geo.STORE_BY_ID[sid]
        stores.append({
            "id": sid, "name": st["name"], "city": st["city"], "state": st["state"],
            "lat": st["lat"], "lng": st["lng"],
            "channel": st["channel"], "channel_label": geo.CHANNEL_LABEL[st["channel"]],
            "cloud": st["cloud"], "count": count,
        })

    clouds = []
    for cid, region in geo.CLOUD_REGIONS.items():
        count = cloud_counts.get(cid, 0)
        baseline = baselines.get(cid, 0.0)
        region_stores = [sid for sid in store_counts if geo.STORE_BY_ID[sid]["cloud"] == cid]
        region_channels = sorted({geo.STORE_BY_ID[sid]["channel"] for sid in region_stores})
        clouds.append({
            "id": cid, "label": region["label"], "aws_region": region["aws_region"],
            "site": region["site"], "lat": region["lat"], "lng": region["lng"],
            "count": count, "baseline": round(baseline, 1),
            "status": geo.cloud_status(count, baseline),
            "store_count": len(region_stores),
            "channels": region_channels,
            "channel_labels": [geo.CHANNEL_LABEL[c] for c in region_channels],
        })

    return {
        "stores": stores,
        "clouds": clouds,
        "channels": [
            {"channel": c, "label": geo.CHANNEL_LABEL[c], "count": channel_counts[c]}
            for c in geo.CHANNELS
        ],
        "unique_stores": len(store_counts),
        "channels_impacted": sum(1 for c in geo.CHANNELS if channel_counts[c] > 0),
        "thresholds": {
            "model": "relative",
            "yellow_ratio": geo.CLOUD_YELLOW_RATIO,
            "red_ratio": geo.CLOUD_RED_RATIO,
            "min_baseline": geo.CLOUD_MIN_BASELINE,
            "baseline_weeks": BASELINE_WEEKS,
        },
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

        # DOW-aligned baseline: the same rolling-24h window over each of the
        # previous BASELINE_WEEKS weeks, averaged per region. Same weekday +
        # time-of-day as "now", so normal weekly rhythm reads as normal.
        week_counts: dict[str, list[int]] = {cid: [] for cid in geo.CLOUD_REGIONS}
        for w in range(1, BASELINE_WEEKS + 1):
            w_end = now - timedelta(days=7 * w)
            w_start = w_end - timedelta(hours=24)
            rows = s.exec(
                select(Ticket.cloud_env, func.count()).where(
                    Ticket.created_at >= w_start, Ticket.created_at < w_end
                ).group_by(Ticket.cloud_env)
            ).all()
            rc = {cid: n for cid, n in rows if cid}
            for cid in geo.CLOUD_REGIONS:
                week_counts[cid].append(rc.get(cid, 0))
    baselines = {cid: (sum(v) / len(v) if v else 0.0) for cid, v in week_counts.items()}

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
        "geo": _build_geo(list(recent), baselines),
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
# Each scenario spreads its burst across a chosen set of channels and cloud
# regions so the impact map + P-level light up believably:
#   etni     → AWS East only, 2 channels, sales-blocking          → P2
#   payment  → both clouds, all 4 channels, sales-blocking        → P1
#   activation → both clouds, 2 channels, sales-blocking          → P2
#   billing  → both clouds, 3 channels, not blocking, no workaround → P3
#   promo    → both clouds, 2 channels, not blocking, workaround  → P4
_SCENARIOS: dict[str, dict] = {
    "etni": {
        "intent": "activation",
        "count": 8,
        "channels": ["retail", "indirect"],
        "clouds": ["aws_east"],
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
        "count": 14,
        "channels": list(geo.CHANNELS),
        "clouds": ["aws_east", "aws_west"],
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
        "count": 10,
        "channels": ["retail", "d2d"],
        "clouds": ["aws_east", "aws_west"],
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
    # Non-blocking, no clean workaround, spread across locations → P3.
    "billing": {
        "intent": "billing",
        "count": 8,
        "channels": ["retail", "indirect", "inside_sales"],
        "clouds": ["aws_east", "aws_west"],
        "summaries": [
            "First bill much higher than quoted — unexpected proration",
            "Autopay credit missing from this cycle's bill",
            "Duplicate charge on the current bill for one line",
            "Proration on a mid-cycle plan change looks wrong",
            "Overcharge dispute — taxes and fees don't match the quote",
            "Bill shows a charge for a feature the customer removed",
        ],
    },
    # Non-blocking recurring theme with a workaround — defect-filing path → P4.
    "promo": {
        "intent": "promo",
        "count": 6,
        "channels": ["retail", "indirect"],
        "clouds": ["aws_east", "aws_west"],
        "summaries": [
            "BOGO promo credit missing from qualifying order",
            "Trade-in promo not applied at checkout",
            "Loyalty discount dropped off the current bill",
            "Summer promo code rejected for an eligible account",
        ],
    },
}

_SIM_REPS = ["rep.alvarez", "rep.chen", "rep.patel", "rep.okafor", "rep.santos", "rep.kim"]


def _pick_incident_stores(channels: list[str], clouds: list[str], count: int) -> list[dict]:
    """Round-robin across (cloud × channel) pools so a simulated incident spreads
    evenly across the requested clouds and channels (guaranteeing each appears)."""
    pools = [geo.stores_matching([ch], [cl]) for cl in clouds for ch in channels]
    pools = [p for p in pools if p]
    if not pools:
        return list(geo.STORES[:count])
    picks: list[dict] = []
    idx = 0
    while len(picks) < count:
        picks.append(random.choice(pools[idx % len(pools)]))
        idx += 1
    return picks


class SimulateBody(BaseModel):
    scenario: str = "etni"


@router.post("/simulate", status_code=201)
def simulate_incident(body: SimulateBody) -> dict:
    """DEMO — inject a burst of escalated tickets for one failure scenario so
    the real-time inflow, analysis, alerting and defect flow can be exercised
    without driving dozens of chat conversations. Each ticket carries a cloud /
    store / channel so the impact map and P-level render realistically."""
    scenario = _SCENARIOS.get(body.scenario)
    if not scenario:
        raise HTTPException(400, f"Unknown scenario. Use one of: {', '.join(_SCENARIOS)}")

    now = datetime.now(timezone.utc)
    summaries = scenario["summaries"]
    count = scenario.get("count", len(summaries))
    stores = _pick_incident_stores(scenario["channels"], scenario["clouds"], count)
    created: list[dict] = []
    for i in range(count):
        st = stores[i] if i < len(stores) else random.choice(geo.STORES)
        summary = summaries[i % len(summaries)]
        ts = now - timedelta(minutes=random.uniform(1, 25))
        rep = random.choice(_SIM_REPS)
        thread = f"sim-{uuid.uuid4().hex[:8]}"
        ticket = db.create_ticket(
            created_at=ts, updated_at=ts,
            rep_id=rep, thread_id=thread,
            intent=scenario["intent"], priority="high",
            summary=summary,
            conversation=[{"role": "user", "content": summary}],
            cloud_env=st["cloud"], store_id=st["id"], channel=st["channel"],
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
