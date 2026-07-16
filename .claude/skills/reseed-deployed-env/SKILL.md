---
name: reseed-deployed-env
description: Re-seed the deployed Rep Assist Cloud Run environment's demo data (synthetic conversations, tickets, LLM calls, guardrail events). Use this whenever the user asks to "reseed the deployed environment," "reseed the deployment," "refresh the demo data," or similar on the live/deployed app — and proactively after running ./deploy.sh, since every deploy wipes the container's SQLite database and leaves every dashboard empty until this runs. Do NOT use this for local dev reseeding (that targets 127.0.0.1, not Cloud Run, and needs no admin token) — this skill is specifically for the live https://rep-assist-374044178474.us-central1.run.app URL.
---

# Reseed the deployed environment

Full written runbook, with a troubleshooting table and rationale for each
step: [`docs/17-reseeding-deployed-data.md`](../../../docs/17-reseeding-deployed-data.md).
This file is the condensed, execute-directly version for use inside a
conversation.

## Why this exists

SQLite lives inside the Cloud Run container. Every `./deploy.sh` run rolls a
fresh revision with an **empty database** — the app itself works immediately,
but Performance, CX Monitor, Resolution Desk, and Production Monitor all show
zero data until this seed job runs. Always reseed right after a deploy;
that's not optional cleanup, it's part of finishing the deploy.

## Prerequisites

`gcloud` must be authenticated against the deploy's project, and — in this
environment specifically — is **not** on `PATH` by default:

```bash
export PATH="$HOME/google-cloud-sdk/bin:$PATH"
```

Confirm the right project is active if anything looks off:

```bash
gcloud config get-value project   # expect: test-494103 (as of this writing)
```

## Run it

Three steps: fetch a fresh admin token, start the seed job, poll until it
finishes. Don't skip the poll — the `POST` only confirms the job *started*
(it returns in well under a second); the actual seeding takes **1–3
minutes**.

```bash
export PATH="$HOME/google-cloud-sdk/bin:$PATH"
ADMIN_TOKEN=$(gcloud secrets versions access latest --secret=rep-assist-admin-token)
URL="https://rep-assist-374044178474.us-central1.run.app"

curl -s -X POST "$URL/api/admin/seed" -H "X-Admin-Token: $ADMIN_TOKEN"
```

Then poll (run this as one background-capable command — it blocks for up to
~4 minutes):

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

Success looks like `"done": true, "result": {"conversations": <large number>, ...}, "error": null`.
Report the result's `conversations`/`engagements`/`tickets`/`llm_calls`
counts back to the user as confirmation — don't just say "done," show the
numbers, since that's the actual proof the data landed.

## Fetch the token fresh every time

Always re-fetch `ADMIN_TOKEN` from Secret Manager in the same turn you use
it — never hardcode a token value from a prior conversation or reuse one
across sessions. It can rotate, and a stale token fails with a `403` that's
easy to misdiagnose as something else.

## If it's slow or looks stuck

A 1–3 minute wait is normal (cold container start + several hundred
thousand rows written across `engagement`, `ticket`, `llm_calls`,
`action_audit`, `guardrail_events`). If the poll loop above exhausts all 25
iterations still `running=true`, just run the poll loop again — re-running
the `POST` is unnecessary (and harmless: the endpoint refuses to start a
second job while one is running, returning `{"status": "already_running"}`
instead of double-seeding).

## Don't confuse this with local dev

This skill targets the **live Cloud Run URL**. Local dev reseeding is a
different, unauthenticated process (`python backend/scripts/seed_ytd.py`,
or hitting `127.0.0.1:8000`'s same endpoint with no token needed unless
`ADMIN_TOKEN` is set in `backend/.env`). If the user's ask is ambiguous
about which environment, ask — pointing these commands at the wrong target
silently does nothing useful.

## After deploying

If this skill is being invoked right after a `./deploy.sh` run in the same
conversation, no need to ask whether to reseed — just do it as the natural
last step of finishing the deploy, and mention the fresh row counts in your
summary.
