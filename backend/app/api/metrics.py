"""Operational analytics for the solution — powers the Performance dashboard."""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Query

from ..config import get_settings
from ..llm import generate_executive_summary
from ..store import db

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


@router.get("/overview")
def overview(
    start: Optional[date] = Query(None, description="Start date YYYY-MM-DD (inclusive)"),
    end: Optional[date] = Query(None, description="End date YYYY-MM-DD (inclusive)"),
) -> dict:
    """All key KPIs filtered to the requested date range (no params = all time)."""
    return db.metrics_overview(start=start, end=end)


@router.get("/summary")
def summary(
    start: Optional[date] = Query(None, description="Start date YYYY-MM-DD (inclusive)"),
    end: Optional[date] = Query(None, description="End date YYYY-MM-DD (inclusive)"),
) -> dict:
    """AI-generated executive summary of KPIs in the requested date range."""
    overview_data = db.metrics_overview(start=start, end=end)
    gaps = db.capability_gaps(start=start, end=end)
    content = generate_executive_summary(overview_data, gaps)
    settings = get_settings()
    return {
        "generated_at": overview_data["generated_at"],
        "model": settings.anthropic_model if settings.llm_enabled else "mock",
        **content,
    }
