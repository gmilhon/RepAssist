"""FastAPI application entrypoint for the Rep Assist orchestrator."""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import chat, insights, metrics, tickets
from .config import get_settings
from .store import db

logging.basicConfig(level=logging.INFO)

settings = get_settings()
app = FastAPI(
    title="Rep Assist Orchestrator",
    version="0.1.0",
    description="Conversational LangGraph orchestrator for Verizon POS reps.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin, "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router)
app.include_router(tickets.router)
app.include_router(insights.router)
app.include_router(metrics.router)


@app.on_event("startup")
def _startup() -> None:
    db.init_db()


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "llm_mode": "anthropic" if settings.llm_enabled else "mock",
        "model": settings.anthropic_model if settings.llm_enabled else None,
        "agent_services": settings.agent_services_base_url,
        "activation_agent": settings.activation_agent_url or "mock",
        "promo_agent": settings.promo_agent_url or "mock",
    }
