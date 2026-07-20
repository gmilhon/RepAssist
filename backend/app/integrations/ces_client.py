"""Relay client for the external Google CX Agent Studio (CES) `repAssist` agent.

The orchestrator's `ces_remote` node calls `run_turn()` to relay one rep turn to
the CES multi-agent telecom app and read its reply back. The proven method is
CES `runSession` (v1beta) — verified end-to-end against the live `repAssist`
deployment (root "Telecommunications Steering agent" + 8 domain sub-agents). The
whole call is hidden behind this module, so switching `runSession` → the A2A
`message:send` method later (if/when Google enables inbound A2A for the
deployment) is a ~10-line internal change with zero orchestrator impact.

Offline by design — the same fallback pattern as `agents_client._stub_*`:
with `CES_STUB=true`, no deployment, or any error reaching the live API, this
returns a deterministic in-process stub reply, so the node, the per-intent
routing and the Settings toggle are fully testable without GCP credentials.
Set `CES_DEPLOYMENT` to enable the feature; set `CES_STUB=false` (plus a Cloud
Run service account granted a CES-invoke role) to hit the real API.

Governance: this is an ADVISORY relay — it never executes writes. If CES's
Payments/Disconnect sub-agents are later allowed to mutate, route those through
the existing `interrupt()` + `record_action_audit` gate, exactly like the
built-in resolvers.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from ..config import Settings, get_settings

logger = logging.getLogger("repassist.ces")

_HOST = "https://ces.googleapis.com/v1beta"
_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]

# The CES `repAssist` app's domain sub-agents (verified live). Used as the
# optional per-intent `entryAgent` a manager can pick in Settings, and to shape
# the offline stub reply so toggling entry agents visibly changes the response.
CES_ENTRY_AGENTS = [
    "Accounts", "Billing", "Technical Support", "Usage",
    "Plans", "Disconnect", "Equipment", "Payments",
]

# Short, plausible opening lines per sub-agent, so the offline stub reads like
# the real steering agent handing off to a domain specialist.
_STUB_OPENERS = {
    "Accounts": "I can help with the account. Let me confirm the account holder and current status.",
    "Billing": "I can look into that billing question — let me review the recent charges on the account.",
    "Technical Support": "Let's get this working. I'll walk through a couple of quick diagnostics with you.",
    "Usage": "I can break down the usage on this line for the current cycle.",
    "Plans": "Happy to review the plan options — let me check what this line is eligible for.",
    "Disconnect": "I can help with that request. Let me confirm the details before we proceed.",
    "Equipment": "Let's sort out the equipment. I'll check the device and any pending swaps.",
    "Payments": "I can help with a payment. Let me pull up the balance and payment options.",
}


def enabled() -> bool:
    """True when a CES deployment is configured — gates per-intent routing."""
    return get_settings().ces_enabled


@dataclass
class CesTurn:
    """One relayed turn's result. `raw` is the untouched API body (or the stub
    payload) so callers/traces can inspect diagnostics; `stubbed` marks the
    offline path."""

    text: str
    turn_completed: bool = True
    raw: dict = field(default_factory=dict)
    stubbed: bool = False


def run_turn(session_id: str, text: str, entry_agent: Optional[str] = None) -> CesTurn:
    """Relay one turn to CES and return its reply. Never raises — on any failure
    reaching the live API it falls back to the deterministic stub so the chat is
    never broken by an external dependency."""
    s = get_settings()
    if s.ces_stub or not s.ces_deployment:
        return _stub_run_turn(session_id, text, entry_agent)
    try:
        return _live_run_turn(s, session_id, text, entry_agent)
    except Exception as exc:  # noqa: BLE001 - degrade to the stub, never crash the chat
        logger.warning("CES runSession unavailable (%s) — using in-process stub", exc)
        return _stub_run_turn(session_id, text, entry_agent)


# --------------------------------------------------------------------------- #
# Live path — the proven runSession call (v1beta). httpx/google-auth are
# imported lazily so the offline/stub path needs neither installed.
# --------------------------------------------------------------------------- #
def _live_run_turn(s: Settings, session_id: str, text: str, entry_agent: Optional[str]) -> CesTurn:
    import httpx

    app = s.ces_deployment.split("/deployments/")[0]        # projects/…/apps/{app}
    session = f"{app}/sessions/{session_id}"
    cfg: dict = {"session": session, "deployment": s.ces_deployment}
    if s.ces_app_version:
        cfg["appVersion"] = s.ces_app_version
    if entry_agent:
        cfg["entryAgent"] = entry_agent

    resp = httpx.post(
        f"{_HOST}/{session}:runSession",
        headers={
            "Authorization": f"Bearer {_bearer()}",
            "x-goog-request-params": f"location=locations/{s.ces_location}",
        },
        json={"config": cfg, "inputs": [{"text": text}]},
        timeout=httpx.Timeout(30.0),
    )
    resp.raise_for_status()
    body = resp.json()
    out = (body.get("outputs") or [{}])[0]
    return CesTurn(
        text=out.get("text", ""),
        turn_completed=bool(out.get("turnCompleted", True)),
        raw=body,
    )


def _bearer() -> str:
    """ADC bearer token (the Cloud Run service account in production)."""
    import google.auth
    import google.auth.transport.requests

    creds, _ = google.auth.default(scopes=_SCOPES)
    creds.refresh(google.auth.transport.requests.Request())
    return creds.token


# --------------------------------------------------------------------------- #
# Offline stub — mirrors the live steering agent's style (verified 2026-07-20:
# greets, hands off to a domain sub-agent, asks one focused follow-up).
# Deterministic so unit/e2e tests can assert on it.
# --------------------------------------------------------------------------- #
def _stub_run_turn(session_id: str, text: str, entry_agent: Optional[str]) -> CesTurn:
    opener = _STUB_OPENERS.get(
        entry_agent or "",
        "Thanks for the details — let me help you with that.",
    )
    label = entry_agent or "Telecommunications Steering"
    reply = (
        f"[CES · repAssist · {label} agent] {opener} "
        "Could you confirm the mobile number or the last 4 digits of the account "
        "so I can apply this to the right line?"
    )
    return CesTurn(
        text=reply,
        turn_completed=False,  # steering agent is mid-conversation (asking a follow-up)
        raw={"stub": True, "session": session_id, "entry_agent": entry_agent},
        stubbed=True,
    )
