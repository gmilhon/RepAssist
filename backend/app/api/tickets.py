"""Tier 1/2 human-in-the-loop ticket workflow (replaces ServiceNow).

Also hosts the AI Assisted Resolution Desk: a rep-triggered Analyze pass buckets
the open/in_review backlog into education / agent_action / system_defect (see
llm.classify_resolution_tickets), and a one-click action per bucket resolves the
ticket — sharing an OST article, calling the existing resolver agent, or filing
a JIRA-stub defect for the dev team.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import llm
from ..integrations import agents_client
from ..mcp.client import get_mcp_client
from ..schemas import INTENT_TO_CAPABILITY, DiagnoseRequest, Intent
from ..store import db
from ..store.models import GapType, Ticket

logger = logging.getLogger("repassist.tickets")

router = APIRouter(prefix="/api/tickets", tags=["tickets"])

# Intents with a real automated resolver behind agents_client.diagnose/execute —
# the only ones the "agent_action" bucket / Call agent action may act on.
ALLOWED_AGENT_INTENTS = {"activation", "pending_order", "promo", "occ"}


class ClaimRequest(BaseModel):
    agent: str


class ResolveRequest(BaseModel):
    resolution_notes: str
    root_cause_category: str
    # The capability/agent/skill the dev team should build or improve so the
    # assistant can handle this class of issue next time.
    recommended_capability: str
    gap_type: str  # see store.models.GapType
    resolved_by: str
    close_only: bool = False  # True = closed with no capability gap to build


@router.get("")
def list_tickets(status: Optional[str] = None) -> list[Ticket]:
    return db.list_tickets(status)


@router.get("/{ticket_id}")
def get_ticket(ticket_id: str) -> Ticket:
    ticket = db.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    return ticket


@router.post("/{ticket_id}/claim")
def claim(ticket_id: str, req: ClaimRequest) -> Ticket:
    ticket = db.claim_ticket(ticket_id, req.agent)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    return ticket


@router.post("/{ticket_id}/resolve")
def resolve(ticket_id: str, req: ResolveRequest) -> Ticket:
    ticket = db.resolve_ticket(
        ticket_id,
        resolution_notes=req.resolution_notes,
        root_cause_category=req.root_cause_category,
        recommended_capability=req.recommended_capability,
        gap_type=req.gap_type,
        resolved_by=req.resolved_by,
        close_only=req.close_only,
    )
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    return ticket


# --------------------------------------------------------------------------- #
# AI Assisted Resolution Desk
# --------------------------------------------------------------------------- #
class AnalyzeRequest(BaseModel):
    status: str = "open"


class AnalyzeResult(BaseModel):
    analyzed: int
    education: int
    agent_action: int
    system_defect: int
    tickets: list[Ticket]


@router.post("/analyze")
def analyze_backlog(req: AnalyzeRequest) -> AnalyzeResult:
    """Bucket the given status's backlog into education / agent_action / system_defect."""
    tickets = db.list_tickets(req.status)
    if not tickets:
        return AnalyzeResult(analyzed=0, education=0, agent_action=0, system_defect=0, tickets=[])

    briefs = [{"id": t.id, "intent": t.intent, "priority": t.priority, "summary": t.summary} for t in tickets]
    classifications = llm.classify_resolution_tickets(briefs)
    by_id = {c["ticket_id"]: c for c in classifications}

    counts = {"education": 0, "agent_action": 0, "system_defect": 0}
    now = datetime.now(timezone.utc)
    updated: list[Ticket] = []
    for ticket in tickets:
        c = by_id.get(ticket.id)
        if not c:
            continue
        category = c["category"]
        article_id = article_title = capability = None

        if category == "education":
            try:
                result = get_mcp_client().call_tool("ost", "search_articles", {"query": ticket.summary})
                elements = result.get("elements") or []
                if elements:
                    article_id = elements[0]["article_id"]
                    article_title = elements[0]["title"]
            except Exception:  # noqa: BLE001 - OST lookup is best-effort
                logger.exception("OST article lookup failed for %s", ticket.id)
        elif category == "agent_action":
            capability = INTENT_TO_CAPABILITY.get(Intent(ticket.intent), "human-tier-2")

        counts[category] += 1
        saved = db.set_ticket_ai_classification(
            ticket.id,
            category=category,
            reasoning=c["reasoning"],
            article_id=article_id,
            article_title=article_title,
            capability=capability,
            analyzed_at=now,
        )
        if saved:
            updated.append(saved)

    return AnalyzeResult(analyzed=len(updated), tickets=updated, **counts)


class ResolveEducationRequest(BaseModel):
    article_id: str
    resolved_by: str
    notes: Optional[str] = None


@router.post("/{ticket_id}/resolve-education")
def resolve_education(ticket_id: str, req: ResolveEducationRequest) -> Ticket:
    """Education bucket action: share the (AI-suggested or manually picked) OST article and close."""
    ticket = db.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")

    title = req.article_id
    try:
        result = get_mcp_client().call_tool("ost", "get_article", {"article_id": req.article_id})
        elements = result.get("elements") or []
        if elements:
            title = elements[0]["title"]
    except Exception:  # noqa: BLE001 - title lookup is best-effort
        logger.exception("OST article lookup failed for %s", req.article_id)

    notes = f"Shared OST article {req.article_id} — {title}."
    if req.notes:
        notes += f" {req.notes}"

    updated = db.resolve_ticket(
        ticket_id,
        resolution_notes=notes,
        root_cause_category="customer_education",
        recommended_capability="",
        gap_type=GapType.NONE.value,
        resolved_by=req.resolved_by,
        close_only=True,
    )
    if not updated:
        raise HTTPException(404, "Ticket not found")
    return updated


