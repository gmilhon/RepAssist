# Observability P0 — Beyond Latency & Cost

CX Monitor originally answered *how fast* and *what it cost, on average* —
LangSmith latency/token/cost telemetry only. This closes the P0 tier of a
Field Ops / XO / SRE observability proposal (reviewed and approved, not
checked into the repo as a doc): conversation health, guardrail integrity,
true token economics, and sales-intent segmentation, computed from Rep
Assist's own store, independent of LangSmith.

P0 was scoped specifically to items that reuse data already captured or need
no policy decision — nothing here required an answer to the proposal's six
open questions. **P1/P2** (per-node cost breakdown, prompt-injection
detection, PII/PCI classification, cache-hit validation, a dedicated
Guardrail & Sales-Intent panel) remain pending those decisions.

---

## What shipped

| Domain | Metric | Source |
|---|---|---|
| **Conversation health** | Turns/conversation (P50/P90/P99) | `Engagement` rows grouped by `thread_id` — already captured, just never aggregated |
| | Looping conversations (>6 turns, unresolved) | same |
| | Confirmation reversal rate | `Engagement.confirmed` — already captured |
| | Out-of-scope rate + trend | `Engagement.intent == "other"` share, recent vs. prior half of window |
| **Guardrail integrity** | Unconfirmed-mutation count | New `ActionAudit` table — one row per `agents_client.execute()` call |
| **True token economics** | Full taxonomy: input, output, thinking, cache write/read | New `LLMCall` table — captured from `resp.usage` on every Anthropic call |
| | Cost of failure | `LLMCall.cost_usd` summed for threads that ended `escalated` |
| | Fallback-to-mock rate, per function | `LLMCall.fallback` — one row per call attempt, live or degraded |
| **Sales-intent segmentation** | NSE / AAL / UP breakdown | New `sales_intent` field, heuristic-tagged in `triage()` |

---

## Conversation health & guardrail

`db.observability_overview(start, end)` computes all of this from `Engagement`
and the new `ActionAudit` table — no new capture for turns or confirmation
reversal, both were already sitting in the store unaggregated.

**The guardrail invariant is a genuine structural guarantee, not a gap
being closed.** There is exactly one `agents_client.execute()` call site in
the whole app ([`graph/nodes.py:confirm`](../backend/app/graph/nodes.py)),
and it is unreachable without the `interrupt()`/approval check immediately
above it — the graph cannot construct a path around it today. `ActionAudit`
exists as **continuous proof** of that invariant (defense-in-depth against a
future refactor breaking it) and as the audit trail Trust & Safety /
compliance would expect for every executed action. `unconfirmed_mutation_count`
should always read zero; a nonzero value is a real incident, not noise.

---

## True token economics

Every Anthropic call goes through `llm._log_usage()`
([`backend/app/llm.py`](../backend/app/llm.py)), which reads the full
taxonomy directly off `resp.usage`:

```python
resp.usage.input_tokens
resp.usage.output_tokens                        # inclusive of thinking — billing-authoritative
resp.usage.output_tokens_details.thinking_tokens # subset of output_tokens spent on reasoning
resp.usage.cache_creation_input_tokens
resp.usage.cache_read_input_tokens
```

This is exactly the blind spot that caused the [System Enhancements
truncation bug](15-system-enhancements-generation.md) — a thinking block
consumed budget invisibly, and nothing surfaced it. `_log_usage()` is called
on every path (success, live failure → fallback, and no-API-key → fallback)
so `LLMCall.fallback` gives a real fallback-to-mock rate per function instead
of a scattered `logger.warning` nobody's watching.

**Cost model.** Anthropic doesn't return line-item cache pricing on the
response, so cache writes are approximated at 1.25× the base input rate
(5-minute TTL) and cache reads at 0.1× — documented, not exact; revisit if
cache usage becomes material.

**Instrumented functions:** `classify`, `compose` (both conversational,
carry a `thread_id`), `executive_summary`, `production_analysis`,
`enhancements` (all background/admin, `thread_id=None`).

---

## Sales-intent segmentation

`llm.tag_sales_intent()` is a **deterministic keyword heuristic**, not an
LLM classifier — a second model call per turn was too expensive for a P0
signal, and reps rarely narrate their own sales motion explicitly anyway.
It ships only the three codes confirmed in the observability proposal:

| Code | Motion |
|---|---|
| `nse` | New Service & Equipment |
| `aal` | Add a Line |
| `up` | Upgrade |

