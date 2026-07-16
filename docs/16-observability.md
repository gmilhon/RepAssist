# Observability — Conversation Health, Guardrails, Token Economics, Sales-Intent Segmentation

CX Monitor ([doc 09](09-cx-monitor.md)) pairs LangSmith's latency/token/cost
telemetry with an **Observability** section computed entirely from Rep
Assist's own store, independent of whether LangSmith is configured. It
covers four domains: conversation health, guardrail integrity, true token
economics, and sales-intent segmentation.

---

## Conversation health

`db.observability_overview(start, end)` computes all of the following from
`Engagement` rows grouped by `thread_id`:

| Metric | Definition |
|---|---|
| Turns per conversation (P50/P90/P99) | Count of `kind == "message"` engagements per thread |
| Looping conversations | Threads with more than 6 turns that never reached a terminal state |
| Confirmation reversal rate | Share of confirmations where the rep declined the proposed action (`Engagement.confirmed == False`) |
| Out-of-scope rate + trend | Share of messages classified `intent == "other"`, compared across the recent vs. prior half of the date range |
| Re-ask rate | Same intent classified 2+ times in one thread before any terminal resolution |
| Abandonment rate | Thread has messages but never reaches a terminal state (resolved / escalated / cancelled) |
| Repeat-contact rate | New thread for the same rep + intent opened within 24h of a prior *resolved* thread |

**Terminal-state detection scans every engagement kind, not just messages.**
A resolution can land on either the message row (direct resolve or escalate)
or the separate confirmation row (confirm-flow resolve or cancel) — a thread
that goes through `needs_confirmation` carries its final `resolution_status`
on the `kind == "confirmation"` engagement, not the message. Scanning only
messages would silently miscount every confirm-flow thread (a meaningful
share of volume) as permanently unresolved.

