# Store Check-In & Queue

Front-of-store intake: a rep checks a walk-in customer in — capturing why
they're here and how to reach them — and any rep can see the current queue
and start helping someone with a single tap.

This is deliberately **not** routed through the LangGraph orchestrator.
Check-in is a fixed-shape intake form (visit reason + name/phone), not an
open-ended problem for triage to classify. It reuses the existing **A2UI**
generative-card pipeline ([doc 10](10-a2ui-generative-ui.md)) for the queue
view, and hands off into the normal chat flow the moment a rep taps **Assist**
— that's where issue diagnosis actually happens, same as every other CTA.

---

## User flow

1. **Check In** (Front desk section, chat sidebar) opens an inline form:
   reason for visit (New Service, Upgrade, Home Internet, Appointment,
   In-Store Pickup, Account/Billing Support, Something Else), customer name,
   and phone number. At least one of name/phone is required.
2. Submitting posts the entry to the queue and drops a confirmation bubble
   into the chat with the customer's position in line (e.g. *"✅ Maria Lopez
   checked in — Upgrade. #2 in line."*).
3. **View queue** (also under Front desk) reveals the current queue as an
   A2UI `queue` card — customers waiting first (oldest first), then
   customers currently being helped, then today's still-to-come
   appointments appended as purple **Upcoming** rows (subtitle e.g.
   *"2 waiting · 3 upcoming appts"*). For the always-on, real-time floor
   view (the topbar **Live Queue** indicator and its drawer), see
   [doc 22](22-live-queue.md).
4. Tapping a **waiting** row's **Assist →** claims the entry (assigns the
   current rep, flips it to "Being helped") and sends a pre-filled message
   into the chat — *"I'm now assisting Maria Lopez — they're here for:
   Upgrade."* — with `customer_name` / `customer_phone` / `visit_reason` set
   as entities. From there the rep types what the customer actually needs and
   the normal triage → resolve → confirm flow takes over.

---

## Architecture

```
Check In tile ──► inline form (ChatWidget local state, not A2UI)
                     │
                     ▼
              POST /api/queue/checkin ──► db.create_queue_entry()
                     │                       └─ queue_entries row, status=waiting
                     ▼
              confirmation bubble (queue position)

View queue tile ──► GET /api/mcp/queue ──► mcp/queue_stub.get_queue()
                                              └─ reads db.list_queue() live
                                              └─ + db.live_queue_snapshot()["appointments"]
                                              └─ A2UI `queue` element

Assist button ──► POST /api/queue/{id}/assist ──► db.assist_queue_entry()
                     │                                └─ status=in_progress,
                     │                                   assigned_rep_id, started_at
                     ▼
              POST /api/chat (normal send()) ──► LangGraph orchestrator
                     entities: customer_name, customer_phone, visit_reason
```

- **Why an MCP stub for the rep's own operational data.** Every other MCP
  stub (orders, tickets, news, ost) fronts a *mock external system*. Queue is
  different — it's the app's own `queue_entries` table, populated by
  check-in. It's still exposed as an MCP tool so "View queue" renders through
  the same registry-driven A2UI pipeline as everything else (`A2UIRenderer`'s
  `type` switch in [`A2UI.tsx`](../frontend/src/components/A2UI.tsx)) instead
  of a one-off card component. `system_stub.py`'s enhancements card (backed
  by git-log-generated content, not static mock data either) is the existing
  precedent for this.
- **Why check-in isn't a graph intent.** The existing `Intent` enum
  (activation/pending_order/promo/occ/billing/general/system/other) and the
  `sales_intent` heuristic (nse/aal/up, see [doc 16](16-observability.md))
  both classify a *problem* after the rep describes it. Visit reason is
  captured *before* any problem is discussed — it's front-desk intake, not
  triage — so `VisitReason` is a third, independent taxonomy
  ([`schemas.py`](../backend/app/schemas.py)) with its own small closed set of
  values, not an extension of either existing one.
- **Why click-to-assist reuses `send()` instead of a bespoke API.** Clicking
  a queue row calls `assistQueueEntry()` (claim the entry) and then the same
  `send()` used by every other CTA tile and A2UI row (`OrderRow`,
  `TicketRow`) — same mechanism as opening a recent order or an open ticket,
  just with `customer_name`/`customer_phone`/`visit_reason` pre-filled as
  entities instead of `order_id`/`account_id`. No new confirmation/resolution
  machinery was needed.

---

## API

| Method & path | Purpose |
|---|---|
| `GET /api/mcp/queue` | Current queue (waiting + in-progress) plus today's future appointments (appended as `scheduled` rows), as an A2UI `queue` element |
| `GET /api/queue/live` | Full real-time floor snapshot for the Live Queue indicator — bucketed `{waiting, assisting, ispu_to_pick, ispu_ready, appointments}` lists plus a `counts` object. Backed by `db.live_queue_snapshot()`; documented in [doc 22](22-live-queue.md) |
| `POST /api/queue/checkin` | Create a check-in — `{customer_name?, customer_phone?, reason}`; 422 if neither identifier is given. Returns `{entry, queue_position}` |
| `POST /api/queue/{id}/assist` | Claim an entry — `{rep_id, thread_id?}`. Sets `status=in_progress`, `assigned_rep_id`, `started_at` |

