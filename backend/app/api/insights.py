"""Continuous-improvement analytics: turns Tier 1/2 feedback into a ranked
backlog of agents/skills the dev team should build or fix next.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Query

from ..store import db

router = APIRouter(prefix="/api/insights", tags=["insights"])


@router.get("/capability-gaps")
def capability_gaps(
    start: Optional[date] = Query(None, description="Start date YYYY-MM-DD (inclusive)"),
    end: Optional[date] = Query(None, description="End date YYYY-MM-DD (inclusive)"),
) -> dict:
    gaps = db.capability_gaps(start=start, end=end)
    return {
        "generated_from_resolved_tickets": True,
        "count": len(gaps),
        "gaps": gaps,
    }
