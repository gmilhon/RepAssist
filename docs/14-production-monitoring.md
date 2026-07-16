# Production Monitor — Real-Time Issue Detection & Alerting

When the agents can't resolve an issue it escalates to the Resolution Desk — and
a burst of similar escalations usually means something is broken **in
production**: the payment gateway, ETNI (telephone number inventory),
activation/provisioning, the promo engine. The **Production** tab watches that
inflow in real time, uses **AI analysis** to cluster it into systemic issues,
and acts on what it finds:

| Severity | Criteria | Action |
|---|---|---|
| **Critical** | Order-blocking + a burst of related tickets | Red dashboard card + **email alert** with problem statement and recommended fix |
| **Non-critical** | Recurring theme, orders still completing | **Defect filed** on the JIRA board (stub MCP) with problem, fix, and per-ticket examples |

---

## User flow

1. **Production tab** — live KPIs (escalations/24h, this hour vs last, active
   critical issues, defects filed), an hourly **inflow chart**, and a **live
   escalation feed** that updates over SSE the moment an agent escalates.
2. **Analysis** runs two ways:
   - **Automatically** — after every `5` new escalations since the last pass
     (burst detection), and
   - **On demand** — the **🔎 Analyze now** button.
3. **Critical issues** render as red cards: category chip (Payment / ETNI /
   Activation / Backend), `ORDER-BLOCKING` badge, AI-written problem statement
   and recommended fix, the affected ticket list, and the alert-email status.
   **Mark resolved** retires the card into history.
4. **Non-critical themes** render as amber cards and automatically file a
   defect (e.g. `REP-1401`) on the **Defect board** below — click a row to see
   the full JIRA-formatted body.
5. **⚡ Simulate incident** (demo) injects a realistic burst of escalations —
   `ETNI outage`, `Payment gateway`, `Activation failures`, or
   `Promo misses (non-critical)` — so the whole loop can be exercised without
   driving dozens of chat conversations.

---

## Architecture

```
graph escalation                     Production Monitor (api/production.py)
  ticket_fallback ──────────────►      notify_ticket_created(ticket)
    (creates Ticket)                     ├─ SSE broadcast "ticket_created" ──► dashboard feed
                                         └─ burst counter ≥ 5 → background analysis

  POST /analyze  ─────────────►        _run_analysis()
  (dashboard button)                     ├─ collect tickets (last 48h, cap 80)
                                         ├─ llm.analyze_production_issues(...)  ── Claude structured
                                         │    └─ offline fallback: keyword clustering
                                         ├─ upsert ProductionIssue (dedupe by category)
                                         ├─ critical  → email_reports.send_production_alert(...)
                                         ├─ non-crit  → MCP jira.create_issue(...)  (stub board)
                                         └─ SSE broadcast "analysis_complete"
```

- **AI analysis** ([`llm.analyze_production_issues`](../backend/app/llm.py))
  sends the ticket briefs to Claude with a structured-output schema
  (`ProductionAnalysis` in [`schemas.py`](../backend/app/schemas.py)):
  title, category, severity, order-blocking flag, problem statement,
  recommended fix, member ticket ids. Ticket ids are validated against the
  input; clusters need 2+ tickets. **Offline fallback** is deterministic
  keyword clustering (ETNI/payment/activation/promo/billing) with canned
  problem/fix copy — same zero-credential guarantee as the rest of the LLM layer.
- **Dedupe / upsert.** One active `ProductionIssue` per category: re-analysis
  merges ticket ids and refreshes the copy instead of duplicating cards, emails,
  or defects. An issue upgraded non-critical → critical re-triggers the alert.
- **Email alerts** reuse the report SMTP machinery
  ([`email_reports.send_production_alert`](../backend/app/api/email_reports.py)):
  sent to subscribers with the **Alerts** subscription (Settings tab); without
  SMTP or subscribers the dashboard shows the alert **preview** inline instead.
  Alert body: red banner, problem, recommended fix, affected-ticket table.
