"""Email reports — subscriber management and on-demand report sending.

Subscribers are stored in SQLite. Reports are sent via SMTP when configured;
when SMTP is not set up the endpoint returns a preview of the HTML that would
be sent so the UI can show it immediately without needing credentials.
"""
from __future__ import annotations

import smtplib
import ssl
from datetime import date, datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Literal, Optional

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, EmailStr
from sqlmodel import Session, select

from ..config import get_settings
from ..store.db import _engine
from ..store.models import EmailSubscriber

router = APIRouter(prefix="/api/email", tags=["email"])

ReportType = Literal["performance", "cx"]


# --------------------------------------------------------------------------- #
# Subscriber CRUD
# --------------------------------------------------------------------------- #
class SubscriberIn(BaseModel):
    email: EmailStr
    name: Optional[str] = None
    subscribed_performance: bool = True
    subscribed_cx: bool = True


class SubscriberPatch(BaseModel):
    name: Optional[str] = None
    subscribed_performance: Optional[bool] = None
    subscribed_cx: Optional[bool] = None
    active: Optional[bool] = None


def _all_subscribers() -> list[EmailSubscriber]:
    with Session(_engine) as s:
        return list(s.exec(select(EmailSubscriber).order_by(EmailSubscriber.created_at)).all())


@router.get("/subscribers")
def list_subscribers() -> list[dict]:
    return [s.model_dump() for s in _all_subscribers()]


@router.post("/subscribers", status_code=201)
def add_subscriber(body: SubscriberIn) -> dict:
    with Session(_engine) as s:
        existing = s.exec(select(EmailSubscriber).where(EmailSubscriber.email == body.email)).first()
        if existing:
            # Re-activate if previously removed
            existing.active = True
            existing.name = body.name or existing.name
            existing.subscribed_performance = body.subscribed_performance
            existing.subscribed_cx = body.subscribed_cx
            s.add(existing)
            s.commit()
            s.refresh(existing)
            return existing.model_dump()
        sub = EmailSubscriber(**body.model_dump())
        s.add(sub)
        s.commit()
        s.refresh(sub)
        return sub.model_dump()


@router.patch("/subscribers/{email}")
def update_subscriber(email: str, body: SubscriberPatch) -> dict:
    with Session(_engine) as s:
        sub = s.exec(select(EmailSubscriber).where(EmailSubscriber.email == email)).first()
        if not sub:
            raise HTTPException(404, "Subscriber not found")
        for field, val in body.model_dump(exclude_none=True).items():
            setattr(sub, field, val)
        s.add(sub)
        s.commit()
        s.refresh(sub)
        return sub.model_dump()


@router.delete("/subscribers/{email}", status_code=204)
def remove_subscriber(email: str) -> None:
    with Session(_engine) as s:
        sub = s.exec(select(EmailSubscriber).where(EmailSubscriber.email == email)).first()
        if not sub:
            raise HTTPException(404, "Subscriber not found")
        sub.active = False
        s.add(sub)
        s.commit()


# --------------------------------------------------------------------------- #
# HTML report templates
# --------------------------------------------------------------------------- #
_BRAND = "#ee0000"
_DARK  = "#0b0b0b"
_MUTED = "#6b7280"
_LINE  = "#e5e7eb"
_BG    = "#f4f5f7"


def _card(label: str, value: str, sub: str = "") -> str:
    return f"""
    <td style="padding:12px 10px; text-align:center; background:#fff;
               border:1px solid {_LINE}; border-radius:10px; width:16%;">
      <div style="font-size:10px; font-weight:700; text-transform:uppercase;
                  letter-spacing:0.5px; color:{_MUTED}; margin-bottom:4px;">{label}</div>
      <div style="font-size:22px; font-weight:800; color:{_DARK}; line-height:1;">{value}</div>
      {f'<div style="font-size:11px; color:{_MUTED}; margin-top:3px;">{sub}</div>' if sub else ""}
    </td>"""


def _header(title: str, period: str) -> str:
    return f"""
    <tr>
      <td style="background:{_DARK}; padding:20px 28px;">
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr>
            <td>
              <span style="background:{_BRAND}; color:#fff; font-weight:800; font-size:14px;
                           padding:4px 8px; border-radius:5px; margin-right:10px;">✓</span>
              <span style="color:#fff; font-size:18px; font-weight:800;">Rep Assist</span>
              <span style="color:#9ca3af; font-size:12px; margin-left:8px;">
                Verizon POS · {title}
              </span>
            </td>
            <td align="right">
              <span style="color:#9ca3af; font-size:12px;">{period}</span>
            </td>
          </tr>
        </table>
      </td>
    </tr>"""


