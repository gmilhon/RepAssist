# Local Setup Runbook

Everything runs locally with **no credentials** (deterministic mock LLM). Add an
`ANTHROPIC_API_KEY` to switch on real Claude reasoning.

## Prerequisites

| Tool | Version used | Notes |
|---|---|---|
| Python | 3.12+ (tested on 3.14) | for the backend |
| Node.js | 20+ (tested on 25) | for the frontend |
| (optional) Anthropic API key | — | enables live Claude; omit to run offline |

## Ports

| Service | Port | Command |
|---|---|---|
| Existing agent services (mock) | 8100 | `uvicorn app.mock_services.main:app --port 8100` |
| Orchestrator API | 8000 | `uvicorn app.main:app --port 8000` |
| Frontend (Vite dev) | 5173 | `npm run dev` (proxies `/api` → 8000) |
| _(optional)_ Sample "real" Activation agent | 8200 | `uvicorn app.sample_agent.main:app --port 8200` — see [doc 07](07-real-agent-integration-example.md) |

## 1. Backend

```bash
cd backend
python3 -m venv .venv
. .venv/bin/activate                 # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# optional: enable live Claude
cp .env.example .env                 # then set ANTHROPIC_API_KEY in .env
```

Start the two backend services in separate terminals (both from `backend/` with
the venv active):

```bash
# terminal A — the "existing" agent microservices (mock)
uvicorn app.mock_services.main:app --port 8100

# terminal B — the orchestrator
uvicorn app.main:app --port 8000
```

Verify:

```bash
curl http://127.0.0.1:8000/health
# {"status":"ok","llm_mode":"mock"|"anthropic","model":...,"agent_services":"http://127.0.0.1:8100"}
```

## 2. Frontend

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173
```

Open http://localhost:5173.

## 3. Try it

The **Rep Assist** tab leads with **first-step CTA tiles** (Fix an activation,
Unblock an order, …) that prefill the composer, plus **"Look up"** tiles that
reveal MCP-backed *recent orders* / *open tickets* cards on demand
([doc 10](10-a2ui-generative-ui.md)). Tap a tile, or type one of these yourself:

| Try this | What happens |
|---|---|
| `Order ACT-1001 is stuck in activation, the SIM won't activate` | Diagnoses → asks you to confirm "resend provisioning" → resolves. |
| `ORD-2002 is blocking the customer's new upgrade order` | Diagnoses a blocking order → confirm "expedite ORD-1990" → resolves. |
| `Account AC-3003 is missing their BOGO promo credit` | Confirm "re-apply BOGO" → resolves. |
| `Account AC-3004 is missing their BOGO promo` | Resolves with **no change** (customer ineligible — promo expired). |
| `Why is the customer's first bill so high?` | Answers from the knowledge base. |
| `Customer wants to rename their smartwatch watch face` | No agent/knowledge → opens a **ticket**. |

Then open the **Resolution Desk** tab, claim the ticket, fill in the resolve
form (set a *recommended agent/skill* and *gap type*), and **Resolve & flag
capability gap**. The **Operations** tab shows it ranked in the capability backlog.

### Populate the Operations dashboard

The **Operations** tab (engagement, escalations, resolutions, and all KPIs) is
live, so a fresh DB starts empty. Seed ~10 days of realistic demo data:

```bash
cd backend && . .venv/bin/activate
python scripts/seed_demo.py      # deterministic; resets + repopulates
```

Real chat usage also accumulates into the same KPIs automatically. See
[Operations & KPI Dashboard](08-operations-dashboard.md).

## 4. Automated checks

```bash
cd backend && . .venv/bin/activate

# offline graph tests (no servers, mock LLM + stubbed agents)
pytest -q

# live end-to-end smoke (requires both backend servers running)
python scripts/smoke.py
```

## Scenario data (mock)

The mock agents key behaviour off ids so demos are repeatable
([`backend/app/mock_services/data.py`](../backend/app/mock_services/data.py)):

| Id | Outcome |
|---|---|
| `ACT-1001` | activation — auto-fixable (re-provision) |
| `ACT-1002` | activation — **not** fixable → ticket |
| `ORD-2002` | pending order — auto-fixable (expedite blocking `ORD-1990`) |
| `ORD-2003` | pending order — credit hold → ticket |
| `AC-3003` | promo — auto-fixable (re-apply BOGO) |
| `AC-3004` | promo — resolved, no change (ineligible) |

## Troubleshooting

| Symptom | Fix |
|---|---|
| `llm_mode: mock` but you set a key | Ensure `.env` is in `backend/` and you restarted `uvicorn` (no `--reload` by default). |
| Chat returns an error about `:8100` | Start the mock services first; check `AGENT_SERVICES_BASE_URL`. |
| Frontend can't reach API | Vite proxies `/api`→`:8000`; confirm the orchestrator is up and `FRONTEND_ORIGIN` matches. |
| `address already in use` on restart | `lsof -ti:8000 \| xargs kill -9` then restart. |
| Reset all data | Stop servers, delete `backend/repassist.db` and `backend/checkpoints.sqlite`, restart. |

## Configuration reference (`backend/.env`)

| Var | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | _(empty)_ | Empty → offline mock LLM. Set → live Claude. |
| `ANTHROPIC_MODEL` | `claude-opus-4-8` | Switch to `claude-sonnet-4-6` / `claude-haiku-4-5` for cost. |
| `AGENT_SERVICES_BASE_URL` | `http://127.0.0.1:8100` | Point at real agent services in production. |
| `TICKETS_DB_URL` | `sqlite:///./repassist.db` | Swap for Postgres in production. |
| `CHECKPOINT_DB` | `./checkpoints.sqlite` | LangGraph conversation state. |
| `TRIAGE_CONFIDENCE_THRESHOLD` | `0.45` | Below this, escalate to a human. |
| `FRONTEND_ORIGIN` | `http://localhost:5173` | CORS allow-list. |
| `LANGCHAIN_API_KEY` | _(empty)_ | Enables LangSmith tracing + the **CX Monitor** tab. See [doc 09](09-cx-monitor.md). |
| `LANGCHAIN_PROJECT` | `rep-assist` | LangSmith project (created on first trace). |
| `SMTP_HOST` / `SMTP_USER` / `SMTP_PASSWORD` / `SMTP_FROM` | _(empty)_ | Enables **email reports**; empty → in-browser preview. See [doc 11](11-email-reports.md). |

> **More capabilities:** [CX Monitor](09-cx-monitor.md) ·
> [A2UI recent orders](10-a2ui-generative-ui.md) ·
> [Email reports & Settings](11-email-reports.md) ·
> [Cloud Run deployment](12-deployment-cloud-run.md).
