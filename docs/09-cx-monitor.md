# CX Monitor — LangSmith Integration

The **CX Monitor** tab gives the product team a real-time window into how the
Rep Assist conversational experience is performing: how fast is the orchestrator
responding, how many tokens each conversation consumes, what that costs, and
whether any conversations are erroring.

The dashboard is fully functional with **zero credentials** — it renders
deterministic sample data that mirrors the realistic patterns used by the YTD
seed script. When a `LANGCHAIN_API_KEY` is present it switches to live
LangSmith data automatically.

Below the LangSmith-sourced KPIs, the dashboard also renders an
**Observability** section — conversation health, guardrail integrity
(including log-only prompt-injection detection), true token economics (cost
by intent/outcome), and sales-intent segmentation — computed from Rep
Assist's own store and available regardless of whether LangSmith is
configured. See [Observability P0](16-observability-p0.md) and
[Observability P1](17-observability-p1.md).

---

## Architecture

```
LangGraph orchestrator              LangSmith (cloud)
  orchestrator.py                     project: rep-assist
    _config(thread_id)   ─trace──►   root run per conversation
      run_name = "rep-assist-conversation"
      LANGCHAIN_TRACING_V2 = true
```

```
FastAPI                              React
  GET /api/cx/overview?start&end  ──►  CXDashboard.tsx
    ↳ langsmith.Client.list_runs        ↳ KPI cards
    ↳ OR deterministic mock             ↳ latency-by-intent bars
                                        ↳ daily timeseries chart
                                        ↳ recent traces table
```

### Auto-tracing

LangGraph instruments itself when these two environment variables are set:

| Variable | Value |
|---|---|
| `LANGCHAIN_TRACING_V2` | `true` |
| `LANGCHAIN_API_KEY` | your LangSmith API key |

`main.py` sets them at startup via `os.environ.setdefault(...)` so they are
always in place before the first `/api/chat` request hits the graph.

Every `graph.invoke()` call creates one root run in LangSmith named
`"rep-assist-conversation"`. Child runs (triage, activation resolver, compose,
…) appear nested underneath in the LangSmith trace explorer.

---

## Configuration

### Minimal (recommended)

```dotenv
# backend/.env
LANGCHAIN_API_KEY=lsv2_...     # from https://smith.langchain.com/settings
LANGCHAIN_PROJECT=rep-assist   # created automatically on first trace
```

### Full (with cost customisation)

```dotenv
LANGCHAIN_API_KEY=lsv2_...
LANGCHAIN_PROJECT=rep-assist
# Adjust these if you switch models — defaults are claude-sonnet-4-6 pricing
LANGSMITH_INPUT_COST_PER_MILLION=3.0
LANGSMITH_OUTPUT_COST_PER_MILLION=15.0
```

See [`backend/.env.example`](../backend/.env.example) for all available
variables.

### Settings object

`backend/app/config.py` exposes:

```python
settings.langsmith_api_key            # LANGCHAIN_API_KEY
settings.langsmith_project            # LANGCHAIN_PROJECT
settings.langsmith_input_cost_per_million
settings.langsmith_output_cost_per_million
settings.langsmith_enabled            # bool — True when key is non-empty
```

---

## API

### `GET /api/cx/overview`

Query parameters: `start` and `end` (YYYY-MM-DD, both optional).

Response shape:

```jsonc
{
  "configured": false,           // true when LANGCHAIN_API_KEY is set
  "langsmith_project": null,     // project name when configured
  "generated_at": "2026-07-10T…",
  "period": { "start": "…", "end": "…" },
  "overview": {
    "conversations": 3213,
    "traces_captured": 0,        // 0 in sample-data mode
    "error_count": 38,
    "error_rate": 0.0118
  },
  "latency_ms": {
    "p50": 1612, "p95": 2981, "p99": 3540, "avg": 1734,
    "by_intent": [
      { "intent": "activation", "avg_ms": 2087, "count": 902 },
      …
    ]
  },
  "tokens": {
    "avg_input": 880, "avg_output": 215, "avg_total": 1095,
    "total_input": 2828160, "total_output": 691230
  },
  "cost_usd": {
    "avg_per_conversation": 0.00586,
    "total": 18.84,
    "model": "claude-opus-4-8",
    "input_rate_per_million": 3.0,
    "output_rate_per_million": 15.0
  },
  "timeseries": [
    { "date": "2026-01-01", "conversations": 32, "avg_latency_ms": 1703, "avg_tokens": 1089, "error_count": 0 },
    …
  ],
  "recent_traces": [
    {
      "id": "mock-2026-07-09-4821",
      "started_at": "2026-07-09T14:22:00+00:00",
      "latency_ms": 1880,
      "input_tokens": 884, "output_tokens": 209, "total_tokens": 1093,
      "error": null,
      "intent": "activation",
      "url": null            // populated with real LangSmith trace URL when configured
    }
  ]
}
```

