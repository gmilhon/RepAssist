# System Enhancements — Generated From Git History

The **"What's new in Rep Assist"** card (the ✨ chip in chat, and the *system*
intent's answers to "what's new?" questions) used to be a hand-maintained,
static list — it never changed unless someone manually edited
[`system_stub.py`](../backend/app/mcp/system_stub.py), so it silently drifted
out of date every time a real feature shipped. It's now **generated from the
repo's own commit history** and refreshed automatically on every deploy.

---

## How it works

```
deploy.sh (step 2c, before the frontend build)
  └─ backend/scripts/generate_enhancements.py
       ├─ git log <last_commit_sha>..HEAD   (repo root, full commit messages)
       ├─ llm.generate_system_enhancements(log, previous_enhancements)
       │    └─ Claude, structured output (SystemEnhancementsDoc) — merges with
       │       what's already published, drops internal-only changes, caps at 8
       └─ writes backend/app/mcp/enhancements_data.json
            (generated_at, last_commit_sha, enhancements[], suggestions[])

system_stub.py loads enhancements_data.json once at process start (falls back
to a small seed list if the file has never been generated) and serves it via
the existing get_system_enhancements / answer_system_question MCP tools —
no change to the API or A2UI card shape reps already see.
```

- **Filtering is the important part.** The generation prompt explicitly tells
  Claude to skip anything a retail rep wouldn't notice or care about — CI/deploy
  fixes, refactors, dependency bumps, admin-only tooling, internal dashboards.
  A rep-invisible feature (e.g. an ops-only monitoring tab) correctly produces
  **no card**, even though it's a real, shipped feature — that's by design, not
  a bug: this card answers "what changed for *me*," not "what changed in the repo."
- **Managers can hide individual cards.** On top of generation-time filtering,
  `get_system_enhancements` omits any enhancement a manager has hidden from
  **Settings → Training & Enablement** — it drops every entry whose title is in
  `db.hidden_enhancement_titles()` (the `hidden_enhancements` table) before
  building the rep-facing card. Generation still produces the entry; the toggle
  just controls whether reps see it. See
  [Training & Enablement](21-training-and-enablement.md).
- **Merge, don't replace.** Each run passes the previously published list back
  to Claude alongside the new commits, so it can carry forward still-relevant
  items, fold a follow-up commit into an existing entry (e.g. a later "add
  live notify" commit got merged into the existing "System health" entry
  instead of becoming a redundant second card), and drop stale ones — capped
  at 8 total.
- **High-water mark.** `last_commit_sha` in the output file means each run only
  looks at commits since the last successful generation — an unrelated big
  commit range doesn't get re-summarized every deploy.
- **Each entry also carries a rep walkthrough.** Every generated
  `EnhancementItem` includes a hands-on 3–6-step `walkthrough` (plus a detailed
  follow-up `answer`) teaching a rep to use that feature in the app. These are
  generated here so a rep's how-to always ships with the commit that added the
  feature, and they power the **Training & Enablement** surface: the rep's single
  **"Show me how"** unfolds the steps, an animated **demo GIF** of the flow (when
  one is matched), and an uploaded **training video** (when attached) — plus an AI
  storyboard generator for the Go-To-Channel team. See
  [Training & Enablement](21-training-and-enablement.md).
- **No credentials → no-op, never a bad overwrite.** If `ANTHROPIC_API_KEY`
  isn't configured (or the venv is missing) the step is skipped with a warning
  and the deploy continues; the previously generated file — or the small seed
  list on a fresh clone — ships as-is. It never overwrites good curated
  content with nothing just because a key was missing on one run.

---

## Running it

```bash
cd backend
python scripts/generate_enhancements.py
```

Runs automatically as step 2c of [`deploy.sh`](../deploy.sh) — no separate
step to remember. To pick up changes without a full deploy, run the script and
restart the local dev server (content is cached at process start, matching
[`system_health.py`](../backend/app/api/system_health.py)'s pattern).

`enhancements_data.json` is **checked into git** (not gitignored) — it needs
to exist inside the `backend/` Docker build context (which has no `.git`
history of its own), and keeping it versioned means every regeneration shows
up as a reviewable diff, same as any other content change.

---

## Files

| File | Role |
|---|---|
| `backend/scripts/generate_enhancements.py` | Reads git log, calls the LLM, writes the data file |
| `backend/app/llm.py` (`generate_system_enhancements`) | The structured-output Claude call; no offline fallback — the script skips instead |
| `backend/app/schemas.py` (`EnhancementItem`, `SystemEnhancementsDoc`, `Walkthrough`) | Structured-output schema: tag, title, detail, keywords, per-item answer, walkthrough, suggestions |
| `backend/app/mcp/system_stub.py` | Loads `enhancements_data.json`, serves the existing `get_system_enhancements` / `answer_system_question` MCP tools |
| `backend/app/mcp/enhancements_data.json` | Generated content — tracked in git |
| `deploy.sh` (step 2c) | Runs the script before every deploy |

---

## Known limitation

`answer_system_question` still routes by simple keyword substring match against
the LLM-generated `keywords` list (first match wins, same mechanism the old
hardcoded list used) — a rep phrasing that doesn't share a keyword falls
through to a generic top-3 summary rather than the specific answer. Since the
per-item `answer` field already exists in the generated data, a straightforward
upgrade is a live LLM call at question time (grounded in the current
enhancements list) instead of keyword matching, if this proves too blunt in
practice.
