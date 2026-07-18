"""Training & enablement: enhancement walkthroughs + storyboard generation.

Structural assertions only, so the cases pass whether the LLM layer is live or
in offline-mock mode.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app import llm
from app.main import app

client = TestClient(app)


def test_training_enhancements_carry_walkthroughs():
    res = client.get("/api/training/enhancements")
    assert res.status_code == 200
    items = res.json()
    assert isinstance(items, list) and len(items) >= 1
    e = items[0]
    assert e["title"] and e["detail"]
    # Every enhancement carries a walkthrough (stored or synthesized).
    wt = e["walkthrough"]
    assert wt["steps"] and all(s["title"] and s["detail"] for s in wt["steps"])


def test_storyboard_generation_shape():
    src = client.get("/api/training/enhancements").json()[0]
    res = client.post("/api/training/storyboard", json={
        "title": src["title"], "detail": src["detail"],
        "answer": src.get("answer", ""), "walkthrough": src["walkthrough"],
    })
    assert res.status_code == 200
    sb = res.json()
    assert sb["title"] and sb["audience"] and sb["total_duration_label"]
    assert len(sb["scenes"]) >= 2
    s0 = sb["scenes"][0]
    assert all(k in s0 for k in ("scene", "visual", "on_screen_text", "narration", "duration_seconds"))
    assert sb["call_to_action"]


def test_video_upload_link_serve_delete():
    title = client.get("/api/training/enhancements").json()[0]["title"]
    files = {"file": ("demo.mp4", b"\x00\x00\x00\x18ftypmp42\x00\x00", "video/mp4")}
    up = client.post("/api/training/video", data={"enhancement_title": title}, files=files)
    assert up.status_code == 201
    vid = up.json()["id"]

    # Enhancement now advertises the video url.
    enh = client.get("/api/training/enhancements").json()
    match = next(e for e in enh if e["title"] == title)
    assert match["video_url"] == f"/api/training/video/{vid}"

    # And the 'What's new' card too.
    card = client.get("/api/mcp/system-enhancements").json()["elements"][0]["enhancements"]
    assert any(e.get("video_url") == f"/api/training/video/{vid}" for e in card)

    # File is served back.
    got = client.get(f"/api/training/video/{vid}")
    assert got.status_code == 200 and got.content

    # Non-video is rejected.
    bad = client.post("/api/training/video", data={"enhancement_title": title},
                      files={"file": ("x.txt", b"hi", "text/plain")})
    assert bad.status_code == 400

    # Delete cleans up.
    assert client.delete(f"/api/training/video/{vid}").status_code == 204
    assert client.get(f"/api/training/video/{vid}").status_code == 404


def test_walkthrough_media_serving_and_safety():
    got = client.get("/api/training/walkthrough-media/live-listen.gif")
    assert got.status_code == 200
    assert got.headers["content-type"] == "image/gif" and got.content
    assert client.get("/api/training/walkthrough-media/nope.gif").status_code == 404
    # Names starting with '.' or containing separators are rejected.
    assert client.get("/api/training/walkthrough-media/.hidden").status_code == 400


def test_demo_gif_matched_to_live_listen_enhancement():
    enh = client.get("/api/training/enhancements").json()
    live_listen = [e for e in enh if "live listen" in e["title"].lower()]
    if live_listen:  # present in the committed enhancements data
        assert any((e.get("gif_url") or "").endswith("live-listen.gif") for e in live_listen)
        assert all(e.get("gif_caption") for e in live_listen if e.get("gif_url"))


def test_mock_storyboard_builds_from_walkthrough():
    wt = {"intro": "How to use it", "steps": [
        {"title": "Open the app", "detail": "Go to the chat.", "tip": None},
        {"title": "Tap the button", "detail": "Start the flow.", "tip": "It's next to Send."},
    ]}
    sb = llm._mock_storyboard("Cool Feature", "It does a cool thing.", wt)
    # Intro scene + one per step + closing scene.
    assert len(sb.scenes) == 1 + len(wt["steps"]) + 1
    assert sb.scenes[0].scene == 1
    assert sb.call_to_action
