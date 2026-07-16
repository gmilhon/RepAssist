"""System health status — operator-configured service status + live diagnostics."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

router = APIRouter(prefix="/api/system-health", tags=["system-health"])

_STATE_FILE = Path("./system_health.json")

_DEFAULT: dict = {
    "status": "operational",   # operational | degraded | outage
    "description": "",
    "workaround": "",
    "hard_stop": False,
    "updated_at": None,
}


def _load() -> dict:
    try:
        if _STATE_FILE.exists():
            return {**_DEFAULT, **json.loads(_STATE_FILE.read_text())}
    except Exception:
        pass
    return dict(_DEFAULT)


def _save(state: dict) -> None:
    try:
        _STATE_FILE.write_text(json.dumps(state, default=str))
    except Exception:
        pass


_state: dict = _load()

# SSE subscriber queues — one asyncio.Queue per connected client
_subscribers: list[asyncio.Queue] = []


def _broadcast(event_type: str, data: dict) -> None:
    payload = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
    dead: list[asyncio.Queue] = []
    for q in _subscribers:
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        try:
            _subscribers.remove(q)
        except ValueError:
            pass


class HealthUpdate(BaseModel):
    status: str = "operational"
    description: str = ""
    workaround: str = ""
    hard_stop: bool = False
    notify: bool = False


@router.get("")
def get_status() -> dict:
    return dict(_state)


@router.post("")
async def set_status(body: HealthUpdate) -> dict:
    global _state
    _state = {
        "status": body.status,
        "description": body.description,
        "workaround": body.workaround,
        "hard_stop": body.hard_stop,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _save(_state)
    if body.notify:
        _broadcast("health_update", dict(_state))
    return dict(_state)


def maybe_auto_degrade(reason: str) -> bool:
    """Auto-flag the service degraded on a sustained LLM fallback spike (see
    docs/16-observability.md). Called from `llm._log_usage()`, not exposed
    as an endpoint.

    Only acts when the current status is exactly "operational" — never
    overwrites a status an admin set manually (a real outage, or a degraded
    state for an unrelated reason). No auto-recovery by design: once flagged,
    an admin clears it from Settings like any other incident, so a transient
    dip doesn't flap the badge back and forth.
    """
    global _state
    if _state.get("status") != "operational":
        return False
    _state = {
        "status": "degraded",
        "description": f"[Auto] {reason}",
        "workaround": "Check ANTHROPIC_API_KEY validity and Anthropic API status. "
                       "Clear this from Settings once resolved.",
        "hard_stop": False,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _save(_state)
    _broadcast("health_update", dict(_state))
    return True


@router.get("/events")
async def sse_events(request: Request) -> StreamingResponse:
    queue: asyncio.Queue = asyncio.Queue(maxsize=32)
    _subscribers.append(queue)

    async def stream() -> AsyncGenerator[str, None]:
        try:
            yield ": connected\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = queue.get_nowait()
                    yield msg
                except asyncio.QueueEmpty:
                    await asyncio.sleep(0.25)
        finally:
            try:
                _subscribers.remove(queue)
            except ValueError:
                pass

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/ping")
def ping(request: Request) -> dict:
    forwarded = request.headers.get("x-forwarded-for", "")
    client_ip = (
        forwarded.split(",")[0].strip()
        if forwarded
        else (request.client.host if request.client else "unknown")
    )
    return {
        "ok": True,
        "server_ts": datetime.now(timezone.utc).isoformat(),
        "client_ip": client_ip,
        "region": "us-central",
    }


_REGION_LABELS = {
    "east":    "us-east",
    "central": "us-central",
    "west":    "us-west",
}


@router.get("/ping/{region}")
def ping_region(region: str, request: Request) -> dict:
    if region not in _REGION_LABELS:
        raise HTTPException(status_code=404, detail="Unknown region")
    forwarded = request.headers.get("x-forwarded-for", "")
    client_ip = (
        forwarded.split(",")[0].strip()
        if forwarded
        else (request.client.host if request.client else "unknown")
    )
    return {
        "ok": True,
        "server_ts": datetime.now(timezone.utc).isoformat(),
        "client_ip": client_ip,
        "region": _REGION_LABELS[region],
    }
