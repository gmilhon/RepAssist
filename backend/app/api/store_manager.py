"""Store Manager dashboard — daily operating picture for a store lead.

`/overview` returns the full synthetic-but-coherent snapshot (staffing, traffic
forecast, sales performance, operations). `/brief` layers an AI-generated daily
brief on top of that same snapshot, mirroring the Performance dashboard's
executive-summary pattern (live Claude call with an offline-safe fallback).
"""
from __future__ import annotations

from fastapi import APIRouter

from .. import store_manager_data
from ..config import get_settings
from ..llm import generate_store_manager_brief

router = APIRouter(prefix="/api/store-manager", tags=["store-manager"])


@router.get("/overview")
def overview() -> dict:
    """Full store snapshot for right now — staffing, traffic, sales, operations."""
    return store_manager_data.build_overview()


@router.get("/brief")
def brief() -> dict:
    """AI-generated daily brief summarizing the current store snapshot."""
    data = store_manager_data.build_overview()
    content = generate_store_manager_brief(data)
    settings = get_settings()
    return {
        "generated_at": data["generated_at"],
        "as_of_label": data["as_of_label"],
        "model": settings.anthropic_model if settings.llm_enabled else "mock",
        **content,
    }
