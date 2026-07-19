# Live Queue — real-time floor snapshot

A rep working a conversation shouldn't have to open a card to know what's
happening on the floor. **Live Queue** is an always-on topbar indicator that
polls the store in the background and shows compact live counts —
walk-ins waiting, customers being assisted, and in-store pickups — updating on
its own every 20 seconds. Tapping it opens a right-side drawer with the full
floor breakdown, including in-store-pickup fulfilment state and today's
still-to-come appointments.

Where the chat **View queue** card ([doc 19](19-store-checkin-queue.md)) is an
*on-demand, walk-in-focused* A2UI snapshot a rep pulls up when they want it,
Live Queue is the *passive, floor-wide* view that's always visible and refreshes
itself. Both read the same `queue_entries` table — Live Queue just buckets every
status, not only waiting/in-progress. It introduces **no new mutation surface**:
it is a read-only `GET`, with no Assist/claim affordance of its own (claiming
still happens from the chat queue card or Live Listen).

---

## What the rep sees

1. A **Live Queue** badge sits in the topbar, in a new `.topbar-right` wrapper
   immediately to the **left** of the System Health badge. It shows three
   compact segments — **N wait · N active · N ISPU** (`counts.waiting`,
   `counts.assisting`, `counts.ispu`) — and refreshes every 20 s without any
   interaction (`setInterval(loadLiveQueue, 20_000)` in `App.tsx`).
2. Clicking the badge opens **`LiveQueuePanel`**, a right-side drawer that
   reuses the same `.hpanel` shell as the System Health panel. **Escape** (or a
   backdrop click) closes it; a **Refresh** button re-polls on demand.
3. The panel opens with four summary stat tiles — **Waiting / Assisting / ISPU /
   Appts** — then the detailed sections below.

---

## Architecture

```
topbar "Live Queue" badge ──► GET /api/queue/live  (poll every 20s)
                                   │
                                   ▼
                          db.live_queue_snapshot()
                                   │  reads queue_entries live, buckets by status:
                                   │   waiting · assisting · ispu_to_pick ·
                                   │   ispu_ready · appointments (future-only)
                                   │  all sorting done in Python
                                   ▼
                          queue.py _serialize(row, now) per bucket
                                   │  id, customer_name/phone, reason(_label),
                                   │  status, order_id, assigned_rep_id, wait_label
                                   │  (+ scheduled_at/scheduled_label/eta_label on appts)
                                   ▼
                          { waiting, assisting, ispu_to_pick, ispu_ready,
                            appointments, counts }
                                   │
              badge segments ◄─────┴─────► LiveQueuePanel drawer (click to open)
              (wait/active/ISPU)            stat tiles + bucketed sections
```

### Why these choices

- **Why a background poll, not SSE.** The queue changes at human, front-desk
  pace, so a 20-second poll is plenty and avoids standing up a second event
  channel. (This is the exact "no live update" gap called out in
  [doc 19](19-store-checkin-queue.md)'s known limitations, closed for the
  topbar view.) System Health, which *does* need push, keeps its SSE stream —
  they poll independently.
- **Why bucket in Python.** `queue_entries` mixes timestamp formats across
  seed/runtime rows, so `live_queue_snapshot()` reads all rows once and sorts
  each bucket in Python — the same rationale as `list_queue()` and
  `create_queue_entry()`. Counts are then derived from the serialized lists in
  `queue.py`, so the badge and the panel can never disagree.
- **Why read-only, with no Assist affordance.** Live Queue is a *monitor*, not
  a controller. Claiming a customer still goes through the chat queue card's
  **Assist** (or Live Listen), which is the single place the queue-assist
  hand-off into a chat thread lives. Keeping claim in one path means Live Queue
  adds nothing new to audit.

---

## The Live Queue panel

`LiveQueuePanel` renders four sections, each with a count chip and an empty
state:

| Section | Bucket(s) | Row hint (right side) |
|---|---|---|
| **Waiting** | `waiting` | `wait_label` · "waiting" |
| **Being assisted** | `assisting` | `wait_label` · the **assigned rep name** (from `assigned_rep_id`, or "in progress") |
| **In-store pickups (ISPU)** | `ispu_to_pick` + `ispu_ready` | `wait_label` · "to pick" / "staged" |
| **Future appointments · today** | `appointments` | `scheduled_label` (e.g. *2:30 PM*) · `eta_label` (e.g. *in 45m*) |

