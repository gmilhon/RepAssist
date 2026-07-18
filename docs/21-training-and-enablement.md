# Training & Enablement

Every capability this app ships is only useful if a rep knows how to use it. The
Training & Enablement surface keeps rep education in lockstep with what actually
shipped, and gives the Go-To-Channel team the tools to produce richer training
material on top of it. It has two audiences:

- **Reps** get a hands-on **walkthrough** for every enhancement — auto-generated
  at deploy time next to the "What's new" card — and can watch a **training
  video** for a feature right from that card.
- **The Go-To-Channel team** (Settings → Training & Enablement) can generate a
  narration script + **storyboard** for any feature to feed an AI video tool, and
  **upload** the finished training video per enhancement.

It builds on the git-log-driven "What's new" pipeline
([doc 15](15-system-enhancements-generation.md)): a walkthrough is just another
field on each generated enhancement, so a rep's how-to is always in sync with the
commit that shipped the feature, with no hand-maintenance.

---

## 1. Rep walkthroughs

Each entry in the "What's new in Rep Assist" card carries a `walkthrough`: a
short intro plus **3–6 ordered steps** (`title`, `detail`, optional `tip`) a rep
follows in the app to use the feature. Reps reach it in the chat under
**Briefings → System enhancements**, expanding an enhancement to see its steps.

Walkthroughs are **generated with the enhancements**, not separately.
`scripts/generate_enhancements.py` runs at deploy time, feeds the git commit log
to `llm.generate_system_enhancements()`, and writes each `EnhancementItem`
— walkthrough included — to `app/mcp/enhancements_data.json`, which is committed
to git so it ships inside the image ([doc 15](15-system-enhancements-generation.md)).
For any older record that predates walkthrough generation,
`system_stub._ensure_walkthrough()` synthesizes a minimal one on read, so the UI
never has to handle a missing walkthrough.

## 2. Storyboard generator

For a fuller training video, the Go-To-Channel team taps **🎬 Generate
storyboard** on any enhancement in Settings. `POST /api/training/storyboard`
runs `llm.generate_video_storyboard()` over the feature's title, detail, answer,
and walkthrough and returns a `VideoStoryboard` ready to feed an AI video tool:

| Field | Meaning |
|---|---|
| `title` / `audience` / `total_duration_label` | Video framing (e.g. *Retail sales reps · 1m 20s*) |
| `scenes[]` | Ordered scenes: `visual`, `on_screen_text`, `narration`, `duration_seconds` |
| `call_to_action` | Closing on-screen next step |

The rendered storyboard has a **Copy script** button. Generation is
**offline-safe**: with no `ANTHROPIC_API_KEY` it builds a deterministic
storyboard from the walkthrough steps, and every call is logged to the
`llm_calls` token ledger ([doc 16](16-observability.md)) as function
`storyboard`.

## 3. Training video upload & playback

Once a video exists, the team uploads it against an enhancement (**⬆ Upload
training video**). The file streams to disk under `backend/uploaded_media/`,
with a metadata row in `enhancement_videos`; the enhancement's **What's new**
card then shows a ▶ video the rep can play. Uploading is validated on the way in
(`video/*` content type, **32 MB** cap streamed and checked chunk-by-chunk) and
a video can be removed again from Settings.

---

## Architecture

```
DEPLOY TIME
  ./deploy.sh ──► scripts/generate_enhancements.py
                    └─ git log ──► llm.generate_system_enhancements()
                                     └─ EnhancementItem.walkthrough (3-6 steps)
                                     └─ enhancements_data.json  (committed to git)

REP (chat)  Briefings → System enhancements ──► `system_enhancements` A2UI card
                    └─ walkthrough steps (expand)
                    └─ ▶ training video (system_stub._video_url_for → latest upload)

GO-TO-CHANNEL (Settings → Training & Enablement)
  GET  /api/training/enhancements ──► list (tag, title, detail, answer, walkthrough, video_url)
  🎬 Generate storyboard ──► POST /api/training/storyboard ──► llm.generate_video_storyboard() → VideoStoryboard
  ⬆ Upload training video ──► POST /api/training/video (multipart) ──► uploaded_media/<uuid> + enhancement_videos row
  ✕ Remove ──────────────► DELETE /api/training/video/{id}
```

### Why these choices

