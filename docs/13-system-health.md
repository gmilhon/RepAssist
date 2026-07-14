# System Health & Live Notifications

A **System Health badge** sits in the topbar on every tab, so a rep always knows
the assistant's status without leaving their conversation. An **operator**
(anyone on the Settings tab) sets the status; optionally, saving a change can
**push a live toast notification** to every rep who currently has the app open —
no refresh required.

---

## User flow

1. **Badge (all tabs)** — a colored dot + label (`Operational` / `Degraded` /
   `Outage`) in the topbar. Click it to open the **health panel**.
2. **Health panel** — status banner, hard-stop warning (if set), the event
   description/workaround (if set), live **server region pings** (US East/Central/
   West), **live diagnostics** (API round-trip, client IP, browser, connection
   type), and browser cache stats with a **Clear all** action.
3. **Settings tab → System Health** — the operator form: pick a status, write a
   description + workaround, toggle **Hard stop** (warns reps not to process new
   orders), toggle **Notify active users when saved**, then **Save**.
4. **Live notification** — if "Notify" was checked, every browser tab with the
   app open receives a toast in the bottom-right corner (auto-dismisses after 8s,
   or click ✕) and the topbar badge updates immediately, without waiting for the
   60-second poll.

The **Notify** checkbox always resets to unchecked after a successful save, so
notifying is an explicit, per-save decision — routine status edits don't spam
reps by default.

---

## Architecture

```
React                                    FastAPI
  App.tsx           ── poll (60s) ────►   GET  /api/system-health
  App.tsx           ── SSE stream ────►   GET  /api/system-health/events
  SettingsPage.tsx  ── save ──────────►   POST /api/system-health  {..., notify}
                                            ↳ persists to system_health.json
                                            ↳ if notify: broadcast to all
                                              connected SSE subscribers
  HealthPanel.tsx   ── on demand ─────►   GET  /api/system-health/ping
                                           GET  /api/system-health/ping/{region}
```

- **Delivery is two-layered on purpose.** The 60-second poll (`loadSysHealth`)
  is the source of truth and self-heals if a client missed an SSE event (tab was
  backgrounded, connection dropped). SSE (`EventSource`) is purely a
  **low-latency push** on top — losing it degrades to "notice within 60s"
  instead of "notice instantly," never to "never notice."
- **Broadcast, not persistence, of the notify flag.** `notify` is not stored in
  `system_health.json` — it's a one-shot instruction to fan the *next* update out
  over SSE. Reloading the page always shows the latest persisted status via the
  `GET` endpoint regardless of whether it was ever broadcast.
- **In-memory subscriber list.** `_subscribers` in
  [`system_health.py`](../backend/app/api/system_health.py) is a plain
  `list[asyncio.Queue]`, one per open SSE connection, alive only for the
  lifetime of that connection and that container instance (see
  [Persistence caveat](12-deployment-cloud-run.md#persistence-caveat) — same
  single-instance assumption as the SQLite DB).

---

## API

| Method & path | Purpose |
|---|---|
| `GET /api/system-health` | Current status (polled every 60s) |
| `POST /api/system-health` | Set status; body includes `notify: bool` — `true` broadcasts to live clients |
| `GET /api/system-health/events` | SSE stream — `event: health_update` whenever a `notify=true` save happens |
| `GET /api/system-health/ping` | Round-trip latency + client IP + connected region |
| `GET /api/system-health/ping/{region}` | Same, pinned to `east` \| `central` \| `west` |

**Set status body:**

```jsonc
{
  "status": "operational" | "degraded" | "outage",
  "description": "",
  "workaround": "",
  "hard_stop": false,
  "notify": false        // true → push a live toast to every connected client
}
```

**SSE event payload** (`event: health_update`):

```jsonc
data: {"status":"degraded","description":"...","workaround":"...","hard_stop":false,"updated_at":"2026-07-11T23:33:06Z"}
```

Code: [`backend/app/api/system_health.py`](../backend/app/api/system_health.py).

---

## Frontend

| File | Role |
|---|---|
| `frontend/src/App.tsx` | Topbar badge, 60s poll, `EventSource` subscription, toast stack |
| `frontend/src/components/HealthPanel.tsx` | Status banner, hard-stop notice, server-region pings, live diagnostics, cache clear |
| `frontend/src/components/SettingsPage.tsx` | Operator form — status radio, description/workaround, hard-stop + notify checkboxes |
| `frontend/src/api.ts` | `getSystemHealth`, `setSystemHealth`, `healthEventsUrl`, `ping`, `pingRegion` |
| `frontend/src/types.ts` | `SystemHealth`, `PingResult` |
| `frontend/src/styles.css` | `.health-badge*`, `.hpanel*`, `.sh-*` (form), `.health-toast*` (notification stack) |

---

## Dev proxy note (SSE + Vite)

`frontend/vite.config.ts` proxies `/api/system-health/events` **explicitly**,
separately from the general `/api` proxy, forcing the `Accept: text/event-stream`
header on the upstream request. Without this, `http-proxy`'s default buffering
can hold the stream open without flushing chunks to the browser, so the
`EventSource` never fires. Every SSE endpoint needs its own proxy entry (or a
shared one keyed on a `/stream` path prefix) rather than relying on the
catch-all `/api` rule — the [Production Monitor](14-production-monitoring.md)'s
`/api/production/events` has a matching entry for the same reason.

---

## Production notes

- **Auth.** `POST /api/system-health` and the SSE endpoint are unauthenticated in
  the prototype (same as most non-admin routes) — gate them behind the app's SSO
  before pilot so only authorized operators can change status or trigger a
  broadcast.
- **Multi-instance.** If `--max-instances` is raised above `1` (see
  [Deployment](12-deployment-cloud-run.md)), SSE subscribers on one instance
  won't hear a `notify` triggered against a request routed to another instance.
  Fan-out across instances needs a shared pub/sub (Redis, GCP Pub/Sub) behind
  `_broadcast()` instead of the in-process queue list.
- **Reconnection.** The browser's native `EventSource` auto-reconnects on drop;
  no custom retry logic was needed.
