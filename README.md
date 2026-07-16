# Rep Assist — Conversational Assisted Sales & Service for Retail Reps

Rep Assist is a conversational **Assisted Sales & Service** assistant embedded in
the retail sales application. A retail rep describes an order or service problem
in plain language; a **LangGraph orchestrator** triages it, routes it to the right
existing agent (Activation Resolver, Promo Correction Agent, Pending Order
Resolver, …), confirms any account-changing action with the rep, and — when no
agent or knowledge can solve it — opens a **human-in-the-loop ticket** that
replaces ServiceNow. Tier 1/2 specialists resolve those tickets and leave
structured feedback that becomes a **prioritized backlog of agents/skills** the
dev team should build next, so the assistant keeps getting better.

> This repository is a **runnable reference implementation**: a real LangGraph
> orchestrator, a rep chat UI, the Tier 1/2 resolution desk, mocked "existing
> agent" microservices, and a feedback/analytics loop. It runs locally with
> **zero credentials** (deterministic mock LLM) and lights up real Claude
> reasoning the moment you add an `ANTHROPIC_API_KEY`.

---

## What's in the box

| Layer | Tech | Folder |
|---|---|---|
| Rep chat UI + Tier 1/2 desk + dashboards | React + Vite + TypeScript | [`frontend/`](frontend/) |
| Conversational orchestrator | LangGraph + FastAPI | [`backend/app/graph`](backend/app/graph), [`backend/app/api`](backend/app/api) |
| **A2UI** (agent-to-UI) elements + stubbed MCP layer | FastAPI + React | [`backend/app/mcp`](backend/app/mcp), [`frontend/src/components/A2UI.tsx`](frontend/src/components/A2UI.tsx) |
| "Existing" agents (mocked microservices) | FastAPI | [`backend/app/mock_services`](backend/app/mock_services) |
| HITL ticketing + feedback store (ServiceNow replacement) + **AI Assisted Resolution Desk** (Claude ticket triage → education/agent_action/system_defect, one-click resolution) | SQLite + SQLModel + Claude | [`backend/app/store`](backend/app/store), [`backend/app/api/tickets.py`](backend/app/api/tickets.py) |
| Observability (CX Monitor) + email reports | LangSmith + smtplib | [`backend/app/api/cx.py`](backend/app/api/cx.py), [`backend/app/api/email_reports.py`](backend/app/api/email_reports.py) |
| **Production Monitor** — live escalation inflow, AI issue clustering, alerts, JIRA-stub defects | FastAPI SSE + Claude | [`backend/app/api/production.py`](backend/app/api/production.py), [`frontend/src/components/ProductionDashboard.tsx`](frontend/src/components/ProductionDashboard.tsx) |
| LLM access (Claude + offline fallback) | official `anthropic` SDK | [`backend/app/llm.py`](backend/app/llm.py) |
| Cloud Run deployment (one service, API + UI) | Docker + gcloud | [`deploy.sh`](deploy.sh), [`backend/Dockerfile`](backend/Dockerfile) |
| Architecture, diagrams, runbook, roadmap | Markdown + Mermaid | [`docs/`](docs/) |

## Documentation

1. [Executive Summary](docs/00-executive-summary.md) — the one-pager for leadership.
2. [Solution Architecture](docs/01-solution-architecture.md) — context/container/sequence diagrams, data model, security.
3. [LangGraph Orchestration](docs/02-langgraph-orchestration.md) — the graph, state, nodes, and the human-in-the-loop interrupt.
4. [HITL Ticketing Workflow](docs/03-hitl-ticketing-workflow.md) — how this replaces ServiceNow, plus the AI Assisted Resolution Desk that Claude-classifies the backlog into education / agent_action / system_defect with a one-click resolution per bucket.
5. [Feedback & Continuous Improvement](docs/04-feedback-and-continuous-improvement.md) — turning Tier 1/2 feedback into a dev backlog.
6. [Local Setup Runbook](docs/05-local-setup-runbook.md) — step-by-step to run everything.
7. [Roadmap & What You Need To Do](docs/06-roadmap-and-what-you-need-to-do.md) — productionization plan and your task list.
8. [Real Agent Integration — Worked Example](docs/07-real-agent-integration-example.md) — how to swap a mock for a real, vendor-shaped agent (implemented for Activation).
9. [Operations & KPI Dashboard](docs/08-operations-dashboard.md) — engagement, escalations, resolutions, and all operational KPIs.
10. [CX Monitor — LangSmith Integration](docs/09-cx-monitor.md) — conversation latency, token usage, cost-per-conversation, and live trace explorer.
11. [A2UI — Agent-to-UI Elements](docs/10-a2ui-generative-ui.md) — generative UI in the chat (recent orders) sourced from a stubbed MCP layer.
12. [Email Reports & Settings](docs/11-email-reports.md) — on-demand HTML dashboard reports, subscriber management, SMTP + preview mode.
13. [Deployment — Google Cloud Run](docs/12-deployment-cloud-run.md) — one service serving API + UI, Secret Manager, and synthetic-data seeding.
14. [System Health & Live Notifications](docs/13-system-health.md) — the topbar status badge, operator-set incidents, and real-time SSE toast notifications.
15. [Production Monitor](docs/14-production-monitoring.md) — real-time escalation inflow, AI issue clustering, critical email alerts, and auto-filed JIRA defects (stub MCP).
16. [System Enhancements Generation](docs/15-system-enhancements-generation.md) — the "What's new" card, regenerated from git commit history on every deploy instead of hand-maintained.
17. [Observability](docs/16-observability.md) — conversation health, guardrail integrity (incl. log-only prompt-injection detection), true token economics (cost by intent/outcome), sales-intent segmentation, and a fallback-rate alert wired to System Health, added to CX Monitor.
18. [Reseeding the Deployed Environment](docs/17-reseeding-deployed-data.md) — the exact runbook for repopulating demo data after a deploy, plus a matching Claude Code skill.

