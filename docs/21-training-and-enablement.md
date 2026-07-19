# Training & Enablement

Every capability this app ships is only useful if a rep knows how to use it. The
Training & Enablement surface keeps rep education in lockstep with what actually
shipped, and gives the Go-To-Channel team the tools to produce richer training
material on top of it. It has two audiences:

- **Reps** open a single **"Show me how"** on any enhancement in the "What's new"
  card and get, in one card: a hands-on **step-by-step walkthrough** (auto-generated
  at deploy time), an **animated GIF demo** of the flow when one is available, and
  the uploaded **training video** if the team has attached one.
- **The Go-To-Channel team** (Settings → Training & Enablement) can **hide** any
  enhancement from the rep-facing "What's new" card, generate a narration script +
  **storyboard** for any feature to feed an AI video tool, and **upload** the
  finished training video per enhancement.

It builds on the git-log-driven "What's new" pipeline
([doc 15](15-system-enhancements-generation.md)): a walkthrough is just another
field on each generated enhancement, so a rep's how-to is always in sync with the
commit that shipped the feature, with no hand-maintenance.

---

## 1. "Show me how" — one card, three layers

Tapping **📖 Show me how** on an enhancement (chat → Briefings → System
enhancements) opens one walkthrough card composed of up to three parts, in order:

1. **Steps** — the generated `walkthrough`: a short intro plus **3–6 ordered
   steps** (`title`, `detail`, optional `tip`) the rep follows in the app.
2. **🎞 Quick demo** — a short, silent, looping **animated GIF** of the real app
   performing the flow, with a one-line caption. Shown only when a GIF is matched
   to that enhancement (see §2).
3. **▶ Training video** — the video the Go-To-Channel team uploaded for that
   feature, if any (see §4).

The button hints at what's inside: a `🎞` appears when a demo GIF is available and
a `▶` when a video is attached. Any layer can be absent — an enhancement with only
steps still opens a clean card.

### Walkthrough steps
Walkthroughs are **generated with the enhancements**, not separately.
`scripts/generate_enhancements.py` runs at deploy time, feeds the git commit log
to `llm.generate_system_enhancements()`, and writes each `EnhancementItem`
— walkthrough included — to `app/mcp/enhancements_data.json`, which is committed
to git so it ships inside the image ([doc 15](15-system-enhancements-generation.md)).
For any older record that predates walkthrough generation,
`system_stub._ensure_walkthrough()` synthesizes a minimal one on read, so the UI
never has to handle a missing walkthrough.

## 2. Animated GIF demos

A headless deploy can't drive a browser, so demo GIFs are **authored ahead of
time** (drive the running app with Playwright, capture frames, assemble with
ffmpeg into a small looping GIF) and **committed** under
`backend/app/mcp/walkthrough_media/`. They ship in the image — unlike uploaded
videos, they are durable and survive redeploys.

A GIF is matched to an enhancement by a manifest,
`walkthrough_media/walkthrough_media.json`:

```json
{ "media": [
  { "gif": "live-listen.gif",
    "caption": "Start a Live Listen, watch suggestions appear, then stop to see your Playbook score.",
    "match": ["live listen", "playbook", "coaching", "docked transcript"] }
] }
```

At serve time `system_stub._gif_for(enhancement)` lowercases the enhancement's
**title** (not its keywords — a keyword like "playbook" listed under an unrelated
feature would otherwise pull in the wrong GIF) and attaches the first manifest
entry whose `match` term is a substring **and** whose `.gif` file actually exists
on disk. That existence check means adding a manifest row before the GIF is
captured is harmless — nothing is advertised until the file is present.

The committed GIFs today cover the flagship flows (Live Listen end-to-end; the
check-in queue with eligibility badges); enhancements without a matching GIF simply
show steps (+ video). To add one, capture a new GIF, drop it in
`walkthrough_media/`, and add a manifest entry.

## 3. Storyboard generator

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

## 4. Training video upload & playback

Once a video exists, the team uploads it against an enhancement (**⬆ Upload
training video**). The file streams to disk under `backend/uploaded_media/`,
with a metadata row in `enhancement_videos`; the enhancement's **What's new**
card then plays it **inside the "Show me how" card** (§1, layer 3). Uploading is
validated on the way in (`video/*` content type, **32 MB** cap streamed and
checked chunk-by-chunk) and a video can be removed again from Settings.

## 5. Hiding an enhancement from reps

Not every shipped change belongs in the rep-facing feed. Each row in Settings →
Training & Enablement carries a **Shown / Hidden** toggle so the Go-To-Channel team
can pull an enhancement out of the chat's "What's new" card without deleting it.

- Clicking the toggle calls `POST /api/training/enhancements/hide` with
  `{title, hidden}` (`SettingsPage.toggleHidden` → `api.setEnhancementHidden`); the
  row flips optimistically and rolls back if the call fails.
- A hidden row is **dimmed** (`train-item--hidden`) and gets a **"Hidden from reps"**
  badge, but the team still sees it in full — hiding controls rep visibility, it is
  not a delete.