**Health endpoint** also reflects LangSmith status:

```json
GET /health
{
  "status": "ok",
  "langsmith": { "enabled": true, "project": "rep-assist" }
}
```

---

## Frontend

### Dashboard tab

`App.tsx` adds a **CX Monitor** tab and shows two header pills:
- `LLM: <model>` (green) / `LLM: mock (offline)` (grey)
- `LS: <project>` (green) / `LS: not configured` (grey)

### CXDashboard component

`frontend/src/components/CXDashboard.tsx` renders:

| Section | Detail |
|---|---|
| Status banner | Live (green) or sample-data (amber) with setup hint |
| Date bar | 7D / 1M / 3M / YTD presets + custom date pickers |
| KPI cards (6) | Conversations, P50, P99, Error Rate, Avg Tokens, Avg Cost/Conv |
| Latency by intent | Horizontal bar chart for each intent route |
| Cost breakdown | Input/output rate table with estimated total |
| Daily timeseries | Dual-line SVG chart — conversations + avg latency |
| Recent traces | Table with time, latency, tokens, intent, error snippet, LangSmith link |

### Types

`frontend/src/types.ts` exports `CXOverview` and `CXTrace` matching the
`/api/cx/overview` response exactly.

### API client

```ts
api.cxOverview(start?: string, end?: string) => Promise<CXOverview>
```

---

## Sample data vs live data

| | Sample data (no key) | Live data (key configured) |
|---|---|---|
| `configured` | `false` | `true` |
| Source | Deterministic mock in `cx.py` | `langsmith.Client.list_runs()` |
| Intent breakdown | Populated (mirrors seed weights) | Empty (not in trace metadata by default) |
| LangSmith links | `null` | Deep-link to trace in LangSmith UI |
| Traces captured | 0 | Actual count |

The mock uses the same day-of-week multipliers and post-holiday boosts as
`seed_ytd.py`, so the timeseries chart looks realistic rather than flat.

If LangSmith is configured but the API call fails (network error, expired key,
rate limit), the endpoint falls back to sample data and adds an `"error"` field
to the response. The status banner shows the error message so it is visible in
the UI.

---

## Adding intent metadata to live traces

By default LangSmith traces carry no intent label. To populate the
`by_intent` breakdown in live mode, tag each run with metadata in the
orchestrator node. In `backend/app/graph/nodes.py`, after the intent is
resolved in `triage()`:

```python
from langsmith import traceable  # already available via langsmith package

# Inside the triage node, after intent is determined:
from langchain_core.traceable import get_current_run_tree
run = get_current_run_tree()
if run:
    run.metadata["intent"] = state["intent"]
    run.metadata["confidence"] = state["confidence"]
```

Then in `cx.py`'s `_live_cx_overview`, read `run.metadata.get("intent")` when
building `recent_traces` and the `by_intent` aggregation.

---

## File manifest

| File | Role |
|---|---|
| `backend/app/api/cx.py` | `/api/cx/overview` endpoint — LangSmith SDK + mock fallback |
| `backend/app/config.py` | LangSmith settings block and `langsmith_enabled` property |
| `backend/app/main.py` | Sets `LANGCHAIN_TRACING_V2` / env vars on startup; includes cx router |
| `backend/app/graph/orchestrator.py` | `run_name = "rep-assist-conversation"` in `_config()` |
| `backend/requirements.txt` | `langsmith>=0.1` |
| `backend/.env.example` | LangSmith env var documentation |
| `frontend/src/components/CXDashboard.tsx` | Full CX monitor dashboard component |
| `frontend/src/types.ts` | `CXOverview` and `CXTrace` TypeScript interfaces |
| `frontend/src/api.ts` | `api.cxOverview()` method |
| `frontend/src/App.tsx` | CX Monitor tab + dual header pills |
| `frontend/src/styles.css` | CX dashboard styles (`cx-*` namespace) |
| `backend/app/store/db.py` | `observability_overview()`, `llm_usage_overview()`, `check_fallback_spike()` — see [doc 16](16-observability-p0.md), [doc 17](17-observability-p1.md) |
| `backend/app/llm.py` | `_log_usage()`, `tag_sales_intent()`, `_scan_and_log()` — token-taxonomy capture, sales-intent heuristic, injection scan |
| `backend/app/guardrail.py` | Log-only prompt-injection pattern scanner — see [doc 17](17-observability-p1.md) |