Each row shows the customer's name (falling back to phone, then "Customer"), the
`reason_label`, and a coloured tick keyed to the bucket. The reason line also
carries a secondary identifier — the phone when a named customer also has one,
otherwise the `order_id` (so ISPU rows surface their `ORD-…` number). The **Being assisted**
rows are the only place the panel surfaces *who* is helping — the rep name is
derived client-side from `assigned_rep_id` (`rep.jane_doe` → "Jane doe").

### ISPU two-state lifecycle

In-store pickups are order-driven, not walk-in, and move through two states that
the panel shows as **sub-groups** inside the one ISPU section:

1. **Ready to be picked** (`ispu_to_pick`) — the order is placed but still needs
   pulling off the shelf.
2. **Picked · awaiting customer** (`ispu_ready`) — picked and staged, now
   waiting on the customer to collect.

The ISPU **count** on the badge and stat tile is the *sum* of both sub-groups
(`counts.ispu = ispu_to_pick + ispu_ready`); the two lists stay separate so a
picker can see what's actionable vs. what's just waiting on the customer.

### Future appointments

The **Future appointments · today** section lists only appointments whose
`scheduled_at` is still ahead of *now*, earliest-first — past appointment slots
have effectively become no-shows or already-served walk-ins, so they drop off.
Each row carries a `scheduled_label` (local time of day) and an `eta_label`
(`"in " + <compact elapsed>`), both computed in `queue.py._serialize`.

---

## API — `GET /api/queue/live`

Returns the full floor snapshot: five bucketed lists plus a derived `counts`
object. No parameters; no auth beyond the app's usual.

```jsonc
{
  "waiting": [
    {
      "id": "Q-1A2B3C4D",
      "customer_name": "Devon Marsh",
      "customer_phone": null,
      "reason": "new_service",
      "reason_label": "New Service",
      "status": "waiting",
      "order_id": "ACT-1002",
      "assigned_rep_id": null,
      "wait_label": "6m"
    }
  ],
  "assisting":     [ /* status=in_progress, assigned_rep_id set */ ],
  "ispu_to_pick":  [ /* status=ispu_to_pick */ ],
  "ispu_ready":    [ /* status=ispu_ready */ ],
  "appointments": [
    {
      "id": "Q-9F8E7D6C",
      "customer_name": "Priya Nair",
      "customer_phone": "(555) 019-7781",
      "reason": "appointment",
      "reason_label": "Appointment",
      "status": "scheduled",
      "order_id": null,
      "assigned_rep_id": null,
      "wait_label": "1h 30m",
      "scheduled_at": "2026-07-19T19:30:00+00:00",
      "scheduled_label": "2:30 PM",
      "eta_label": "in 45m"
    }
  ],
  "counts": {
    "waiting": 2,
    "assisting": 2,
    "ispu_to_pick": 2,
    "ispu_ready": 2,
    "ispu": 4,
    "appointments": 3
  }
}
```

Every row carries `id`, `customer_name`, `customer_phone`, `reason`,
`reason_label`, `status`, `order_id`, `assigned_rep_id`, and `wait_label`.
**Scheduled** rows additionally carry `scheduled_at`, `scheduled_label`, and
`eta_label`. `counts.ispu` is the sum of the two ISPU buckets; every other count
is the length of the like-named list.

Code: [`backend/app/api/queue.py`](../backend/app/api/queue.py)
(the `/live` route, `_serialize`, `_elapsed_label`),
[`backend/app/store/db.py`](../backend/app/store/db.py) (`live_queue_snapshot`).
Client call: `api.liveQueue()` → `/api/queue/live` in
[`frontend/src/api.ts`](../frontend/src/api.ts).

---

## Data model

Live Queue reuses `queue_entries` ([doc 19](19-store-checkin-queue.md)) — no new
table. Two additive changes support it:

- **`QueueStatus` gained three values** ([`models.py`](../backend/app/store/models.py)):
  `ispu_to_pick`, `ispu_ready`, and `scheduled`, alongside the existing
  `waiting` and `in_progress`.
- **`QueueEntry.scheduled_at`** — a nullable `datetime` for when a `scheduled`
  appointment is booked (null for walk-in / ISPU rows). Added via an additive
  `ALTER TABLE queue_entries ADD COLUMN scheduled_at DATETIME` migration in
  `db.init_db`, consistent with the other additive migrations there.

`db.live_queue_snapshot()` reads all rows once, buckets them by status, filters
`appointments` to `scheduled_at >= now`, and sorts each bucket in Python
(waiting oldest-first; assisting most-recently-started-first; ISPU oldest-first;
appointments earliest-first).

### Seeding

