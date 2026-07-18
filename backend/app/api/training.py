"""Training & enablement.

- The rep-facing walkthroughs are generated at deploy time alongside the
  'What's new' enhancements (scripts/generate_enhancements.py) and served with
  each enhancement.
- This router exposes the full enhancement list (incl. walkthroughs) for the
  Settings 'Training & Enablement' section, lets the Go-To-Channel team generate
  a narration script + storyboard for any enhancement, and lets them upload a
  training video per enhancement that reps can watch from the 'What's new' card.

Uploaded videos live on disk under UPLOAD_DIR with the metadata in the DB. On
Cloud Run that disk is ephemeral (wiped on redeploy, like the demo database),
so uploads are for demo/session use, not durable storage.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import llm
from ..mcp import system_stub
from ..store import db

router = APIRouter(prefix="/api/training", tags=["training"])

UPLOAD_DIR = Path(__file__).resolve().parents[2] / "uploaded_media"
UPLOAD_DIR.mkdir(exist_ok=True)

MAX_VIDEO_BYTES = 32 * 1024 * 1024  # 32 MB — within Cloud Run's request-size limit
_ALLOWED_PREFIX = "video/"


class StoryboardRequest(BaseModel):
    title: str
    detail: str = ""
    answer: str = ""
    walkthrough: Optional[dict] = None


@router.get("/enhancements")
def list_enhancements() -> list[dict]:
    """Full enhancement records (tag, title, detail, answer, walkthrough, video)."""
    return system_stub.all_enhancements()


@router.post("/storyboard")
def storyboard(req: StoryboardRequest) -> dict:
    """Generate a training-video narration script + storyboard for one feature."""
    result = llm.generate_video_storyboard(req.title, req.detail, req.answer, req.walkthrough)
    return result.model_dump()


# --------------------------------------------------------------------------- #
# Training video upload / serve
# --------------------------------------------------------------------------- #
def _video_meta(v) -> dict:
    return {
        "id": v.id,
        "enhancement_title": v.enhancement_title,
        "original_name": v.original_name,
        "content_type": v.content_type,
        "size_bytes": v.size_bytes,
        "uploaded_at": v.uploaded_at.isoformat(),
        "url": f"/api/training/video/{v.id}",
    }


@router.get("/videos")
def list_videos() -> list[dict]:
    return [_video_meta(v) for v in db.list_enhancement_videos()]


@router.post("/video", status_code=201)
def upload_video(
    enhancement_title: str = Form(...),
    file: UploadFile = File(...),
) -> dict:
    ctype = (file.content_type or "").lower()
    if not ctype.startswith(_ALLOWED_PREFIX):
        raise HTTPException(400, "Please upload a video file.")
    if not enhancement_title.strip():
        raise HTTPException(400, "enhancement_title is required.")

    suffix = Path(file.filename or "").suffix[:10] or ".mp4"
    stored_name = f"{uuid.uuid4().hex}{suffix}"
    dest = UPLOAD_DIR / stored_name

    size = 0
    try:
        with dest.open("wb") as out:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_VIDEO_BYTES:
                    out.close()
                    dest.unlink(missing_ok=True)
                    raise HTTPException(413, f"Video exceeds the {MAX_VIDEO_BYTES // (1024 * 1024)} MB limit.")
                out.write(chunk)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        dest.unlink(missing_ok=True)
        raise HTTPException(500, f"Upload failed: {exc}") from exc

    video = db.add_enhancement_video(
        enhancement_title=enhancement_title.strip(),
        stored_name=stored_name,
        original_name=file.filename or stored_name,
        content_type=ctype,
        size_bytes=size,
    )
    return _video_meta(video)


@router.get("/video/{video_id}")
def get_video(video_id: int) -> FileResponse:
    video = db.get_enhancement_video(video_id)
    if not video:
        raise HTTPException(404, "Video not found")
    path = UPLOAD_DIR / video.stored_name
    if not path.is_file():
        raise HTTPException(404, "Video file missing")
    return FileResponse(str(path), media_type=video.content_type, filename=video.original_name)


@router.delete("/video/{video_id}", status_code=204)
def delete_video(video_id: int) -> None:
    video = db.delete_enhancement_video(video_id)
    if not video:
        raise HTTPException(404, "Video not found")
    (UPLOAD_DIR / video.stored_name).unlink(missing_ok=True)
