"""System health status — operator-configured service status + live diagnostics."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Request
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


class HealthUpdate(BaseModel):
    status: str = "operational"
    description: str = ""
    workaround: str = ""
    hard_stop: bool = False


@router.get("")
def get_status() -> dict:
    return dict(_state)


@router.post("")
def set_status(body: HealthUpdate) -> dict:
    global _state
    _state = {
        "status": body.status,
        "description": body.description,
        "workaround": body.workaround,
        "hard_stop": body.hard_stop,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _save(_state)
    return dict(_state)


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
    }