The demo seed carries **11 queue rows** — 2 `waiting`, 2 `in_progress`, 2
`ispu_to_pick`, 2 `ispu_ready`, and 3 `scheduled` appointments (each with a
minutes-from-now offset so it lands in the future). The set is defined in **both**
[`backend/app/api/admin.py`](../backend/app/api/admin.py) (`_QUEUE_SAMPLES`, used
by `POST /api/admin/seed`) and
[`backend/scripts/seed_demo.py`](../backend/scripts/seed_demo.py)
(`QUEUE_SAMPLES`, used by the local seed script). Because the deployed reseed
(`POST /api/admin/seed`) now includes this queue mock data, its result reports
the row count under `queue_entries` (see [doc 17](17-reseeding-deployed-data.md)).
Account/order ids on the seed rows map to the mock scenario ids so an assisting
rep — or Live Listen — can call agents with the customer's known ids, no clarify
prompt.

---

## Model & Tracing moved into System Health

The Live Queue badge needed topbar room, so the two runtime **pills** that used
to live there — the **LLM** pill and the **LangSmith (LS)** pill — were removed
(the old `.topbar-pills` / `.llm-pill` markup and CSS are gone) and folded into
the **System Health** panel ([doc 13](13-system-health.md)) as a new **Model &
Tracing** section:

- **LLM** — the model id when `llm_mode` is `anthropic`, otherwise
  *"mock (offline)"*.
- **LangSmith** — the project name when tracing is enabled, otherwise
  *"not configured"*.

`HealthPanel` gets this from a new `runtime` prop — the `/health` payload
(`llm_mode`, `model`, `langsmith.enabled`, `langsmith.project`) — which
`App.tsx` passes in as `runtime={health}`. Same information, same offline-vs-live
signal; it just moved from an always-visible pill to inside the health drawer.

---

## Relationship to Store Check-In & Queue (doc 19)

Live Queue and the chat **View queue** card are two views over the same
`queue_entries` table, with different jobs:

| | Chat "View queue" card (doc 19) | Live Queue (this doc) |
|---|---|---|
| Trigger | Rep taps **View queue**; point-in-time | Always-on topbar badge; polls every 20 s |
| Scope | Walk-ins (waiting + in-progress) + today's appointments appended | Every bucket — waiting, assisting, ISPU (both states), appointments |
| Render | A2UI `queue` card ([doc 10](10-a2ui-generative-ui.md)) | Dedicated `LiveQueuePanel` drawer |
| Actions | **Assist →** claims a waiting row | None — read-only monitor |

The shared `QueueStatus`/`scheduled_at` changes also let the doc-19 chat card
append today's future appointments as `scheduled` rows (a purple **Upcoming**
pill with a non-clickable **Scheduled** CTA, and a subtitle like
*"2 waiting · 3 upcoming appts"*) — see [doc 19](19-store-checkin-queue.md).

---

## Frontend

| File | Role |
|---|---|
| `frontend/src/App.tsx` | The `Live Queue` badge in `.topbar-right`, the 20 s poll (`loadLiveQueue` / `queuePollRef`), `refreshLiveQueue`, and mounting `LiveQueuePanel`; passes `runtime={health}` into `HealthPanel` |
| `frontend/src/components/LiveQueuePanel.tsx` | The drawer: summary stat tiles, the four bucketed sections, the ISPU sub-groups, the rep-name derivation, Refresh + Escape-to-close |
| `frontend/src/components/HealthPanel.tsx` | The new **Model & Tracing** section (LLM + LangSmith rows), rendered from the `runtime` prop |
| `frontend/src/api.ts` / `types.ts` | `liveQueue()`; `LiveQueueEntry`, `LiveQueueCounts`, `LiveQueueSnapshot` |
| `frontend/src/styles.css` | `.queue-badge*`, `.lq-*` (panel), reusing the `.hpanel` shell rather than new drawer chrome |

---

## Known limitations & future work

- **Poll, not push.** The badge is at most 20 s stale (or immediate via
  Refresh). A busy multi-terminal floor would still benefit from an SSE channel
  like System Health, but the poll is intentionally simple for the demo.
- **No claim from the panel.** Live Queue is deliberately read-only; to start
  helping someone a rep uses the chat queue card or Live Listen. Adding an
  Assist affordance here would mean threading the claim/hand-off (and its chat
  thread) through the panel.
- **ISPU/appointment state is seed-driven.** There's no UI to *advance* a pickup
  from `ispu_to_pick` → `ispu_ready`, or to book an appointment — those rows come
  from the seed. A real deployment would drive them from the order/appointment
  systems.
- **Past appointments simply vanish.** `scheduled_at < now` rows drop out of the
  snapshot with no "missed / no-show" bucket; a production build would likely
  track and surface those.