- Server-side the two reads share one set: `get_system_enhancements` (the rep-facing
  `system_enhancements` card) drops any enhancement whose title is in
  `db.hidden_enhancement_titles()`, while `all_enhancements()` (the Settings list)
  keeps every row and tags each with a `hidden: bool`. Because both subtract the same
  set, the Settings toggle and the rep card can't drift.
- Visibility is keyed by **enhancement title** — the same stable key uploaded videos
  use — and persisted via `db.set_enhancement_hidden(title, hidden)`, which is
  idempotent: hiding inserts a `hidden_enhancements` row, showing deletes it.

---

## Architecture

```
DEPLOY TIME
  ./deploy.sh ──► scripts/generate_enhancements.py
                    └─ git log ──► llm.generate_system_enhancements()
                                     └─ EnhancementItem.walkthrough (3-6 steps)
                                     └─ enhancements_data.json  (committed to git)
  committed assets: walkthrough_media/*.gif + walkthrough_media.json  (ship in image)

REP (chat)  Briefings → System enhancements ──► `system_enhancements` A2UI card
   📖 Show me how ──► one walkthrough card:
        1. walkthrough steps        (from enhancements_data.json)
        2. 🎞 demo GIF + caption     (system_stub._gif_for → walkthrough-media route)
        3. ▶ training video          (system_stub._video_url_for → latest upload)

GO-TO-CHANNEL (Settings → Training & Enablement)
  GET  /api/training/enhancements ──► list (tag, title, detail, answer, walkthrough, video_url, gif_url, hidden)
  Shown / Hidden toggle ────► POST /api/training/enhancements/hide {title, hidden}
                                 └─ hidden_enhancements table ──► title subtracted from rep card
  🎬 Generate storyboard ──► POST /api/training/storyboard ──► llm.generate_video_storyboard() → VideoStoryboard
  ⬆ Upload training video ──► POST /api/training/video (multipart) ──► uploaded_media/<uuid> + enhancement_videos row
  ✕ Remove ──────────────► DELETE /api/training/video/{id}
```

### Why these choices

- **Why one "Show me how" instead of separate buttons.** Steps, a demo GIF, and a
  video are three fidelities of the same answer ("how do I use this?"). Folding
  them into one card means the rep taps once and gets whatever depth exists, in a
  sensible order (read → watch a quick loop → watch the full video), instead of
  guessing which button to press.
- **Why walkthroughs ride along with the enhancements.** The "What's new" card is
  already regenerated from the git log on every deploy
  ([doc 15](15-system-enhancements-generation.md)); making the walkthrough a field
  on each `EnhancementItem` means a rep's how-to is generated from the same commits
  that shipped the feature — always current, never hand-maintained.
- **Why GIFs are committed, not generated at deploy.** Capturing a GIF requires
  driving a real browser through the flow, which a headless deploy can't do. So
  GIFs are authored once and checked into git — which also makes them durable
  (they ship in the image and survive redeploys, unlike uploaded videos). They are
  matched to enhancements on **title** to avoid keyword collisions, and only
  advertised when the file exists on disk.
- **Why the storyboard is a separate, on-demand step.** A full narration script is
  a heavier artifact aimed at producing an actual video, so it's generated per
  feature only when the team asks — and it's seeded from that feature's real
  walkthrough, so the script stays grounded in the steps reps actually take.
- **Why videos are linked to an enhancement by title.** The enhancement list is
  regenerated from git each deploy and has no durable per-enhancement id, so
  `enhancement_title` is the closest stable key. It's a deliberate tradeoff —
  renaming an enhancement's title would orphan its video.
- **Why hidden enhancements live in their own table, keyed by title.** The
  enhancement list is regenerated from git each deploy and carries no durable id, so
  — exactly like uploaded videos — the only stable handle is the title. Rather than
  trying to flag records inside the redeployed JSON, we persist just the hidden
  titles in `hidden_enhancements` and subtract that set at serve time; the rep card
  (`get_system_enhancements`) and the Settings list (`all_enhancements`) read the
  same set, so they can't drift.
- **Why ephemeral storage is acceptable for uploads.** `uploaded_media/` lives on
  Cloud Run's container disk, which is wiped on every redeploy exactly like the
  demo database ([doc 17](17-reseeding-deployed-data.md)). Uploads are for
  demo/session use; a production build would put them in object storage and serve
  via signed URLs. (Committed demo GIFs are unaffected — they ship in the image.)
- **Never trust the upload.** The handler checks the `video/*` content-type prefix,
  caps size at 32 MB by counting bytes as it streams (deleting the partial file if
  the cap is exceeded), and stores under a generated `uuid` filename. The
  GIF-serving route rejects names with path separators or a leading `.` and
  confirms the resolved path stays inside `walkthrough_media/`.

---

## API

