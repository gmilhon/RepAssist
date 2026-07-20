"""FastAPI application entrypoint for the Rep Assist orchestrator."""
from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import (
    admin, chat, coaching, cx, email_reports, huddle, insights, listen, mcp,
    metrics, playbook, production, queue, system_health, tickets, training,
)
from .api import settings as settings_api  # aliased: `settings` is the Settings instance below
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
    description="Conversational LangGraph orchestrator — Assisted Sales & Service for retail reps.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin, "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(admin.router)
app.include_router(chat.router)
app.include_router(tickets.router)
app.include_router(insights.router)
app.include_router(metrics.router)
app.include_router(cx.router)
app.include_router(email_reports.router)
app.include_router(mcp.router)
app.include_router(huddle.router)
app.include_router(system_health.router)
app.include_router(production.router)
app.include_router(queue.router)
app.include_router(listen.router)
app.include_router(playbook.router)
app.include_router(coaching.router)
app.include_router(training.router)
app.include_router(settings_api.router)


@app.on_event("startup")
def _startup() -> None:
    db.init_db()
    db.seed_playbook_defaults_if_empty()
    from .mcp import news_stub
    news_stub.seed_defaults_if_empty()


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


# Serve the built React frontend in production.
# Registered AFTER all API routes so /api/* and /health always win.
_static = Path(__file__).parent.parent / "static"
if _static.is_dir():
    # Serve JS/CSS/image assets from /assets (Vite's output dir)
    app.mount("/assets", StaticFiles(directory=str(_static / "assets")), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def _spa(path: str) -> FileResponse:
        candidate = _static / (path or "index.html")
        if candidate.is_file():
            return FileResponse(str(candidate))
        return FileResponse(str(_static / "index.html"))