## 60-second quickstart

```bash
# 1) Backend deps
cd backend && python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

# 2) Start the existing-agent microservices (mock) + the orchestrator
uvicorn app.mock_services.main:app --port 8100   # terminal A
uvicorn app.main:app --port 8000                 # terminal B

# 3) Frontend
cd ../frontend && npm install && npm run dev      # terminal C  -> http://localhost:5173
```

Open http://localhost:5173. The chat leads with **first-step CTA tiles** (Fix an
activation, Unblock an order, …) that prefill the composer, plus **"Look up"**
tiles that reveal MCP-backed *recent orders* / *open tickets* cards on demand.
Pick one (or just type), then watch the assistant diagnose, ask you to confirm the
fix, and resolve it — or escalate to the Resolution Desk. Full details in the
[runbook](docs/05-local-setup-runbook.md).

> **Go live with Claude:** put `ANTHROPIC_API_KEY=...` in `backend/.env`
> (copy from `.env.example`). With no key, the system runs fully offline using a
> deterministic rule-based classifier so you can demo without credentials.

> **Enable LangSmith tracing:** add `LANGCHAIN_API_KEY=...` (from
> [smith.langchain.com](https://smith.langchain.com)) to `backend/.env`. This
> enables the **CX Monitor** tab — latency percentiles, token usage,
> cost-per-conversation, and a live trace explorer backed by real LangSmith data.
> The tab shows sample data when the key is absent.

> **Deploy to the cloud:** `./deploy.sh` packages the API + built frontend into a
> single **Google Cloud Run** service with secrets in Secret Manager. See
> [Deployment — Google Cloud Run](docs/12-deployment-cloud-run.md).

### The six tabs

| Tab | What it is |
|---|---|
| **Rep Assist** | The conversational chat — first-step CTA tiles + on-demand A2UI recent-orders/open-tickets cards ([doc 10](docs/10-a2ui-generative-ui.md)) |
| **Resolution Desk** | Tier 1/2 ticket queue with AI-assisted triage (education / agent_action / system_defect) and one-click resolution, plus the original resolve/feedback form ([doc 03](docs/03-hitl-ticketing-workflow.md)) |
| **Performance** | Engagement/deflection KPIs + AI exec summary ([doc 08](docs/08-operations-dashboard.md)) |
| **CX Monitor** | LangSmith latency/token/cost telemetry ([doc 09](docs/09-cx-monitor.md)) |
| **Production** | Real-time escalation inflow + AI issue detection, alerts, and defect filing ([doc 14](docs/14-production-monitoring.md)) |
| **Settings** | Email-report subscribers + SMTP status ([doc 11](docs/11-email-reports.md)) |

The Performance and CX Monitor tabs can **email HTML reports** to subscribers
(with an in-browser preview when SMTP isn't configured). The UI is **responsive**
— it works on phones, iPad Mini, and foldables.

A **System Health badge** in the topbar (visible on every tab) shows live
service status; an operator can set it from Settings and optionally push a
real-time toast notification to every rep with the app open. See
[System Health & Live Notifications](docs/13-system-health.md).

## The flow at a glance

```mermaid
flowchart LR
    Rep["🧑‍💼 Rep in sales app"] -->|"describes issue"| Orch["LangGraph<br/>Orchestrator"]
    Orch --> Triage{"Triage:<br/>intent + confidence"}
    Triage -->|activation| A["Activation Resolver"]
    Triage -->|pending order| P["Pending Order Resolver"]
    Triage -->|promo| M["Promo Correction Agent"]
    Triage -->|billing / how-to| K["Knowledge Base"]
    Triage -->|unknown / low conf.| T["🎫 Human Ticket"]
    A & P & M --> Confirm{"Rep confirms<br/>the change?"}
    Confirm -->|yes| Done["✅ Resolved in-app"]
    Confirm -->|no| Done2["No change made"]
    K --> Done
    T --> Desk["🛠️ Tier 1/2 Resolution Desk"]
    Desk -->|"feedback: which agent to build"| Backlog["📊 Capability Backlog<br/>(dev team)"]
    Backlog -.->|"new agents/skills"| Orch
```

## License / status

Internal reference prototype. Not production-hardened — see
[Roadmap & What You Need To Do](docs/06-roadmap-and-what-you-need-to-do.md) for the
gap list before any pilot.