- **Why walkthroughs ride along with the enhancements.** The "What's new" card
  is already regenerated from the git log on every deploy
  ([doc 15](15-system-enhancements-generation.md)); making the walkthrough a
  field on each `EnhancementItem` means a rep's how-to is generated from the same
  commits that shipped the feature — always current, never hand-maintained, and
  never out of step with the release.
- **Why the storyboard is a separate, on-demand step.** A full narration script
  is a heavier artifact aimed at producing an actual video, so it's generated per
  feature only when the team asks — and it's seeded from that feature's real
  walkthrough, so the script stays grounded in the steps reps actually take.
- **Why videos are linked to an enhancement by title.** The enhancement list is
  regenerated from git each deploy and has no durable per-enhancement id, so
  `enhancement_title` is the closest stable key. `latest_video_for_title()`
  resolves the current video for a card. It's a deliberate tradeoff — renaming an
  enhancement's title would orphan its video.
- **Why ephemeral storage is acceptable here.** `uploaded_media/` lives on Cloud
  Run's container disk, which is wiped on every redeploy exactly like the demo
  database ([doc 17](17-reseeding-deployed-data.md)). Uploads are for
  demo/session use, not durable storage; a production build would put them in
  object storage (GCS/S3) and serve via signed URLs.
- **Never trust the upload.** The handler checks the `video/*` content-type
  prefix, caps the size at 32 MB (within Cloud Run's request-size limit) by
  counting bytes as it streams — deleting the partial file if the cap is
  exceeded — and stores under a generated `uuid` filename, never the client's.

---

## API

| Method & path | Purpose |
|---|---|
| `GET /api/training/enhancements` | Full enhancement records (`tag`, `title`, `detail`, `answer`, `walkthrough`, `video_url`) for the Settings Training list |
| `POST /api/training/storyboard` | Generate a narration script + storyboard — `{title, detail, answer, walkthrough?}` → `VideoStoryboard` |
| `GET /api/training/videos` | List uploaded training-video metadata |
| `POST /api/training/video` | Upload a video (multipart `enhancement_title` + `file`); 400 non-video, 413 over 32 MB |
| `GET /api/training/video/{id}` | Stream a stored video |
| `DELETE /api/training/video/{id}` | Delete the video file + metadata row |

Code: [`backend/app/api/training.py`](../backend/app/api/training.py),
[`backend/app/mcp/system_stub.py`](../backend/app/mcp/system_stub.py)
(`all_enhancements`, `_ensure_walkthrough`, `_video_url_for`),
[`backend/app/llm.py`](../backend/app/llm.py) (`generate_video_storyboard`),
[`backend/scripts/generate_enhancements.py`](../backend/scripts/generate_enhancements.py).

---

## Data model

| Table | Purpose |
|---|---|
| `enhancement_videos` | One row per uploaded training video: `enhancement_title` (link key), `stored_name` (on-disk uuid filename), `original_name`, `content_type`, `size_bytes`, `uploaded_at`. The file lives on disk; this row is the metadata |

Walkthroughs are **not** a table — they are a field on each generated
enhancement in `enhancements_data.json` (see the `Walkthrough` /
`WalkthroughStep` schemas in [`schemas.py`](../backend/app/schemas.py)).

---

## Frontend

| File | Role |
|---|---|
| `frontend/src/components/SettingsPage.tsx` | The **Training & Enablement** section: per-enhancement storyboard generate/copy, and the video upload / preview / remove controls |
| `frontend/src/components/ChatWidget.tsx` | Renders an enhancement's walkthrough steps and the ▶ training video on the "What's new" card |
| `frontend/src/components/A2UI.tsx` | `SystemEnhancementsCard` — the `system_enhancements` element carrying walkthrough + `video_url` |
| `frontend/src/api.ts` / `types.ts` | `trainingEnhancements`, `generateStoryboard`, `uploadEnhancementVideo`, `deleteEnhancementVideo`; `VideoStoryboard`, `Walkthrough`, `TrainingEnhancement` |

---

## Known limitations & future work

- **Ephemeral storage.** Uploaded videos do not survive a redeploy on Cloud Run.
  Move to object storage (GCS/S3) + signed URLs for durability.
- **Title-linked videos.** Renaming an enhancement orphans its video; a durable
  per-enhancement id would remove the coupling.
- **No transcode / thumbnailing.** The file is served back as-is; there's no
  format normalization, poster-frame extraction, or captions pipeline.
- **Storyboard is text only.** It produces a script + shot list for a human/AI
  video tool — it does not render a video itself.
