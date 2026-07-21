"""District & Territory rollup dashboards for field leadership.

`/district` and `/territory` return the consolidated snapshot; the matching
`/brief` endpoints layer an AI outlier-management summary on top — same
live-Claude-with-offline-fallback pattern as the store manager brief.
"""
from __future__ import annotations

from fastapi import APIRouter

from .. import rollup_data
from ..config import get_settings
from ..llm import generate_rollup_brief

router = APIRouter(prefix="/api/rollup", tags=["rollup"])


@router.get("/district")
def district() -> dict:
    """Daily district rollup across the stores in the district (for the DM)."""
    return rollup_data.build_district_rollup()


@router.get("/district/brief")
def district_brief() -> dict:
    data = rollup_data.build_district_rollup()
    content = generate_rollup_brief(data)
    settings = get_settings()
    return {
        "generated_at": data["generated_at"],
        "level": "district",
        "model": settings.anthropic_model if settings.llm_enabled else "mock",
        **content,
    }


@router.get("/territory")
def territory() -> dict:
    """Weekly territory rollup across the districts in the territory (for the Director)."""
    return rollup_data.build_territory_rollup()


@router.get("/territory/brief")
def territory_brief() -> dict:
    data = rollup_data.build_territory_rollup()
    content = generate_rollup_brief(data)
    settings = get_settings()
    return {
        "generated_at": data["generated_at"],
        "level": "territory",
        "model": settings.anthropic_model if settings.llm_enabled else "mock",
        **content,
    }
