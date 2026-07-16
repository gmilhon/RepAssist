# Observability P1 — Cost by Node, Injection Detection, Alerting, and Conversation Signals

P0 ([doc 16](16-observability-p0.md)) shipped the tier that needed no policy
decision. P1 needed six — all resolved in one review pass:

| Question | Decision |
|---|---|
| Sales-intent taxonomy | Stay at NSE/AAL/UP — no expansion |
| Guardrail action on detection | Log-only — no blocking |
| Fallback-rate alert threshold | Sustained spike — >5% fallback rate over a 10-minute window |
| Guardrail & Sales-Intent panel placement | Stay in CX Monitor — no new tab |
| Per-node cost tracking | Build it next |
| PII/PCI pattern detection | Defer entirely — out of scope for this prototype |

This closes the four items those decisions unblocked: cost-per-node,
prompt-injection detection, the fallback-rate alert, and the
re-ask/abandonment/repeat-contact metrics that had no blocker at all, just
hadn't been built yet.

---

## Cost "per node" — reframed to match the actual graph

The proposal asked for cost broken out per graph node — triage vs. resolver
vs. compose. Building it surfaced a fact about this specific architecture:
**only two nodes ever call the LLM.** `triage` calls `llm.classify()`;
`compose` calls `llm.compose_reply()`. Every resolver
(`activation_resolver`, `pending_order_resolver`, `promo_resolver`,
`occ_resolver`) calls `agents_client.diagnose()` / `.execute()` — the
downstream "existing agent" services, not Claude. `knowledge()`,
`ticket_fallback()`, and `confirm()` don't touch the LLM either.

So a literal per-resolver cost breakdown would just be four rows reading
`$0.00`. The **honest, valuable** delivery is cost broken out by
**intent** and by **outcome** instead — "which kind of conversation, and
which kind of ending, drives spend" is the real question underneath "which
node." Both use the `thread_id` already on every conversational `LLMCall`
row, joined against `Engagement.intent` / `resolution_status` — no new
instrumentation needed.

```jsonc
// GET /api/cx/overview → llm_usage
{
  "by_intent":  [{ "intent": "promo", "calls": 15068, "total_cost_usd": 51.21 }, "…"],
  "by_outcome": [{ "outcome": "escalated", "calls": 14898, "total_cost_usd": 50.55 }, "…"]
}
```

If the graph ever grows a node that calls the LLM directly (a resolver doing
its own reasoning instead of delegating to `agents_client`, for instance),
`_log_usage()`'s `function` parameter already supports that — pass the new
node's name and it appears in `by_function` automatically.

---

## Prompt-injection detection (log-only)

[`backend/app/guardrail.py`](../backend/app/guardrail.py) is a small,
dependency-free regex pass — the same philosophy as the existing entity
extraction in `llm.py`: deterministic, zero added latency, zero added cost.
Seven pattern families (ignore-instructions, disregard-instructions,
new-instructions, reveal-system-prompt, role-override, bypass-confirmation,
developer-mode) checked in order, first match wins.

Two call sites, matching the two vectors OWASP LLM01 describes:

| Vector | Where | What's scanned |
|---|---|---|
| **Direct** | `llm.classify()` | The rep's own typed message |
| **Indirect** | `llm.compose_reply()` | `order_context`, assembled from a downstream service — data that flows into the prompt without the rep ever typing it |

By decision, a match **never blocks or alters the turn** — it's recorded to
the new `GuardrailEvent` table and surfaced on CX Monitor. This is the
correct default for a first pass: false positives on legitimate rep language
("ignore the previous ticket, this is a new issue") are expected, and a
blocking false positive would actively harm a rep mid-conversation. If the
real-world false-positive rate proves low, block-on-detection (or a
model-based classifier for the ambiguous cases) is a natural follow-up —
not built here, per the decision above.

---

## Fallback-rate alert — reusing System Health's SSE notify

`db.check_fallback_spike(window_minutes=10, threshold=0.05)` is a pure query
(no side effects) — has the fallback-to-mock rate across all `LLMCall` rows
exceeded 5% in the last 10 minutes, with a minimum 8-call sample so one
fallback in a quiet period doesn't read as a 100% spike?

`llm._log_usage()` calls it after every fallback event (not every call —
a run of successes can't newly cross the threshold, so there's no reason to
query on the success path). A spike calls
`system_health.maybe_auto_degrade(reason)`
([doc 13](13-system-health.md)), which:

- **Only acts when the current status is exactly `operational`** — never
  overwrites a status an admin set manually, for a real outage or an
  unrelated degraded state.