def _footer() -> str:
    return f"""
    <tr>
      <td style="padding:20px 28px; color:{_MUTED}; font-size:11px; border-top:1px solid {_LINE};">
        Generated by Rep Assist · {datetime.now(timezone.utc).strftime("%-d %b %Y, %H:%M UTC")} ·
        Manage subscriptions in the Rep Assist Settings tab.
      </td>
    </tr>"""


def _wrap(rows: str) -> str:
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    </head>
    <body style="margin:0; padding:24px; background:{_BG};
                 font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
      <table width="640" cellpadding="0" cellspacing="0"
             style="margin:0 auto; background:#fff; border-radius:12px;
                    overflow:hidden; border:1px solid {_LINE};">
        {rows}
      </table>
    </body></html>"""


def build_performance_html(overview: dict, period: str) -> str:
    e   = overview.get("engagement", {})
    out = overview.get("outcomes", {})
    con = overview.get("confirmations", {})
    intents = overview.get("intents", [])

    kpi_row = f"""
    <tr>
      <td style="padding:24px 28px 0;">
        <table width="100%" cellpadding="4" cellspacing="6">
          <tr>
            {_card("Conversations", str(e.get("conversations", 0)))}
            {_card("Containment", f"{round(out.get('containment_rate',0)*100)}%",
                   f"{out.get('auto_resolved',0)} resolved")}
            {_card("Escalation Rate", f"{round(out.get('escalation_rate',0)*100)}%",
                   f"{out.get('escalated',0)} tickets")}
            {_card("Avg Confidence", f"{round(e.get('avg_confidence',0)*100)}%")}
            {_card("Approval Rate", f"{round(con.get('approval_rate',0)*100)}%",
                   f"{con.get('approved',0)} approved")}
            {_card("Active Reps", str(e.get("active_reps", 0)))}
          </tr>
        </table>
      </td>
    </tr>"""

    intent_rows = "".join(
        f"""<tr style="border-bottom:1px solid {_LINE};">
          <td style="padding:7px 0; font-size:13px;">{r['intent'].replace('_',' ').title()}</td>
          <td style="padding:7px 0; font-size:13px; text-align:right;">{r['count']}</td>
          <td style="padding:7px 0; font-size:13px; text-align:right;
                     color:{'#0a7d33' if r['auto_resolved']/max(r['count'],1) > 0.5 else _BRAND};">
            {round(r['auto_resolved']/max(r['count'],1)*100)}%
          </td>
          <td style="padding:7px 0; font-size:13px; text-align:right; color:{_MUTED};">
            {round(r.get('avg_confidence',0)*100)}%
          </td>
        </tr>"""
        for r in intents[:8]
    )

    intents_section = f"""
    <tr><td style="padding:24px 28px 0;">
      <div style="font-size:11px; font-weight:700; text-transform:uppercase;
                  letter-spacing:0.5px; color:{_MUTED}; margin-bottom:10px;">Volume by Intent</div>
      <table width="100%" cellpadding="0" cellspacing="0">
        <tr style="border-bottom:2px solid {_LINE};">
          <th style="text-align:left; font-size:11px; padding-bottom:6px; color:{_MUTED};">Intent</th>
          <th style="text-align:right; font-size:11px; padding-bottom:6px; color:{_MUTED};">Count</th>
          <th style="text-align:right; font-size:11px; padding-bottom:6px; color:{_MUTED};">Containment</th>
          <th style="text-align:right; font-size:11px; padding-bottom:6px; color:{_MUTED};">Confidence</th>
        </tr>
        {intent_rows}
      </table>
    </td></tr>"""

    rows = _header("Performance Report", period) + kpi_row + intents_section + _footer()
    return _wrap(rows)


def build_cx_html(cx: dict, period: str) -> str:
    ov  = cx.get("overview", {})
    lat = cx.get("latency_ms", {})
    tok = cx.get("tokens", {})
    cost = cx.get("cost_usd", {})

    def fms(ms: int) -> str:
        return f"{ms/1000:.1f}s" if ms >= 1000 else f"{ms}ms"

    err_rate = f"{ov.get('error_rate', 0) * 100:.2f}%"

    kpi_row = f"""
    <tr>
      <td style="padding:24px 28px 0;">
        <table width="100%" cellpadding="4" cellspacing="6">
          <tr>
            {_card("Conversations", str(ov.get("conversations", 0)),
                   f"{ov.get('traces_captured',0)} traced")}
            {_card("P50 Latency", fms(lat.get("p50", 0)),
                   f"P95: {fms(lat.get('p95', 0))}")}
            {_card("P99 Latency", fms(lat.get("p99", 0)),
                   f"avg: {fms(lat.get('avg', 0))}")}
            {_card("Error Rate", err_rate,
                   f"{ov.get('error_count', 0)} errors")}
            {_card("Avg Tokens", str(tok.get("avg_total", 0)),
                   f"in: {tok.get('avg_input',0)} / out: {tok.get('avg_output',0)}")}
            {_card("Avg Cost", f"${cost.get('avg_per_conversation', 0):.4f}",
                   f"total: ${cost.get('total', 0):.2f}")}
          </tr>
        </table>
      </td>
    </tr>"""

    configured_note = (
        f'<span style="color:#0a7d33; font-weight:700;">● Live</span> '
        f'project: {cx.get("langsmith_project")}'
        if cx.get("configured") else
        f'<span style="color:#b25f00; font-weight:700;">● Sample data</span> '
        f'(configure LANGCHAIN_API_KEY for live traces)'
    )

    note_row = f"""
    <tr><td style="padding:16px 28px 24px; font-size:12px; color:{_MUTED};">
      LangSmith: {configured_note} · model: {cost.get("model", "—")}
    </td></tr>"""

    rows = _header("CX Monitor Report", period) + kpi_row + note_row + _footer()
    return _wrap(rows)


# --------------------------------------------------------------------------- #
# Send report
# --------------------------------------------------------------------------- #
class SendReportBody(BaseModel):
    report_type: ReportType
    start: Optional[date] = None
    end: Optional[date] = None


def _fetch_performance(start: Optional[date], end: Optional[date]) -> tuple[dict, str]:
    params: dict = {}
    if start: params["start"] = start.isoformat()
    if end:   params["end"]   = end.isoformat()
    r = httpx.get("http://localhost:8000/api/metrics/overview", params=params, timeout=15.0)
    r.raise_for_status()
    data = r.json()
    s = start.isoformat() if start else "YTD"
    e = end.isoformat()   if end   else date.today().isoformat()
    return data, f"{s} – {e}"


def _fetch_cx(start: Optional[date], end: Optional[date]) -> tuple[dict, str]:
    params: dict = {}
    if start: params["start"] = start.isoformat()
    if end:   params["end"]   = end.isoformat()
    r = httpx.get("http://localhost:8000/api/cx/overview", params=params, timeout=15.0)
    r.raise_for_status()
    data = r.json()
    p = data.get("period", {})
    s = p.get("start") or (start.isoformat() if start else "YTD")
    e = p.get("end")   or (end.isoformat()   if end   else date.today().isoformat())
    return data, f"{s} – {e}"


def _send_smtp(subject: str, html: str, recipients: list[str], settings) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = settings.smtp_from_addr
    msg["To"]      = ", ".join(recipients)
    msg.attach(MIMEText(html, "html"))

    ctx = ssl.create_default_context()
    if settings.smtp_tls:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.ehlo()
            server.starttls(context=ctx)
            server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(settings.smtp_from_addr, recipients, msg.as_string())
    else:
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, context=ctx) as server:
            server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(settings.smtp_from_addr, recipients, msg.as_string())


@router.post("/send-report")
def send_report(body: SendReportBody) -> dict:
    settings = get_settings()

    # Fetch data and build HTML
    try:
        if body.report_type == "performance":
            data, period = _fetch_performance(body.start, body.end)
            html    = build_performance_html(data, period)
            subject = f"Rep Assist Performance Report · {period}"
            sub_field = "subscribed_performance"
        else:
            data, period = _fetch_cx(body.start, body.end)
            html    = build_cx_html(data, period)
            subject = f"Rep Assist CX Monitor Report · {period}"
            sub_field = "subscribed_cx"
    except Exception as exc:
        raise HTTPException(500, f"Failed to fetch report data: {exc}") from exc

    # Collect active subscribers for this report type
    with Session(_engine) as s:
        subs = list(s.exec(
            select(EmailSubscriber)
            .where(EmailSubscriber.active == True)  # noqa: E712
            .where(getattr(EmailSubscriber, sub_field) == True)  # noqa: E712
        ).all())

    recipients = [s.email for s in subs]

    if not recipients:
        return {
            "sent": 0,
            "previewed": False,
            "recipients": [],
            "preview_html": html,
            "warning": "No active subscribers for this report type. Add subscribers in Settings.",
        }

    if not settings.smtp_enabled:
        return {
            "sent": 0,
            "previewed": True,
            "recipients": recipients,
            "preview_html": html,
            "warning": "SMTP not configured — showing preview. Add SMTP settings to backend/.env to send real email.",
        }

    try:
        _send_smtp(subject, html, recipients, settings)
        return {"sent": len(recipients), "previewed": False, "recipients": recipients}
    except Exception as exc:
        return {
            "sent": 0,
            "previewed": True,
            "recipients": recipients,
            "preview_html": html,
            "error": str(exc),
        }


@router.get("/settings")
def email_settings() -> dict:
    s = get_settings()
    return {
        "smtp_enabled": s.smtp_enabled,
        "smtp_host":    s.smtp_host or None,
        "smtp_port":    s.smtp_port,
        "smtp_user":    s.smtp_user or None,
        "smtp_tls":     s.smtp_tls,
    }
