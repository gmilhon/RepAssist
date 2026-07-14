# Deployment — Google Cloud Run

Rep Assist deploys as a **single Cloud Run service** that serves both the FastAPI
orchestrator **and** the built React frontend from one URL — no separate frontend
host, no CORS. Secrets live in **Secret Manager**, never in the image or git.

> **Current deployment:** `https://rep-assist-374044178474.us-central1.run.app`

---

## How it's packaged

```
frontend (Vite build)  ─►  backend/static/   ─►  Docker image  ─►  Cloud Run
                                    ▲                                   │
                                    └── FastAPI serves it via a         │
                                        catch-all route (SPA)  ◄────────┘
```

- [`backend/Dockerfile`](../backend/Dockerfile) — `python:3.12-slim`, installs
  `requirements.txt`, copies `app/` and the bundled `static/`, runs
  `uvicorn app.main:app` on port `8080`.
- [`backend/app/main.py`](../backend/app/main.py) — mounts `/assets` and adds a
  `/{path:path}` catch-all **after** all API routes, so `/api/*` and `/health`
  always win and everything else serves `index.html` (SPA routing).
- `backend/static/` is a **build artifact** (git-ignored); `deploy.sh` regenerates
  it from `frontend/dist` on every deploy.

---

## Prerequisites

```bash
# Install the gcloud CLI: https://cloud.google.com/sdk/docs/install
gcloud auth login
gcloud config set project YOUR_PROJECT_ID     # the string ID, not the number
```

You need a GCP project with billing enabled. The script enables the required APIs
(Run, Cloud Build, Container Registry, Secret Manager) itself.

---

## One-command deploy

```bash
./deploy.sh                       # uses the gcloud default project
# or
./deploy.sh --project my-proj --region us-central1
```

[`deploy.sh`](../deploy.sh) is idempotent and does the whole thing:

1. **Enable APIs** — Run, Cloud Build, Container Registry, Secret Manager.
2. **Create secrets** (skips any that exist) — prompts for the Anthropic key,
   LangSmith key, and SMTP password; **auto-generates** the admin token.
3. **Grant IAM** — gives the Cloud Run runtime service account
   (`<project-number>-compute@developer.gserviceaccount.com`) the
   `roles/secretmanager.secretAccessor` role.
4. **Build the frontend** (`npm ci && npm run build`) and bundle it into
   `backend/static/`.
5. **Build the image** via Cloud Build → `gcr.io/<project>/rep-assist`.
6. **Deploy** to Cloud Run and print the live URL.

### Runtime configuration it sets

| Setting | Value | Why |
|---|---|---|
| `--min-instances` / `--max-instances` | `1` / `1` | Always-on single instance — keeps the local SQLite DB warm between requests. |
| `--memory` | `2Gi` | Headroom for the synthetic-data seed job (~250k rows). |
| `--timeout` | `600` | The seed endpoint runs in the background but the request can take minutes. |
| `--allow-unauthenticated` | — | Public demo URL. Gate behind IAP/SSO before pilot. |

---

## Secrets (Secret Manager)

| Secret | Env var | Purpose |
|---|---|---|
| `rep-assist-anthropic-key` | `ANTHROPIC_API_KEY` | Live Claude |
| `rep-assist-langsmith-key` | `LANGCHAIN_API_KEY` | LangSmith tracing / CX Monitor |
| `rep-assist-smtp-password` | `SMTP_PASSWORD` | Email reports |
| `rep-assist-admin-token` | `ADMIN_TOKEN` | Gates `POST /api/admin/seed` |

Non-secret config (model, LangSmith project, SMTP host/user/from) is passed via
`--set-env-vars`. **`GET /api/email/settings` never returns secret values.**

> **Gotcha — `--set-secrets` replaces the whole set.** When updating one secret on
> a running service, pass *all* of them in a single `--set-secrets` flag, or the
> others get dropped.

### Rotating a key

```bash
# add a new version (keeps history; Cloud Run reads :latest)
printf '%s' 'NEW_VALUE' | gcloud secrets versions add rep-assist-anthropic-key --data-file=-
# roll a new revision so it's picked up
gcloud run services update rep-assist --region us-central1 \
  --set-secrets "ANTHROPIC_API_KEY=rep-assist-anthropic-key:latest,LANGCHAIN_API_KEY=rep-assist-langsmith-key:latest,SMTP_PASSWORD=rep-assist-smtp-password:latest,ADMIN_TOKEN=rep-assist-admin-token:latest"
```

---

## Redeploy after code changes

Re-run `./deploy.sh` — it rebuilds the frontend, re-bundles, rebuilds the image,
and rolls a new revision. Frontend-only or backend-only changes both go through
the same path (the frontend is baked into the image).

Before the frontend build, it also regenerates the **System Enhancements**
("What's new in Rep Assist") card from the commits since the last deploy — see
[doc 15](15-system-enhancements-generation.md). Skipped gracefully (existing
content ships as-is) if `backend/.venv` or `ANTHROPIC_API_KEY` isn't available
on the machine running the deploy.

---

## Seeding synthetic history (deployed)

The database ships empty. To populate realistic history for demos, call the
token-protected admin endpoint (see also
[Operations Dashboard](08-operations-dashboard.md)):

```bash
TOKEN=$(gcloud secrets versions access latest --secret rep-assist-admin-token)
BASE=https://rep-assist-374044178474.us-central1.run.app

# kick off the background seed (Jan 1 → today, ~5,700 conversations/week)
curl -s -X POST "$BASE/api/admin/seed" -H "X-Admin-Token: $TOKEN"
# poll until done
curl -s "$BASE/api/admin/seed/status" -H "X-Admin-Token: $TOKEN"
```

The seed runs in the background (FastAPI `BackgroundTasks`), inserts week-by-week
via raw SQL `executemany` for speed, and reports totals via the status endpoint.
Code: [`backend/app/api/admin.py`](../backend/app/api/admin.py).

---

## Persistence caveat

SQLite lives **inside the container**, so tickets, subscribers, checkpoints, and
seeded history **reset on every redeploy** (and if the single instance is
recycled). That's acceptable for a prototype/demo. For durable data, move to
**Cloud SQL (Postgres)** — set `TICKETS_DB_URL` to the Postgres DSN and use a
Postgres/Redis LangGraph checkpointer, then `--min/--max-instances` can scale past 1.

The same single-instance assumption applies to the **System Health SSE
subscriber list** ([doc 13](13-system-health.md)) — it's an in-process
`list[asyncio.Queue]`, not shared storage. With `--max-instances 1` (the
default here) every rep's live connection lands on the one instance, so
real-time notify-on-save works correctly. If you ever raise `--max-instances`,
a `notify` triggered against one instance won't reach reps whose SSE connection
is pinned to another — that needs a shared pub/sub (Redis, GCP Pub/Sub) instead.

---

## File manifest

| File | Role |
|---|---|
| `deploy.sh` | End-to-end deploy (APIs, secrets, IAM, build, deploy) |
| `backend/Dockerfile` | Container image (Python 3.12-slim + bundled frontend) |
| `backend/.dockerignore` | Excludes venv, `.env`, SQLite files from the image |
| `backend/app/main.py` | Serves `static/` via `/assets` mount + SPA catch-all |
| `backend/app/api/admin.py` | Token-gated synthetic-data seed endpoint |
| `backend/app/api/system_health.py` | Status GET/POST + SSE live-notification stream ([doc 13](13-system-health.md)) |
| `backend/scripts/generate_enhancements.py` | Regenerates "What's new" from git log before each deploy ([doc 15](15-system-enhancements-generation.md)) |
