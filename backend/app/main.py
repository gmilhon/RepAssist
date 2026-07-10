"""FastAPI application entrypoint for the Rep Assist orchestrator."""
from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import chat, cx, insights, metrics, tickets
from .config import get_settings
from .store import db

logging.basicConfig(level=logging.INFO)

settings = get_settings()

# Enable LangSmith auto-tracing for all LangGraph runs when a key is configured.
# These env vars are read by the LangChain/LangGraph internals at import time, so
# we set them before any graph code runs (i.e. before the first /chat request).
if settings.langsmith_enabled:
    os.environ.setdefault("LANGCHAIN_TRACING_V2",  "true")
    os.environ.setdefault("LANGCHAIN_API_KEY",      settings.langsmith_api_key)
    os.environ.setdefault("LANGCHAIN_PROJECT",      settings.langsmith_project)

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
app.include_router(cx.router)


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
        "langsmith": {
            "enabled": settings.langsmith_enabled,
            "project": settings.langsmith_project if settings.langsmith_enabled else None,
        },
    }