**Repeat-contact rate has a known precision limit.** It correlates only by
`rep_id` + `intent` — `Engagement` doesn't carry an order/account/customer
identifier the way `Ticket` does. For a rep handling real volume, "resolved
this intent within the last 24h" is true almost constantly, so at high
volume the metric reads more as a rep-workload artifact than a genuine "the
same customer came back" signal. The CX Monitor card renders this caveat
directly next to the number. Making it trustworthy rather than directional
means capturing an order/account identifier on `Engagement` — see
[Known limitations](#known-limitations--future-work).

---

## Guardrail integrity

### Confirm-gate audit

`ActionAudit` ([`backend/app/store/models.py`](../backend/app/store/models.py))
holds one row per mutating action actually executed against a downstream
agent, written at the single `agents_client.execute()` call site in
[`graph/nodes.py:confirm`](../backend/app/graph/nodes.py). That call site is
unreachable without passing the `interrupt()`/rep-approval check immediately
above it — there is no code path in the graph that reaches `execute()`
without a rep-approved confirmation first.

`unconfirmed_mutation_count` in the guardrail summary should therefore
always read zero. It exists as continuous proof of that invariant (catching
a future refactor that breaks the gate) and as the audit trail Trust &
Safety / compliance expects for every executed action — a nonzero value is
a real incident, not statistical noise.

### Prompt-injection detection

[`backend/app/guardrail.py`](../backend/app/guardrail.py) is a small,
dependency-free regex scanner — deterministic, zero added latency or cost,
the same approach as the existing entity extraction in `llm.py`. Seven
pattern families are checked in order, first match wins:

| Pattern | Catches |
|---|---|
| `ignore_instructions` | "ignore the previous instructions…" |
| `disregard_instructions` | "disregard your instructions…" |
| `new_instructions` | "new instructions: …" |
| `reveal_system_prompt` | "what is your system prompt…" |
| `role_override` | "you are now…" / "act as…" / "pretend you are…" |
| `bypass_confirmation` | "skip/auto-approve without confirming…" |
| `developer_mode` | "developer mode" / "DAN" |

Two call sites cover the two vectors OWASP LLM01 describes:

| Vector | Where | What's scanned |
|---|---|---|
| Direct | `llm.classify()` | The rep's own typed message |
| Indirect | `llm.compose_reply()` | `order_context`, assembled from a downstream service — data that reaches the prompt without the rep ever typing it |

A match is recorded to `GuardrailEvent` and surfaced on CX Monitor; it never
blocks or alters the turn. This is a deliberate default for a first-pass
regex scanner: false positives on legitimate rep language ("ignore the
previous ticket, this is a new issue") are expected, and a blocking false
positive would actively interrupt a rep mid-conversation. Block-on-detection
(or a model-based classifier for the ambiguous cases) is a viable upgrade
once the real-world false-positive rate is known — see
[Known limitations](#known-limitations--future-work).

---

## True token economics

Every Anthropic call goes through `llm._log_usage()`
([`backend/app/llm.py`](../backend/app/llm.py)), which reads the full token
taxonomy directly off `resp.usage`:

```python
resp.usage.input_tokens
resp.usage.output_tokens                        # inclusive of thinking — billing-authoritative
resp.usage.output_tokens_details.thinking_tokens # subset of output_tokens spent on reasoning
resp.usage.cache_creation_input_tokens
resp.usage.cache_read_input_tokens
```

`_log_usage()` runs on every path — success, live failure with fallback to
the offline mock, and no-API-key fallback — so `LLMCall.fallback` gives a
real fallback-to-mock rate per function rather than a scattered
`logger.warning` nobody's watching.

**Instrumented functions:** `classify` and `compose` (conversational, carry
a `thread_id`); `executive_summary`, `production_analysis`, `enhancements`
(background/admin, `thread_id=None`).

**Cost model.** Anthropic doesn't return line-item cache pricing on the
response, so cache writes are approximated at 1.25× the base input rate
(5-minute TTL) and cache reads at 0.1× — documented, not exact; revisit if
cache usage becomes material.

**Cost of failure** sums `LLMCall.cost_usd` for every call on a thread that
ultimately ended `escalated` — money spent with zero auto-resolution value
delivered.

**Cost by intent and by outcome**, not by graph node. Only two nodes in the
graph ever call the LLM: `triage` (→ `classify`) and `compose` (→
`compose_reply`). Every resolver (`activation_resolver`,
`pending_order_resolver`, `promo_resolver`, `occ_resolver`) calls
`agents_client.diagnose()` / `.execute()` — the downstream "existing agent"
services, not Claude — and `knowledge()`, `ticket_fallback()`, `confirm()`
don't touch the LLM either. A literal per-resolver cost split would just be
rows reading `$0.00`. Cost broken out by **intent** and by **outcome**
answers the real question underneath "which node drives spend" — both
computed by joining `LLMCall.thread_id` against `Engagement.intent` /
`resolution_status`, no extra instrumentation required:

```jsonc
"by_intent":  [{ "intent": "promo", "calls": 15068, "total_cost_usd": 51.21 }],
"by_outcome": [{ "outcome": "escalated", "calls": 14898, "total_cost_usd": 50.55 }]
```

If a future node calls the LLM directly, `_log_usage()`'s `function`
parameter already supports it — pass the new node's name and it appears in
`by_function` automatically.

---

## Sales-intent segmentation

`llm.tag_sales_intent()` is a deterministic keyword heuristic, not an LLM
classifier — a second model call per turn is too expensive for this signal,
and reps rarely narrate their own sales motion explicitly. It recognizes
three codes:

| Code | Motion |
|---|---|
| `nse` | New Service & Equipment |
| `aal` | Add a Line |
| `up` | Upgrade |

Everything else stays `unclassified` rather than guessing.

**This is a first-pass, low-precision signal.** Validate against real
order/account data ("is this a new customer / new line / device swap")
before using it for reporting decisions — the caveat is rendered directly on
the CX Monitor dashboard's Sales-Intent Breakdown card.

The tag is sticky across a thread — `llm.tag_sales_intent(text) or
state.get("sales_intent")` — since a rep rarely repeats "add a line" every
message. It flows through to both `Engagement.sales_intent` and
`Ticket.sales_intent`.

---

## Fallback-rate alerting

`db.check_fallback_spike(window_minutes=10, threshold=0.05)` is a pure
query: has the fallback-to-mock rate across all `LLMCall` rows exceeded 5%
in the last 10 minutes, with a minimum 8-call sample so a single fallback in
a quiet period doesn't read as a 100% spike?

`llm._log_usage()` calls it after every fallback event (not every call — a
run of successes can't newly cross the threshold). A spike calls
`system_health.maybe_auto_degrade(reason)` ([doc 13](13-system-health.md)),
which:

- **Only acts when the current status is exactly `operational`** — never
  overwrites a status an admin set manually, whether a real outage or an
  unrelated degraded state.
- Sets `degraded` with an `[Auto]`-prefixed description and a workaround
  note ("check `ANTHROPIC_API_KEY` / Anthropic API status"), persists it,
  and broadcasts over the same SSE channel the manual notify-on-save toast
  uses — reps see a live toast the moment the spike is detected, with no
  additional frontend wiring.
- **No auto-recovery, by design.** Once flagged, an admin clears it from
  Settings like any other incident — a transient dip won't flap the badge
  back and forth on its own.

---

## API

`GET /api/cx/overview` carries two additional top-level keys, present in the
mock, live, and error-fallback response shapes alike:

```jsonc
{
  // ...existing latency/tokens/cost_usd/timeseries from LangSmith...
  "observability": {
    "conversation_health": {
      "turns_per_conversation": { "p50": 1, "p90": 2, "p99": 6, "conversations_measured": 25573 },
      "looping_threshold": 6,
      "looping_conversations": 0,
      "confirmation_reversal_rate": 0.117,
      "out_of_scope_rate": 0.07,
      "out_of_scope_trend": "up 1% vs. prior half of window",
      "re_ask_rate": 0.0,
      "abandonment_rate": 0.0,
      "repeat_contact_rate": 0.09
    },
    "sales_intent": [
      { "sales_intent": "nse", "count": 2440, "auto_resolved": 1706, "escalated": 706,
        "avg_confidence": 0.857, "containment_rate": 0.699 }
    ],
    "guardrail": {
      "actions_executed": 13620,
      "unconfirmed_mutation_count": 0,
      "unconfirmed_mutation_examples": [],
      "injection_attempts": 5,
      "injection_examples": [
        { "thread_id": "…", "node": "triage", "source": "direct",
          "pattern": "role_override", "snippet": "pretend you are a supervisor…",
          "created_at": "…" }
      ]
    }
  },
  "llm_usage": {
    "calls_recorded": 313606,
    "token_taxonomy": { "avg_input": 763, "avg_output": 74, "avg_thinking": 2, "…": "…" },
    "cost_usd": { "total": 1064.69, "avg_per_call": 0.0034, "cost_of_failure": 303.15, "cost_of_failure_pct": 0.285 },
    "by_function": [
      { "function": "classify", "calls": 156803, "fallback_calls": 2337, "fallback_rate": 0.015, "…": "…" }
    ],
    "by_intent":  [{ "intent": "promo", "calls": 15068, "total_cost_usd": 51.21 }],
    "by_outcome": [{ "outcome": "escalated", "calls": 14898, "total_cost_usd": 50.55 }]
  }
}
```

Code: [`backend/app/api/cx.py`](../backend/app/api/cx.py) (`_with_observability`),
[`backend/app/store/db.py`](../backend/app/store/db.py)
(`observability_overview`, `llm_usage_overview`, `check_fallback_spike`).

---

## Data model

| Table | Purpose |
|---|---|
| `llm_calls` | One row per Anthropic call attempt — full token taxonomy, cost, success/fallback |
| `action_audit` | One row per executed mutation — the confirm-gate audit trail |
| `guardrail_events` | One row per injection-pattern match — log-only, thread/rep/node/source/pattern/snippet |

`engagement` and `ticket` both carry a nullable `sales_intent` column.

`Ticket.id` and `ProductionIssue.id` use 12 hex characters of a UUID4 (not
8) — at production-scale row counts, 8 hex characters (32 bits) has a
non-trivial birthday-paradox collision probability; 12 (48 bits) keeps it
negligible.

---

## Frontend

| File | Role |
|---|---|
| `frontend/src/components/CXDashboard.tsx` | Conversation-health KPI rows, guardrail + injection banners, sales-intent bars, full token-taxonomy table, fallback-rate table, cost-by-intent/outcome tables |
| `frontend/src/types.ts` | `ObservabilityOverview`, `LLMUsageOverview` |
| `backend/app/api/admin.py` | Seed job populates `llm_calls`, `action_audit`, `guardrail_events`, and `sales_intent` so the deployed demo isn't empty in these sections |

---

## Known limitations & future work

- **Repeat-contact accuracy** — needs an order/account/customer identifier
  on `Engagement` to correlate by customer rather than by rep + intent.
- **Prompt-injection detection is log-only** — block-on-detection or a
  model-based classifier for ambiguous cases is a natural upgrade once the
  real-world false-positive rate is known.
- **PII/PCI pattern detection** is not implemented. This has compliance
  implications beyond engineering scope and needs sign-off before design,
  not just before ship — treat as a pre-pilot requirement.
- **Cache-hit $ validation and cost-by-model routing** are blocked on
  prompt caching and multi-model routing actually landing in the app,
  independent of this observability work.
- **Sales-intent taxonomy** covers only NSE/AAL/UP. Additional motions
  (retention/save, port-in, plan change, accessory/protection attach) would
  need validation against real sales-motion data before adding.
- **Guardrail and sales-intent signals live inside CX Monitor** today. A
  dedicated panel (reusing the Production Monitor SSE pattern) is a
  reasonable home if this surface grows enough to warrant its own tab.