Everything else stays `unclassified` rather than guessing — the proposal's
other four candidate codes (Retention, Port-in, Plan Change, Accessory
Attach) are **not** implemented pending validation (open question #1).

**This is a first-pass, low-precision signal.** Validate against real
order/account "is this a new customer / new line / device swap" data before
using it for reporting decisions — see the caveat rendered directly on the
CX Monitor dashboard's Sales-Intent Breakdown card.

The tag is sticky across a thread (`llm.tag_sales_intent(text) or
state.get("sales_intent")`) since a rep rarely repeats "add a line" every
message, and flows through to both `Engagement.sales_intent` and
`Ticket.sales_intent`.

---

## API

`GET /api/cx/overview` gained two new top-level keys, computed independent of
whether LangSmith is configured (present in mock, live, and error-fallback
response shapes alike):

```jsonc
{
  // ...existing latency/tokens/cost_usd/timeseries...
  "observability": {
    "conversation_health": {
      "turns_per_conversation": { "p50": 1, "p90": 2, "p99": 6, "conversations_measured": 25573 },
      "looping_threshold": 6,
      "looping_conversations": 0,
      "confirmation_reversal_rate": 0.117,
      "out_of_scope_rate": 0.07,
      "out_of_scope_trend": "up 1% vs. prior half of window"
    },
    "sales_intent": [
      { "sales_intent": "nse", "count": 2440, "auto_resolved": 1706, "escalated": 706,
        "avg_confidence": 0.857, "containment_rate": 0.699 }
    ],
    "guardrail": {
      "actions_executed": 13620,
      "unconfirmed_mutation_count": 0,
      "unconfirmed_mutation_examples": []
    }
  },
  "llm_usage": {
    "calls_recorded": 313606,
    "token_taxonomy": { "avg_input": 763, "avg_output": 74, "avg_thinking": 2, "..." : "..." },
    "cost_usd": { "total": 1064.69, "avg_per_call": 0.0034, "cost_of_failure": 303.15, "cost_of_failure_pct": 0.285 },
    "by_function": [
      { "function": "classify", "calls": 156803, "fallback_calls": 2337, "fallback_rate": 0.015, "..." : "..." }
    ]
  }
}
```

Code: [`backend/app/api/cx.py`](../backend/app/api/cx.py) (`_with_observability`),
[`backend/app/store/db.py`](../backend/app/store/db.py)
(`observability_overview`, `llm_usage_overview`).

---

## Data model

| Table | Purpose |
|---|---|
| `llm_calls` | One row per Anthropic call attempt — full token taxonomy, cost, success/fallback |
| `action_audit` | One row per executed mutation — the confirm-gate audit trail |

`engagement` and `ticket` both gained a nullable `sales_intent` column (best-effort
`ALTER TABLE` in `db.init_db()`, same pattern as prior migrations).

---

## Drive-by fix: ticket/issue ID collision risk

Building this surfaced a real, pre-existing bug: `Ticket.id` and
`ProductionIssue.id` used only 8 hex characters (32 bits) of a UUID4. At tens
of thousands of rows, the birthday-paradox collision probability is
significant — seeding this feature's demo data hit exactly this, crashing
with `UNIQUE constraint failed: ticket.id`. Widened to 12 hex characters (48
bits) in [`store/models.py`](../backend/app/store/models.py) and the seed
script — collision probability at that volume is now negligible (~0.0004%
instead of ~25–30%).

---

## Frontend

| File | Role |
|---|---|
| `frontend/src/components/CXDashboard.tsx` | New sections: conversation-health KPI row, guardrail banner, sales-intent bars, full token-taxonomy table, fallback-rate table |
| `frontend/src/types.ts` | `ObservabilityOverview`, `LLMUsageOverview` |
| `backend/app/api/admin.py` | Seed job extended to populate `llm_calls`, `action_audit`, and `sales_intent` so the deployed demo isn't empty in the new sections |

---

## What's still pending (P1/P2)

Blocked on the observability proposal's open questions, not on effort:

- **Cost per graph node** (P1) — needs per-node LangSmith metadata tagging, not just per-conversation.
- **Direct + indirect prompt-injection detection** (P1) — needs a decision on log-only vs. block.
- **Re-ask / abandonment / repeat-contact rates** (P1) — straightforward, just not built this pass.
- **PII/PCI pattern detection** (P2) — compliance sign-off needed before design, not just before ship.
- **Cache-hit $ validation, cost-by-model routing** (P2) — blocked on prompt caching / multi-model routing actually landing.
- **Dedicated Guardrail & Sales-Intent panel** (P1/P2) — today's P0 signals live inside CX Monitor; a standalone panel (reusing the Production Monitor SSE pattern) was proposed but not built.
