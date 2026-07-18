"""Playbook guideline management (Settings page).

CRUD over the playbook_guidelines table. The Playbook defines the standard a
rep is graded against after a Live Listen visit — grouped into meeting customer
needs and positioning sales opportunities.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from ..store.db import _engine
from ..store.models import PlaybookGuideline

router = APIRouter(prefix="/api/playbook", tags=["playbook"])

CATEGORIES = ["Customer Needs", "Sales Positioning"]


class GuidelineIn(BaseModel):
    category: str = "Customer Needs"
    text: str


class GuidelinePatch(BaseModel):
    category: Optional[str] = None
    text: Optional[str] = None
    active: Optional[bool] = None
    sort_order: Optional[int] = None


@router.get("/guidelines")
def list_guidelines() -> list[dict]:
    with Session(_engine) as s:
        rows = s.exec(
            select(PlaybookGuideline).order_by(PlaybookGuideline.sort_order, PlaybookGuideline.id)
        ).all()
        return [r.model_dump() for r in rows]


@router.post("/guidelines", status_code=201)
def add_guideline(body: GuidelineIn) -> dict:
    if body.category not in CATEGORIES:
        raise HTTPException(400, f"category must be one of {CATEGORIES}")
    if not body.text.strip():
        raise HTTPException(400, "Guideline text is required.")
    with Session(_engine) as s:
        rows = s.exec(select(PlaybookGuideline)).all() or []
        order = 1 + max([r.sort_order for r in rows], default=-1)
        item = PlaybookGuideline(category=body.category, text=body.text.strip(), sort_order=order)
        s.add(item)
        s.commit()
        s.refresh(item)
        return item.model_dump()


@router.patch("/guidelines/{guideline_id}")
def update_guideline(guideline_id: int, body: GuidelinePatch) -> dict:
    with Session(_engine) as s:
        item = s.get(PlaybookGuideline, guideline_id)
        if not item:
            raise HTTPException(404, "Guideline not found")
        data = body.model_dump(exclude_none=True)
        if "category" in data and data["category"] not in CATEGORIES:
            raise HTTPException(400, f"category must be one of {CATEGORIES}")
        for k, v in data.items():
            setattr(item, k, v.strip() if isinstance(v, str) else v)
        s.add(item)
        s.commit()
        s.refresh(item)
        return item.model_dump()


@router.delete("/guidelines/{guideline_id}", status_code=204)
def remove_guideline(guideline_id: int) -> None:
    with Session(_engine) as s:
        item = s.get(PlaybookGuideline, guideline_id)
        if not item:
            raise HTTPException(404, "Guideline not found")
        s.delete(item)
        s.commit()
