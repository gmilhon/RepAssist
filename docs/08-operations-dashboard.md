# Operations & KPI Dashboard

The **Operations** tab is the single pane of glass for running Rep Assist: how
much it's used, how much it deflects, where it escalates, and what to fix next.
Every KPI is computed from real interaction events — nothing is hard-coded.

Code: events [`store/models.py` `Engagement`](../backend/app/store/models.py),
aggregation [`store/db.py` `metrics_overview()`](../backend/app/store/db.py), API
[`api/metrics.py`](../backend/app/api/metrics.py), UI
[`components/OperationsDashboard.tsx`](../frontend/src/components/OperationsDashboard.tsx).

## How it's measured

The orchestrator writes one `Engagement` row per interaction — a chat turn
(`message`) or a confirmation (`confirmation`) — capturing intent, confidence,
status, resolution status, the resolving capability, the confirm decision, and
any ticket id. This is emitted in `orchestrator.start_or_continue` / `resume` and
is **best-effort** (analytics never breaks the chat path). KPIs are aggregated
from these events plus the `Ticket` table.

## KPIs on the dashboard

| Group | Metric | Definition |
|---|---|---|
| **Engagement** | Conversations | distinct threads |
| | Interactions | total chat turns |
| | Active reps | distinct rep ids |
| | Avg triage confidence | mean classifier confidence |
| **Outcomes** | **Containment rate** | auto-resolved ÷ (resolved + escalated + declined) — the headline deflection KPI |
| | Escalation rate | escalated ÷ terminal outcomes |
| | Declined fixes | rep declined a proposed change |
| **Human-in-the-loop** | Confirm approval rate | approved ÷ (approved + declined) confirmations |
| **By intent** | Volume + containment per intent | where the agent is strong/weak |
| **Capabilities** | Top resolving agents | auto-resolutions by capability |
| **Desk health** | Open / In-review / Resolved / Closed | ticket queue state |
| | Avg resolution time | mean hours from ticket open → resolved |
| **Improvement** | Capability backlog | ranked "what to build next" (from resolved-ticket feedback) |
| **Trend** | Interactions over time | resolved vs escalated per day |

## API

```
GET /api/metrics/overview
→ { engagement, outcomes, confirmations, intents[], capabilities[],
    tickets{...}, timeseries[] }
```

The frontend renders this directly; the same endpoint can feed a BI tool
(Grafana/Looker) in production.

## Populate it with demo data

The dashboard is live, so a fresh database starts empty. Seed ~10 days of
realistic interactions + tickets + feedback:

```bash
cd backend && . .venv/bin/activate
python scripts/seed_demo.py      # deterministic; safe to re-run (resets first)
```

Then open the **Operations** tab. (Real usage from the chat UI accumulates into
the same KPIs automatically.)

## KPI targets to set for a pilot

These are the numbers to watch and agree on with the business before go-live:

- **Containment rate** — primary success metric; trend it up as you ship agents
  from the capability backlog.
- **Escalation rate** + **avg resolution time** — the human-side cost you're
  trying to reduce.
- **Confirm approval rate** — low approval (reps declining) is an early warning
  that an agent proposes bad fixes; investigate before raising automation.
- **Reversal rate** (future) — declined/rolled-back changes; gate any
  auto-approval on keeping this near zero. See
  [Feedback & Continuous Improvement](04-feedback-and-continuous-improvement.md).
