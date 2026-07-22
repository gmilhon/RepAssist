# Field Dashboards — Store Manager, District & Territory Rollups

Rep Assist has always been built for the person **on the floor**. These three
dashboards are built for the people **above** them — the leaders who run a store,
a district, and a territory — giving each a consolidated operating picture
pitched at their span of control and their review cadence, topped with a
GenAI brief written for their job.

| View | Nav (☰ → **Field**) | Audience | Cadence | AI brief focuses on |
|---|---|---|---|---|
| 🏪 **Store Manager** | Store Manager | Store lead | Live / today | What to do **right now** (ranked priorities) |
| 🗺️ **District** | District (DM) | District Manager | **Daily** touch-base | **Outlier management** across the district's stores |
| 🌎 **Territory** | Territory (Director) | Director | **Weekly** review | **Outlier management** across the territory's districts |

All three are synthetic-but-coherent: there is no real WFM / HR / inventory /
sales-datamart behind the prototype, but every number is internally consistent
and the levels **roll up into each other** (see [The org hierarchy](#the-org-hierarchy)).
Each dashboard's brief is a live Claude call with a deterministic **offline-safe
fallback** — the same zero-credential guarantee as the rest of the LLM layer.

---

## The org hierarchy

One org model runs through every view, so drilling up or down never contradicts
the level you came from:

```
Greater Metro (market, ~140 stores)
└─ North Territory ............ Director: Elena Vasquez ...... 6 districts / 54 stores
   └─ District 7 .............. DM: Marcus Webb .............. 9 stores
      └─ Riverside Commons #4 .. Mgr: Jordan Ellis ............ R-4821  ← the single-store view
```

That makes the store's own ranking card read **District #4 of 9 · Territory #14
of 54 · Market #38 of 140** — a store's rank widens as the scope widens, which
only works if the counts nest correctly.

**Coherence by construction.** Riverside Commons appears as a row in the district
rollup and (via its district) in the territory rollup. Its operational fields
there — coverage, on-floor headcount, ops-alert count, at-risk deals — are pulled
**live** from the same `store_manager_data.build_overview()` the single-store view
renders, through `rollup_data._live_riverside()`. So if the store view says
Riverside has a 6 PM coverage gap, the district leaderboard says the same thing.
The other eight stores and five districts are seeded tables.

---

## Store Manager (🏪) — the store's day

The store lead's home screen. Five sections under a GenAI brief:

1. **✦ Manager Brief** — a headline, **3–5 ranked priorities** (each tagged
   `NOW` / `TODAY` / `WATCH` and staffing/sales/ops), and three focus columns
   (Right Now · Staffing / Sales Focus / Operations).
2. **Staffing & Live Floor** — the day's roster grouped **openers → mid →
   closers** with live status (on floor / lunch / scheduled / done), a
   **"needs a break"** flag (worked 5h+ with no meal), coming-in-later and
   closers counts — plus the **live floor** panel (see [Live floor](#live-floor)).
3. **Traffic Forecast** — an hour-by-hour column chart of expected walk-ins
   (split into walk-ins vs. booked appointments+pickups) against **floor
   coverage**, with understaffed hours flagged red, the current hour ringed, and
   a "flex a break or call in coverage before the peak" callout.
4. **Sales Performance** — territory/district/market **rankings** with trend,
   MTD **target bars** (PGA, Upgrades, Mobile+Home, Perk Attach, Premium Mix,
   Pull-Through) each graded **ahead / on / behind** with a focus hint, and a
   **high-priority (at-risk) upgrades** list (churn-risk, upgrade-eligible
   customers with CLV).
5. **Operations** — inbound shipments, device exchanges to return (RMA aging),
   **unpicked pickups** (call-before-auto-cancel), planogram changes, device
   launches, training compliance and open positions.

### Live floor

The part a manager acts on minute-to-minute: **who is with a customer right
now, and where a deal needs help.** Each active engagement card shows:

- the rep and customer, the visit reason, the stage (browsing → quoting →
  building cart → checkout → signature) and how long they've been engaged;
- **opportunity vs. cart** — a bar filling the current cart value against the
  full opportunity, with the **"$ on the table"** gap called out;
- the specific **attach gaps** (e.g. *"2nd eligible line not added,"
  "Protection declined"*); and
- a **risk-to-close** flag — `NEEDS HELP` (high) / `WATCH` / `ON TRACK` —
  so the manager knows exactly which conversation to walk over to.

Only reps who are **currently on the floor** surface here; engagements are
modeled in `store_manager_data._ENGAGEMENTS`, sorted riskiest-and-largest-gap
first, and the risk count rolls up into the "With customers · N need help" KPI.

### The effective store clock

Every staffing state, break time and traffic gap derives from **one** store-local
clock, `store_manager_data._effective_now()`. Two things matter about it:

- **Coherence.** Because a single "now" drives everything, the view is never
  self-contradictory — the person shown "on lunch until 1:45" is excluded from
  that hour's floor-coverage count, and "needs a break" only lights up for
  someone who has actually worked 5h+ without a meal.
- **Always mid-shift for demos.** The container may run in UTC (Cloud Run) or
  any local zone. When the real store-local time is **outside business hours**,
  the clock **wraps to ~1:24 PM** so the dashboard always reads as a live,
  busy mid-afternoon store rather than an empty closed one.

---

## District rollup (🗺️, DM) — daily

The District Manager touches base with each store manager **every day**, so this
view is operational and act-today. It answers "where do I spend my morning?"

- **KPIs** — district composite index (+ pace), stores behind plan, coverage
  gaps today, live deals at risk, open ops alerts, forecast traffic.
- **Store leaderboard** — all 9 stores ranked by **scorecard index** (100 = on
  plan), each with PGA / Upgrades / Mobile+Home attainment, coverage badge
  (OK / Thin / Gap), ops alerts, at-risk deals and short **focus flags**. The
  manager's **home store is highlighted** ("Your store").
- **Outlier callouts** — two lists: **Needs a touch-base today** (the lagging
  stores, red) and **Model stores to learn from** (the leaders, green).
- **AI brief** — see [Outlier-management briefs](#outlier-management-briefs).
  Daily framing, `NOW` / `TODAY` urgencies, named down to the store manager
  ("Get Victor Cho on the phone now," "borrow a rep from Oakdale Center").

---

## Territory rollup (🌎, Director) — weekly

The Director reviews **weekly**, so this view is strategic and trend-oriented.
It answers "which district needs my attention this week, and what's working that
I can spread?"

- **KPIs** — territory composite index (+ pace), **week-over-week** index move,
  districts behind plan, red-flag stores territory-wide, training compliance,
  open-role pipeline.
- **District rollup** — all 6 districts ranked by index, each with store count,
  **WoW trend arrow**, red-store count, and its **top / bottom store**. The
  home district (District 7) is highlighted.
- **Outlier callouts** — **Sliding — Director's focus this week** (districts
  losing ground) vs. **Surging — study & replicate** (districts gaining).
- **AI brief** — weekly framing, `THIS WEEK` / `WATCH` urgencies, pitched at the
  Director's altitude ("needs a territory-level intervention this week, not just
  DM-level fixes," "codify and export District 22's playbook").

The weakest single store *anywhere* in the territory is also surfaced, because a
crisis store can hide inside an average-looking district.

---

## Outlier-management briefs

Two brief shapes, both live-Claude-with-offline-fallback, both structured output
([`schemas.py`](../backend/app/schemas.py)):

| Brief | Schema | Shape |
|---|---|---|
| Store | `StoreManagerBrief` | headline · **priorities** (title/detail/area/urgency) · staffing/sales/operations focus prose |
| District & Territory | `RollupBrief` | headline · **outliers** (name/direction/detail) · **priorities** (title/detail/scope/urgency) · momentum prose |

The store brief is a **prioritized to-do list**. The rollup briefs are built
specifically around **outlier management** — the leadership job of *not* reading
every row, but finding the handful of stores/districts that stand out in **either
direction** (intervene on the ones slipping, replicate the ones surging) and the
few critical areas to focus on. The system prompt tells the model which lens to
use (a DM reviewing daily vs. a Director reviewing weekly) and to match urgency
to that cadence, so the **same** `RollupBrief` schema reads operationally for the
DM and strategically for the Director.

Prompts and the deterministic fallbacks live in
[`llm.py`](../backend/app/llm.py): `generate_store_manager_brief` /
`_mock_store_manager_brief` and `generate_rollup_brief` / `_mock_rollup_brief`.
The mock paths reproduce the same structure (outliers, ranked priorities,
momentum) from the raw numbers so the dashboards are fully usable with **no API
key**.

---

## Architecture

```
store_manager_data.build_overview()          rollup_data.build_district_rollup()
  ├─ _effective_now()  (one store clock)        ├─ _stores_ranked()  (9 stores, ranked)
  ├─ _staffing()  roster + live floor           │    └─ _live_riverside()  ← overlays the
  │    └─ _live_engagements()  opp vs cart       │         home store from the store view
  ├─ _traffic()   forecast vs coverage          └─ KPIs · outliers · leaderboard
  ├─ _sales()     rankings · targets · at-risk
  └─ _operations()                             rollup_data.build_territory_rollup()
                                                  ├─ _district7_summary()  ← rolls the 9
        │                                         │     District-7 stores into a district row
        ▼                                         └─ + 5 seeded districts · WoW · outliers
  api/store_manager.py                         api/rollup.py
   GET /overview        GET /brief ┐            GET /district   GET /district/brief ┐
                                   │            GET /territory  GET /territory/brief│
                                   ▼                                                ▼
                    llm.generate_store_manager_brief          llm.generate_rollup_brief
                      → StoreManagerBrief (Claude)              → RollupBrief (Claude)
                      → offline mock fallback                   → offline mock fallback
        │                                              │
        ▼                                              ▼
  StoreManagerDashboard.tsx                      RollupDashboard.tsx  (level="district" | "territory")
```

The two `*_data.py` modules are pure Python (no DB, no LLM) — they assemble the
snapshot. The `/brief` endpoints call that same builder, hand the snapshot to the
LLM layer, and return the structured brief. This mirrors the Performance
dashboard's executive-summary pattern ([doc 08](08-operations-dashboard.md)).

---

## API

| Method & path | Purpose |
|---|---|
| `GET /api/store-manager/overview` | Full store snapshot: staffing (+ live floor), traffic forecast, sales, operations |
| `GET /api/store-manager/brief` | AI **Manager Brief** for the store (`StoreManagerBrief` + `model`) |
| `GET /api/rollup/district` | Daily district rollup: KPIs, store leaderboard, outliers |
| `GET /api/rollup/district/brief` | AI **outlier-management** brief for the district (`RollupBrief`) |
| `GET /api/rollup/territory` | Weekly territory rollup: KPIs, district rollup, WoW, outliers |
| `GET /api/rollup/territory/brief` | AI **outlier-management** brief for the territory (`RollupBrief`) |

Code: [`api/store_manager.py`](../backend/app/api/store_manager.py),
[`api/rollup.py`](../backend/app/api/rollup.py). All `/brief` responses include
`model` (`"mock"` when running without a key). Briefs are cached client-side for
3 minutes with a **↻ Regenerate** button, so tab switches don't re-hit Claude.

---

## Where the data lives

No new database tables — the field data is **synthetic and in-memory**, assembled
per request. Swapping any section for a real feed means replacing one builder
without touching the API contract or the frontend.

| File | Holds | Real integration seam |
|---|---|---|
| [`store_manager_data.py`](../backend/app/store_manager_data.py) | Store roster (`_ROSTER`), live engagements (`_ENGAGEMENTS`), hourly traffic (`_TRAFFIC`), sales targets & rankings, operations | WFM (staffing), POS/live-cart (floor), volume forecaster (traffic), sales datamart (targets), inventory/RMA (ops) |
| [`rollup_data.py`](../backend/app/rollup_data.py) | District-7 store table (`_STORES`), territory district table (`_OTHER_DISTRICTS`), live Riverside overlay (`_live_riverside`), rollup builders | The sales datamart, keyed by store/district/territory |
| [`schemas.py`](../backend/app/schemas.py) | `StoreManagerBrief`, `StoreManagerPriority`, `RollupBrief`, `RollupOutlier`, `RollupPriority` | — |
| [`llm.py`](../backend/app/llm.py) | Brief prompts + generators + offline mocks | — |

**The composite index.** Stores and districts carry a single **scorecard index
where 100 = on plan/pace** — a blended health number distinct from any one
metric's attainment. It drives ranking, pace (`ahead ≥ 100`, `on ≥ 90`, else
`behind`) and the red/green coloring, so a leader can sort by "who needs me"
without reading six columns per row.

---

## Frontend

| File | Role |
|---|---|
| [`StoreManagerDashboard.tsx`](../frontend/src/components/StoreManagerDashboard.tsx) | The whole store view: brief, staffing + **live floor** cards, traffic chart, sales, operations grid |
| [`RollupDashboard.tsx`](../frontend/src/components/RollupDashboard.tsx) | **Shared** district/territory view, parameterized by `level="district" \| "territory"`: brief, KPIs, ranked table, outlier callouts |
| [`App.tsx`](../frontend/src/App.tsx) | Tabs `store` / `district` / `territory` |
| [`AppDrawer.tsx`](../frontend/src/components/AppDrawer.tsx) | The **Field** nav group |
| [`api.ts`](../frontend/src/api.ts) · [`types.ts`](../frontend/src/types.ts) | `storeManager*` / `districtRollup` / `territoryRollup` endpoints and their types |
| [`styles.css`](../frontend/src/styles.css) | The `sm-*` class block (roster, engagement cards, traffic chart, rollup tables, outlier callouts) |

---

## Production notes

- **Auth & RBAC.** Like the rest of the prototype these endpoints are
  unauthenticated. Before pilot, gate them behind SSO and scope by role — a store
  manager should only see their store, a DM only their district, a Director only
  their territory. Today the org is a fixed constant; that becomes a lookup keyed
  on the signed-in user.
- **Real data is a swap, not a rewrite.** The [data seams](#where-the-data-lives)
  are the whole point: point `_staffing` at the workforce-management API,
  `_traffic` at the volume forecaster, `_sales`/`rollup_data` at the sales
  datamart, `_operations` at inventory/RMA — the dashboards don't change.
- **Live floor.** Today's engagements are mock; wire them to the same live-cart
  / [Live Queue](22-live-queue.md) signals the floor already emits so
  "opportunity vs. cart" reflects the real basket, and the risk flag can be a
  learned model instead of authored rules.
- **Snapshot vs. streaming.** Overview endpoints are pull-per-request (the
  frontend refreshes on demand). For a true live floor, put the engagement +
  coverage deltas on the existing SSE channel ([doc 13](13-system-health.md)).
- **Brief cost.** Each brief is one Claude call, cached 3 min client-side. At
  fleet scale, generate rollup briefs on a schedule (they change per review
  cadence, not per page load) and serve the cached copy.
