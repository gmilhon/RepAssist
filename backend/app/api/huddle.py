"""Morning Huddle item management (Settings page).

CRUD over the huddle_items table that the 'news' MCP stub serves. Article ids
are validated against the OST knowledge base when provided.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from ..mcp import get_mcp_client
from ..store.db import _engine
from ..store.models import HuddleItem

router = APIRouter(prefix="/api/huddle", tags=["huddle"])

CATEGORIES = ["To-Do", "Promo", "Device", "Policy", "Network", "News"]


class HuddleIn(BaseModel):
    category: str = "News"
    title: str
    blurb: str = ""
    article_id: Optional[str] = None


class HuddlePatch(BaseModel):
    category: Optional[str] = None
    title: Optional[str] = None
    blurb: Optional[str] = None
    article_id: Optional[str] = None
    active: Optional[bool] = None
    sort_order: Optional[int] = None


def _valid_article(article_id: Optional[str]) -> Optional[str]:
    """Return the normalized id if it resolves in OST, else raise."""
    if not article_id:
        return None
    aid = article_id.strip().upper()
    res = get_mcp_client().call_tool("ost", "get_article", {"article_id": aid})
    if not res.get("elements"):
        raise HTTPException(400, f"Unknown OST article: {aid}")
    return aid


@router.get("/items")
def list_items() -> list[dict]:
    with Session(_engine) as s:
        rows = s.exec(select(HuddleItem).order_by(HuddleItem.sort_order, HuddleItem.id)).all()
        return [r.model_dump() for r in rows]


@router.get("/articles")
def list_articles() -> list[dict]:
    """OST articles available to link (id, title, category) for the picker."""
    res = get_mcp_client().call_tool("ost", "search_articles", {"query": ""})  # noqa: F841
    # search with empty query returns nothing; enumerate via get_article ids instead.
    from ..mcp import ost_stub
    return [
        {"article_id": a["article_id"], "title": a["title"], "category": a["category"]}
        for a in ost_stub._ARTICLES.values()
    ]


@router.post("/items", status_code=201)
def add_item(body: HuddleIn) -> dict:
    if body.category not in CATEGORIES:
        raise HTTPException(400, f"category must be one of {CATEGORIES}")
    aid = _valid_article(body.article_id)
    with Session(_engine) as s:
        nxt = (s.exec(select(HuddleItem)).all() or [])
        order = 1 + max([r.sort_order for r in nxt], default=-1)
        item = HuddleItem(category=body.category, title=body.title.strip(),
                          blurb=body.blurb.strip(), article_id=aid, sort_order=order)
        s.add(item)
        s.commit()
        s.refresh(item)
        return item.model_dump()


@router.patch("/items/{item_id}")
def update_item(item_id: int, body: HuddlePatch) -> dict:
    with Session(_engine) as s:
        item = s.get(HuddleItem, item_id)
        if not item:
            raise HTTPException(404, "Huddle item not found")
        data = body.model_dump(exclude_none=True)
        if "category" in data and data["category"] not in CATEGORIES:
            raise HTTPException(400, f"category must be one of {CATEGORIES}")
        if "article_id" in data:
            data["article_id"] = _valid_article(data["article_id"])
        for k, v in data.items():
            setattr(item, k, v)
        s.add(item)
        s.commit()
        s.refresh(item)
        return item.model_dump()


@router.delete("/items/{item_id}", status_code=204)
def remove_item(item_id: int) -> None:
    with Session(_engine) as s:
        item = s.get(HuddleItem, item_id)
        if not item:
            raise HTTPException(404, "Huddle item not found")
        s.delete(item)
        s.commit()