- **JIRA stub MCP** ([`mcp/jira_stub.py`](../backend/app/mcp/jira_stub.py))
  exposes `create_issue` / `list_issues` / `get_issue` / `attach_ticket` with
  the tool shape a real MCP JIRA server would have; defects persist in SQLite
  (`jira_defects`). The defect description carries `h2. Problem`,
  `h2. Recommended Fix`, and `h2. Escalated Ticket Examples` with one entry
  per ticket (id, time, rep, priority, intent, summary). `attach_ticket`
  appends to an existing defect's `ticket_ids` instead of creating a
  duplicate — it's the same board the AI Assisted Resolution Desk's
  file/attach-defect action ([doc 03](03-hitl-ticketing-workflow.md#ai-assisted-resolution-desk))
  writes to, so a defect can now originate from either an automatic
  Production Monitor cluster or a Tier 1/2 rep resolving a ticket, and
  accumulate tickets from both sources over its lifetime.
- **SSE** (`GET /api/production/events`) uses the same pattern as
  [System Health](13-system-health.md), with one addition: escalations are
  created on **worker threads** (sync graph nodes), so the broadcast hops onto
  each subscriber's event loop via `loop.call_soon_threadsafe`. The dashboard
  also polls the overview every 60s as the self-healing fallback.

---

## API

| Method & path | Purpose |
|---|---|
| `GET /api/production/overview` | KPIs, hourly inflow buckets (24h), recent escalations, issues, monitor state |
| `GET /api/production/events` | SSE: `ticket_created`, `analysis_complete`, `issue_resolved` |
| `POST /api/production/analyze` | Run an analysis pass now (returns findings, alert results, new defect keys) |
| `POST /api/production/issues/{id}/resolve` | Retire an issue into history |
| `GET /api/production/defects` | The stub JIRA board (via MCP `jira.list_issues`) |
| `POST /api/production/simulate` | DEMO: inject a scenario burst — `{"scenario": "etni" \| "payment" \| "activation" \| "promo"}` |

Code: [`backend/app/api/production.py`](../backend/app/api/production.py).

---

## Data model

| Table | Purpose |
|---|---|
| `production_issues` | Detected issues: severity, category, title, problem/fix, ticket ids, status, `alert_sent`, `defect_key` |
| `jira_defects` | The stub JIRA board: key (`REP-14xx`), summary, description, priority, labels, status, `ticket_ids` (originating tickets — can grow over time as more tickets are attached) |

`email_subscribers` gained `subscribed_alerts` (Settings tab shows an
**Alerts** toggle per subscriber; added via a best-effort `ALTER TABLE` in
`db.init_db()` for pre-existing databases).

---

## Frontend

| File | Role |
|---|---|
| `frontend/src/components/ProductionDashboard.tsx` | The whole tab: KPIs, chart, live feed, issue cards, defect board, simulate/analyze controls |
| `frontend/src/App.tsx` | Sixth tab: **Production** |
| `frontend/src/api.ts` / `types.ts` | `production*` endpoints and types |
| `frontend/vite.config.ts` | Dedicated SSE proxy entry for `/api/production/events` (see the [dev-proxy note](13-system-health.md#dev-proxy-note-sse--vite)) |

---

## Production notes

- **Auth.** Like the rest of the prototype these endpoints are unauthenticated;
  gate them (especially `/simulate`) behind SSO before pilot.
- **Multi-instance.** SSE subscribers and the burst counter are in-process —
  same single-instance assumption as [System Health](13-system-health.md) and
  the SQLite store; use shared pub/sub + a shared counter when scaling out.
- **Signal quality.** The analysis prompt caps at 80 tickets over 48h. For real
  volumes, feed it pre-aggregated clusters (embedding similarity or intent+error
  code grouping) rather than raw tickets, and tune the burst threshold per
  category.
- **Paging.** Email is the only alert channel today; wire
  `send_production_alert` into PagerDuty/Slack MCP tools for on-call routing.