Code: [`backend/app/api/queue.py`](../backend/app/api/queue.py) (both the
mutating routes and the `GET /live` snapshot),
[`backend/app/api/mcp.py`](../backend/app/api/mcp.py) (the `GET /api/mcp/queue`
route), [`backend/app/mcp/queue_stub.py`](../backend/app/mcp/queue_stub.py).

---

## Data model

| Table | Purpose |
|---|---|
| `queue_entries` | One row per check-in: `customer_name`, `customer_phone`, `reason` (`VisitReason` value), `status` (the `QueueStatus` enum — see below), `assigned_rep_id`, `thread_id`, `created_at`, `started_at`, nullable `account_id`/`order_id` (captured at check-in for the assist / Live Listen hand-off, see [doc 20](20-live-listen.md)), and a nullable `scheduled_at` (set only on `scheduled` appointment rows) |

`QueueStatus` now covers five states: walk-ins (`waiting` → `in_progress`),
the two in-store-pickup fulfilment states (`ispu_to_pick` = still to pick off
the shelf, `ispu_ready` = picked & staged, awaiting the customer), and
`scheduled` appointments booked for later today. `scheduled_at` was added as
an additive `ALTER TABLE queue_entries ADD COLUMN scheduled_at DATETIME`
migration in `db.init_db`, consistent with the other additive migrations
there. `db.live_queue_snapshot()` buckets the rows by status (appointments
filtered to the future and sorted earliest-first, all in Python for the same
mixed-timestamp reason as `list_queue`); the `ispu_*` and `scheduled` buckets
primarily drive the real-time Live Queue indicator ([doc 22](22-live-queue.md)).

There's still no "complete"/"mark done" action — an assisted walk-in stays
visible in the queue (as "Being helped") for the life of the demo/session
rather than disappearing. See Known limitations.

---

## Frontend

| File | Role |
|---|---|
| `frontend/src/components/ChatWidget.tsx` | Front desk CTA group (Check In + View queue), the inline check-in form, `submitCheckIn()`, `assistFromQueue()` |
| `frontend/src/components/A2UI.tsx` | `QueueCard` / `QueueRow` — renders the `queue` element; disables the Assist affordance on in-progress rows and on `scheduled` rows (which show a purple **Upcoming** pill and a non-clickable **Scheduled** CTA, plus the appointment `when_label`) |
| `frontend/src/api.ts` / `types.ts` | `queue()`, `checkIn()`, `assistQueueEntry()`; `A2UIQueue`, `VISIT_REASONS` |
| `frontend/src/styles.css` | `.checkin-*` (form), `.a2ui-queue-pill--*` (status pills) — both reuse `.confirm-card` / `.a2ui-order` rather than introducing new card chrome |

---

## Known limitations & future work

- **No "complete" action.** Once assisted, an entry has no way back out of
  the queue short of a fresh seed/reset. Add `POST /api/queue/{id}/complete`
  (`status=completed`, excluded from `list_queue()`) when the demo needs a
  full lifecycle.
- **The A2UI card is still point-in-time.** The `queue` card is a snapshot
  fetched on tap, like every other A2UI card — a second rep's check-in or
  assist won't appear until it's re-opened. The topbar **Live Queue**
  indicator ([doc 22](22-live-queue.md)) closes this gap for the floor at
  large: it polls `GET /api/queue/live` every 20s and opens a drawer with the
  full bucketed snapshot. Wiring an SSE channel (same pattern as
  [System Health](13-system-health.md) / [Production Monitor](14-production-monitoring.md))
  would push updates into the card itself.
- **No dedupe.** Nothing stops the same phone number from being checked in
  twice; a real deployment would want to warn on an existing waiting entry
  for the same customer.
- **Seed data is illustrative, not scaled.** Unlike engagements/tickets/LLM
  calls (seeded across the full date range), queue entries are a small fixed
  set of 11 recent-timestamp fixtures — 2 waiting, 2 being assisted, 2
  `ispu_to_pick`, 2 `ispu_ready`, and 3 `scheduled` appointments (each with a
  minutes-from-now offset) — because a live front-desk queue only makes sense
  as "right now" state. Seeded from `_QUEUE_SAMPLES` in
  [`admin.py`](../backend/app/api/admin.py) (the deployed `POST /api/admin/seed`
  reseed, reported under `queue_entries`) and the matching `QUEUE_SAMPLES` in
  [`seed_demo.py`](../backend/scripts/seed_demo.py).