- Sets `degraded` with an `[Auto]`-prefixed description and a workaround
  ("check `ANTHROPIC_API_KEY` / Anthropic API status"), persists it, and
  broadcasts over the **same SSE channel** the manual notify-on-save toast
  already uses — reps see a live toast the moment the spike is detected,
  with zero new frontend code.
- **No auto-recovery, by design.** Once flagged, an admin clears it from
  Settings like any other incident — a transient dip won't flap the badge
  back and forth on its own.

Verified directly (not via organic seed traffic, which sits around a steady
1.5% fallback rate — well under the 5% threshold): forcing 8 synthetic
fallback events in a row flips status to `degraded` with the expected
description; a second check against a manually-set `outage` status confirms
it's left untouched.

---

## Conversation-health additions

Three new metrics in `db.observability_overview()`, all computed from
`Engagement` data already captured — no new instrumentation:

| Metric | Definition |
|---|---|
| **Re-ask rate** | Same intent classified 2+ times in one thread before any terminal resolution |
| **Abandonment rate** | Thread has messages but never reaches a terminal state (resolved/escalated/cancelled) |
| **Repeat-contact rate** | New thread for the same rep + intent opened within 24h of a prior *resolved* thread |

**A real, honest caveat on repeat-contact:** it correlates only by
`rep_id` + `intent` — `Engagement` doesn't carry an order/account/customer
identifier the way `Ticket` does. For a rep handling real volume, "resolved
this intent within the last 24h" is true almost constantly, so the metric
reads as a rep-workload artifact more than a "the same customer came back"
signal. On this repo's seed data (18 reps × 6 intents, ~150k threads) it
reads **91%** — not because resolutions are failing at that rate, but
because 18 reps × 6 intents is too coarse a key at this volume. The
dashboard displays this caveat directly next to the metric rather than
hiding it. Fixing it properly means capturing an order/account identifier on
`Engagement` — out of scope here; flagged as a concrete next step if this
metric needs to be trustworthy rather than directional.

**Drive-by fix while building this:** `terminal_by_thread` (used by both the
P0 looping-conversation metric and now abandonment) only scanned
`kind == "message"` engagements. Confirm-flow threads (~40% of volume) carry
their terminal `resolution_status` on the separate `kind == "confirmation"`
row, so every confirm-flow thread was silently miscounted as
non-terminal — invisible in P0 because `looping_conversations` only flags
threads over 6 turns (rare regardless), but it would have made the new
abandonment-rate metric wildly, obviously wrong. Fixed by scanning all
engagements for the terminal check, not just messages.

---

## Data model

| Table | Purpose |
|---|---|
| `guardrail_events` | One row per injection-pattern match — log-only, thread/rep/node/source/pattern/snippet |

No new columns on existing tables this pass.

---

## API

`GET /api/cx/overview`'s `observability` and `llm_usage` sections both grew:

```jsonc
{
  "observability": {
    "conversation_health": {
      // …P0 fields…
      "re_ask_rate": 0.0, "abandonment_rate": 0.0, "repeat_contact_rate": 0.913
    },
    "guardrail": {
      // …P0 fields…
      "injection_attempts": 5,
      "injection_examples": [
        { "thread_id": "…", "node": "triage", "source": "direct",
          "pattern": "role_override", "snippet": "pretend you are a supervisor…",
          "created_at": "…" }
      ]
    }
  },
  "llm_usage": {
    // …P0 fields…
    "by_intent":  [{ "intent": "promo", "calls": 15068, "total_cost_usd": 51.2054 }],
    "by_outcome": [{ "outcome": "escalated", "calls": 14898, "total_cost_usd": 50.55 }]
  }
}
```

---

## Frontend

| File | Role |
|---|---|
| `frontend/src/components/CXDashboard.tsx` | New P1 KPI row (re-ask/abandonment/repeat-contact/injection-attempts) with the repeat-contact caveat rendered inline; `InjectionBanner` alongside the existing guardrail banner; `CostSplitTable` for intent/outcome breakdowns |
| `frontend/src/types.ts` | Extended `ObservabilityOverview` and `LLMUsageOverview` |
| `backend/app/api/admin.py` | Seed job sprinkles ~1 synthetic guardrail event every 5–8 days (not tied to conversation volume — real attempts should be rare) so the panel isn't empty in the deployed demo |

---

## What's still pending (P2)

Only the item explicitly deferred:

- **PII/PCI pattern detection** — deferred entirely by decision; flagged as a
  pre-pilot requirement needing compliance sign-off before design, not just
  before ship.

Also still open, not blocked by a decision but not built:

- **Repeat-contact accuracy** — needs an order/account/customer identifier on
  `Engagement` to be a trustworthy signal rather than a directional one.
- **Cache-hit $ validation, cost-by-model routing** — blocked on prompt
  caching / multi-model routing actually landing in the app, independent of
  this observability work.