class CallAgentRequest(BaseModel):
    resolved_by: str


class CallAgentResult(BaseModel):
    resolved: bool
    ticket: Ticket
    diagnosis: dict


@router.post("/{ticket_id}/call-agent")
def call_agent(ticket_id: str, req: CallAgentRequest) -> CallAgentResult:
    """Agent_action bucket action: run the existing diagnose→execute path for this
    ticket's intent and resolve it in one click on success (same two calls the
    live chat's resolver nodes make — see graph/nodes._run_resolver / confirm)."""
    ticket = db.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    if ticket.intent not in ALLOWED_AGENT_INTENTS:
        raise HTTPException(400, f"No automated resolver for intent '{ticket.intent}'")

    intent = Intent(ticket.intent)
    diag = agents_client.diagnose(
        intent, DiagnoseRequest(order_id=ticket.order_id, account_id=ticket.account_id)
    )
    if not diag.can_resolve or not diag.proposed_action:
        return CallAgentResult(
            resolved=False, ticket=ticket,
            diagnosis={"root_cause": diag.root_cause, "summary": diag.summary},
        )

    exec_result = agents_client.execute(diag.proposed_action)
    if not exec_result.success:
        return CallAgentResult(
            resolved=False, ticket=ticket,
            diagnosis={"root_cause": diag.root_cause, "summary": exec_result.summary},
        )

    capability = INTENT_TO_CAPABILITY.get(intent, "human-tier-2")
    updated = db.resolve_ticket(
        ticket_id,
        resolution_notes=f"Auto-resolved via {capability}: {exec_result.summary}",
        root_cause_category=diag.root_cause or "",
        recommended_capability="",
        gap_type=GapType.NONE.value,
        resolved_by=req.resolved_by,
        close_only=True,
    )
    if not updated:
        raise HTTPException(404, "Ticket not found")
    return CallAgentResult(
        resolved=True, ticket=updated,
        diagnosis={
            "root_cause": diag.root_cause,
            "summary": exec_result.summary,
            "actions_taken": exec_result.actions_taken,
        },
    )


@router.get("/{ticket_id}/candidate-defects")
def candidate_defects(ticket_id: str) -> dict:
    """System_defect bucket helper: open defects that plausibly match this ticket
    (same intent label), so the rep can attach instead of filing a duplicate."""
    ticket = db.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    result = get_mcp_client().call_tool("jira", "list_issues", {"limit": 50})
    issues = result.get("issues") or []
    matches = [
        i for i in issues
        if i.get("status") == "Open" and ticket.intent in (i.get("labels") or [])
    ][:5]
    return {"issues": matches}


class FileDefectRequest(BaseModel):
    resolved_by: str
    gap_type: str = "missing_agent"  # missing_agent | agent_failed | bad_data
    attach_to: Optional[str] = None  # existing defect key; omit to file a new one
    recommended_capability: Optional[str] = None


class FileDefectResult(BaseModel):
    ticket: Ticket
    defect_key: str


def _defect_description(ticket: Ticket) -> str:
    return (
        "h2. Problem\n"
        f"{ticket.summary}\n\n"
        "h2. AI classification reasoning\n"
        f"{ticket.ai_reasoning or '—'}\n\n"
        "h2. Ticket\n"
        f"{ticket.id} — intent {ticket.intent}, priority {ticket.priority}, rep {ticket.rep_id or '—'}\n\n"
        f"_Filed from the Resolution Desk (ticket {ticket.id})._"
    )


@router.post("/{ticket_id}/file-defect")
def file_defect(ticket_id: str, req: FileDefectRequest) -> FileDefectResult:
    """System_defect bucket action: attach to an existing JIRA-stub defect or file
    a new one, then resolve the ticket with the capability gap this represents."""
    ticket = db.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")

    if req.attach_to:
        result = get_mcp_client().call_tool(
            "jira", "attach_ticket",
            {"key": req.attach_to, "ticket_id": ticket.id, "note": ticket.summary},
        )
        if result.get("error"):
            raise HTTPException(404, f"Defect {req.attach_to} not found")
        key = req.attach_to
        notes = f"Attached to existing defect {key}"
    else:
        result = get_mcp_client().call_tool("jira", "create_issue", {
            "summary": f"[Resolution Desk] {ticket.summary[:120]}",
            "description": _defect_description(ticket),
            "priority": "High" if ticket.priority == "high" else "Medium",
            "labels": ["rep-assist", "resolution-desk", ticket.intent],
            "ticket_ids": [ticket.id],
        })
        key = result["key"]
        notes = f"Filed defect {key}"

    capability = req.recommended_capability
    if not capability:
        try:
            capability = INTENT_TO_CAPABILITY.get(Intent(ticket.intent), "unspecified")
        except ValueError:
            capability = "unspecified"

    updated = db.resolve_ticket(
        ticket_id,
        resolution_notes=notes,
        root_cause_category=ticket.ai_reasoning or "system defect",
        recommended_capability=capability,
        gap_type=req.gap_type,
        resolved_by=req.resolved_by,
        close_only=False,
    )
    if not updated:
        raise HTTPException(404, "Ticket not found")
    return FileDefectResult(ticket=updated, defect_key=key)