| Method & path | Purpose |
|---|---|
| `GET /api/training/enhancements` | Full enhancement records (`tag`, `title`, `detail`, `answer`, `walkthrough`, `video_url`, `gif_url`, `gif_caption`, `hidden`) for the Settings Training list |
| `POST /api/training/enhancements/hide` | Hide or un-hide one enhancement in the rep-facing card — `{title, hidden}` → `{title, hidden}` |
| `POST /api/training/storyboard` | Generate a narration script + storyboard — `{title, detail, answer, walkthrough?}` → `VideoStoryboard` |
| `GET /api/training/walkthrough-media/{name}` | Serve a committed demo GIF (path-traversal safe) |
| `GET /api/training/videos` | List uploaded training-video metadata |
| `POST /api/training/video` | Upload a video (multipart `enhancement_title` + `file`); 400 non-video, 413 over 32 MB |
| `GET /api/training/video/{id}` | Stream a stored video |
| `DELETE /api/training/video/{id}` | Delete the video file + metadata row |

Code: [`backend/app/api/training.py`](../backend/app/api/training.py),
[`backend/app/mcp/system_stub.py`](../backend/app/mcp/system_stub.py)
(`all_enhancements`, `get_system_enhancements`, `_ensure_walkthrough`, `_video_url_for`, `_gif_for`),
[`backend/app/store/db.py`](../backend/app/store/db.py) (`hidden_enhancement_titles`, `set_enhancement_hidden`),
[`backend/app/llm.py`](../backend/app/llm.py) (`generate_video_storyboard`),
[`backend/scripts/generate_enhancements.py`](../backend/scripts/generate_enhancements.py).

---

## Data model

| Table | Purpose |
|---|---|
| `enhancement_videos` | One row per uploaded training video: `enhancement_title` (link key), `stored_name` (on-disk uuid filename), `original_name`, `content_type`, `size_bytes`, `uploaded_at`. The file lives on disk; this row is the metadata |
| `hidden_enhancements` | One row per enhancement a manager has hidden from reps: `enhancement_title` (primary key, the same stable title key `enhancement_videos` uses), `hidden_at`. A row's *presence* means "hidden" — hiding inserts it, un-hiding deletes it (`HiddenEnhancement` in [`models.py`](../backend/app/store/models.py)) |

Walkthroughs and demo GIFs are **not** tables — walkthroughs are a field on each
generated enhancement in `enhancements_data.json` (see the `Walkthrough` /
`WalkthroughStep` schemas in [`schemas.py`](../backend/app/schemas.py)); demo GIFs
are committed files under `walkthrough_media/` matched by `walkthrough_media.json`.

---

## Frontend

| File | Role |
|---|---|
| `frontend/src/components/SettingsPage.tsx` | The **Training & Enablement** Settings section: the per-enhancement **Shown / Hidden** toggle (`toggleHidden`, dims the row + "Hidden from reps" badge), per-enhancement storyboard generate/copy, and the video upload / preview / remove controls |
| `frontend/src/components/ChatWidget.tsx` | `WalkthroughCard` — renders the unified "Show me how": steps, then demo GIF + caption, then training video |
| `frontend/src/components/A2UI.tsx` | `SystemEnhancementsCard` — the `system_enhancements` element; a single **Show me how** button carrying `walkthrough`, `gif_url`, and `video_url` |
| `frontend/src/api.ts` / `types.ts` | `trainingEnhancements`, `setEnhancementHidden`, `generateStoryboard`, `uploadEnhancementVideo`, `deleteEnhancementVideo`; `VideoStoryboard`, `Walkthrough`, `TrainingEnhancement` (with optional `hidden`) |

---

## Authoring a new demo GIF

1. Run the app locally (dev server + backend).
2. Drive the flow with Playwright, screenshotting frames (see the capture scripts
   used in development), or any screen-capture that yields PNG frames.
3. Assemble a small looping GIF with ffmpeg (palette for quality; scale to ~760px):
   `ffmpeg -framerate 1.4 -i frame_%03d.png -vf "scale=760:-1,palettegen" pal.png`
   then `paletteuse` to produce the `.gif`.
4. Drop the `.gif` in `backend/app/mcp/walkthrough_media/` and add a manifest entry
   with `match` terms that appear in the target enhancement's **title**.

---

## Known limitations & future work

- **GIFs are hand-authored.** They cover the flagship flows, not every enhancement;
  new features need a capture pass to get a demo GIF. They're silent and looping by
  design (no narration).
- **Ephemeral video storage.** Uploaded videos do not survive a redeploy on Cloud
  Run. Move to object storage (GCS/S3) + signed URLs for durability. (Committed
  demo GIFs are durable.)
- **Title-linked media & visibility.** Renaming an enhancement orphans its uploaded
  video and its hidden flag (GIFs re-match on the new title via the manifest); a
  durable per-enhancement id would remove the coupling. Hidden state lives in the
  demo SQLite DB, so — like the seed data — it resets on a Cloud Run redeploy.
- **No transcode / thumbnailing.** Videos are served back as-is; there's no format
  normalization, poster-frame extraction, or captions pipeline.
- **Storyboard is text only.** It produces a script + shot list for a human/AI
  video tool — it does not render a video itself.
