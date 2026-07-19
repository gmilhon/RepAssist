# Reseeding the Deployed Environment's Demo Data

Every `./deploy.sh` run rolls a fresh Cloud Run revision with an **empty**
SQLite database — see [Persistence caveat](12-deployment-cloud-run.md#persistence-caveat).
The deployed app is fully functional immediately after a deploy, but every
dashboard (Performance, CX Monitor, Resolution Desk, Production Monitor)
shows zero/empty data — and the store check-in queue (with its topbar
**Live Queue** indicator, see [doc 22](22-live-queue.md)) is empty — until
the demo history is repopulated. This doc is the
exact, copy-pasteable procedure for doing that against the **live Cloud Run
service** — not local dev, which is a different process (see
[Local vs. deployed](#local-vs-deployed) below).

A matching Claude Code skill at
[`.claude/skills/reseed-deployed-env/SKILL.md`](../.claude/skills/reseed-deployed-env/SKILL.md)
lets any future Claude Code conversation in this repo run this procedure
without re-deriving it.

---

## When to run this

- **After every `./deploy.sh` run.** A redeploy always wipes the container's
  SQLite file. If you just deployed, the environment needs reseeding before
  it's demo-ready.
- **Whenever asked to "reseed the deployed environment," "refresh the demo
  data," or similar** — even if no deploy just happened (e.g., the instance
  recycled, or the data has drifted and needs a clean deterministic reset).
- **Not** needed after every code change — only after an actual deploy, or
  on explicit request.

---

## Prerequisites

- `gcloud` authenticated against the right project (`test-494103` as of this
  writing). Check with:
  ```bash
  ~/google-cloud-sdk/bin/gcloud config get-value project
  ```
- `gcloud` is **not** guaranteed to be on `PATH` in every shell — this repo's
  install lives at `~/google-cloud-sdk/bin/gcloud`. Prepend it before running
  any `gcloud` command:
  ```bash
  export PATH="$HOME/google-cloud-sdk/bin:$PATH"
  ```

---

## The procedure

Three steps: fetch the admin token, kick off the seed job, poll until done.
The seed endpoint is token-protected and runs as a FastAPI background task —
`POST` returns immediately (`202`), the actual seeding continues after the
response.

```bash
export PATH="$HOME/google-cloud-sdk/bin:$PATH"

# 1. Fetch the admin token fresh from Secret Manager every time — don't
#    hardcode or reuse a value from a prior session, it can rotate.
ADMIN_TOKEN=$(gcloud secrets versions access latest --secret=rep-assist-admin-token)
URL="https://rep-assist-374044178474.us-central1.run.app"

# 2. Kick off the seed job (fire-and-forget; responds in well under a second)
curl -s -X POST "$URL/api/admin/seed" -H "X-Admin-Token: $ADMIN_TOKEN"
# → {"status": "started", "poll": "/api/admin/seed/status"}
```

Then **poll until it's done** — the job takes roughly **1–3 minutes**
(cold container start + inserting several hundred thousand rows across
`engagement`, `ticket`, `llm_calls`, `action_audit`, and `guardrail_events`,
plus a handful of "live right now" `queue_entries` store check-in fixtures).
Don't declare success from the `POST` response alone; that only confirms the
job *started*.

```bash
for i in {1..25}; do
  sleep 10
  STATUS=$(curl -s "$URL/api/admin/seed/status" -H "X-Admin-Token: $ADMIN_TOKEN")
  RUNNING=$(echo "$STATUS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('running'))")
  echo "[$i] running=$RUNNING"
  if [ "$RUNNING" = "False" ]; then
    echo "$STATUS" | python3 -m json.tool
    break
  fi
done
```

A successful finish looks like:

```jsonc
{
  "running": false,
  "done": true,
  "result": {
    "seeded_days": 197,
    "date_range": "2026-01-01 → 2026-07-16",
    "conversations": 157614,
    "engagements": 250508,
    "tickets": 44936,
    "llm_calls": 315238,
    "actions_audited": 82283,
    "guardrail_events": 30,
    "queue_entries": 11,
    "weekly_avg_conversations": 5600
  },
  "error": null
}
```

Row counts scale with how many days have elapsed since the seed's fixed
start date (`date(2026, 1, 1)` in `admin.py`, hardcoded — not derived from
"this year") through today, so totals grow slightly larger every time it's
re-run later on. That's expected, not a bug. If this repo is still active
past 2026, that start date will need bumping — [`_run_seed()`](../backend/app/api/admin.py)
is the place to change it.

`queue_entries` is the one count that **doesn't** scale with the date range:
it's a fixed set of **11** store check-in fixtures timestamped relative to
*now* (2 waiting walk-ins, 2 in-progress, 2 ISPU to-pick, 2 ISPU staged/ready,
and 3 future appointments booked for later today), so the topbar **Live Queue**
indicator and its drawer ([doc 22](22-live-queue.md)) — and the chat "View
queue" card — have something to show right after a reseed instead of an empty
floor.

If `"error"` is non-null, or the loop exhausts all 25 iterations still
`running=true`, see [Troubleshooting](#troubleshooting).

---

## Verifying it worked

Spot-check a couple of endpoints rather than trusting the status payload
alone:

```bash
curl -s "$URL/api/metrics/overview" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print('conversations:', d['engagement']['conversations'])
print('containment:', d['outcomes']['containment_rate'])
"
```

Non-zero, plausible numbers confirm the data actually landed. If you want
visual confirmation, open the deployed URL and check the Performance or CX
Monitor tab.

---

## Local vs. deployed

This procedure targets the **live Cloud Run URL**
(`https://rep-assist-374044178474.us-central1.run.app`). It is unrelated to
local dev seeding:

| | Local dev | Deployed |
|---|---|---|
| Target | `http://127.0.0.1:8000` (or wherever `uvicorn` is running) | The Cloud Run URL |
| Auth | The local `/api/admin/seed` endpoint is **disabled (403 on every call)** unless `ADMIN_TOKEN` is set in `backend/.env` — `_require_token` fails closed; once set it needs a matching `X-Admin-Token` header, exactly like deployed | Required — `X-Admin-Token` from Secret Manager |
| Alternative | Run a seed **script** directly (no token — bypasses the HTTP layer): `python backend/scripts/seed_demo.py` reproduces the full demo set **including the 11 store-queue fixtures** (walk-ins, ISPU, and today's appointments). `seed_ytd.py` seeds only engagement/ticket history — it does **not** populate `queue_entries` | Only via the HTTP endpoint — there's no way to run the script inside the container directly |

Don't mix these up: pointing the deployed procedure's `curl` calls at
`127.0.0.1` (or vice versa) will silently fail or reseed the wrong database.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `curl: command not found` for `gcloud` calls | `gcloud` not on `PATH` in this shell | `export PATH="$HOME/google-cloud-sdk/bin:$PATH"` first |
| `403` on any call | Stale or wrong admin token | Re-fetch: `gcloud secrets versions access latest --secret=rep-assist-admin-token` — don't reuse a token from an earlier session |
| Poll loop exhausts 25 iterations, still `running=true` | Cold start + large seed can occasionally run long | Just re-run the poll loop — the `POST` is safe to skip; a running job doesn't need to be restarted |
| `{"status": "already_running"}` from the `POST` | A seed job is already in flight (yours or a concurrent one) — the endpoint refuses to start a second job while one is running, so this is never harmful to call | Skip straight to polling `/api/admin/seed/status` until it finishes |
| Numbers look identical to last time | You reseeded the same day the previous seed already covered | Expected — the seed is deterministic for a given date range; totals only grow once a new day passes |

---

## How it works

Code: [`backend/app/api/admin.py`](../backend/app/api/admin.py) — `_run_seed()`
deletes all rows from `engagement`, `ticket`, `llm_calls`, `action_audit`,
`guardrail_events`, and `queue_entries`, then regenerates deterministic synthetic
history (fixed random seed) week-by-week via raw SQL `executemany` for speed,
covering a fixed start date through today. The `queue_entries` rows are the
exception to the week-by-week history: `_QUEUE_SAMPLES` is a small fixed set of
live check-in fixtures inserted once, timestamped relative to *now*. See
[Observability](16-observability.md) for what the `llm_calls`/`action_audit`/
`guardrail_events` tables represent, and
[Operations Dashboard](08-operations-dashboard.md) for what the resulting
KPIs mean.
