"""Rep-facing conversational endpoints."""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from ..graph import orchestrator

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatRequest(BaseModel):
    message: str
    thread_id: Optional[str] = None
    rep_id: Optional[str] = None


class ConfirmRequest(BaseModel):
    thread_id: str
    approved: bool


@router.post("")
def chat(req: ChatRequest) -> dict:
    thread_id = req.thread_id or f"thr-{uuid.uuid4().hex[:10]}"
    return orchestrator.start_or_continue(thread_id, req.message, req.rep_id)


@router.post("/confirm")
def confirm(req: ConfirmRequest) -> dict:
    return orchestrator.resume(req.thread_id, req.approved)
