# Live Listen — read-only AI copilot over a live conversation

While a rep is helping a checked-in customer at the counter, **Live Listen**
watches the spoken conversation and quietly surfaces suggestion cards for issues
the existing agent intents can triage. When the visit ends it grades the
conversation against the store **Playbook** and drafts a customer-facing visit
summary the rep can email in one tap. A separate **Coaching** view turns those
graded visits into per-rep GenAI feedback.

Live Listen is **strictly read-only**. The watcher never calls the orchestrator,
never creates a ticket, and never executes an agent action. Everything it does
stops at a read-only *diagnose*. When the rep **accepts** a suggestion, the card
hands a prepared prompt into the *normal* chat flow — that is the only place
diagnosis, confirmation, and any account-changing write can happen, exactly as
when a rep types a request themselves. Live Listen therefore adds **zero new
mutation surface**: the confirmation gate and audit trail
([doc 01 §8](01-solution-architecture.md), [doc 02](02-langgraph-orchestration.md))
are untouched.

It builds directly on the store queue ([doc 19](19-store-checkin-queue.md)): a
Live Listen session is always attached to a customer the rep is already
assisting.

---

## User flow

1. A rep taps the **headset button** by the composer to open the *Start Live
   Listen* dialog. It lists customers **waiting** in the store queue and offers
   two capture modes:
   - **Mic** — the browser's `SpeechRecognition` transcribes the counter
     conversation live (composer dictation yields the microphone to the
     session).
   - **Demo** — a scripted store visit is played back on a timer, so the feature
     demos with no microphone and no credentials.
2. Starting a session claims the queue entry (same **Assist** hand-off as
   tapping a queue row), attaches to the chat thread, and drops a confirmation
   bubble: *"🎧 Live Listen started — assisting Maria Lopez (Upgrade). I'll flag
   anything I can help with."* Any **sales opportunities** the customer is
   eligible for are noted up front.
3. As the customer and rep talk, utterances stream into a **docked transcript
   panel**. The frontend buffers new utterances and flushes them to an analyze
   pass on a timer; each pass may surface **suggestion cards** — *"Activation
   sounds stuck"*, *"Missing promo credit"* — colour-coded by urgency and, when
   the customer's id is already known, enriched with a read-only **root-cause
   diagnosis**.
4. The rep taps **Accept** on a card to hand its prepared prompt into the normal
   chat, where the usual triage → diagnose → **confirm** → resolve flow takes
   over (including the write confirmation gate). Ignoring a card costs nothing.
5. Tapping **Stop** ends the session and returns a **recap**: utterance and
   suggestion counts, duration, a **Playbook score** (1–5 stars with a
   per-guideline breakdown), and a drafted **visit summary**. The rep can tap
   **Email summary** to send that recap to the customer-facing subscriber list.
6. Later, the **Coaching** tile lists recently graded visits; opening one
   returns GenAI feedback on how the rep could have better met the Playbook.

---

## Architecture

```
Headset button ──► Start Live Listen dialog (pick waiting customer + mic/demo)
                      │
                      ▼
              POST /api/listen/start ──► db.assist_queue_entry()  (claim queue entry)
                      │                └─ db.create_listen_session()  (listen_sessions row)
                      │                └─ resolve_eligibility(account_id)  → sales opportunities
                      ▼
        docked transcript  ◄── mic SpeechRecognition │ demo script (timer)
                      │  (buffer utterances, flush on a timer)
                      ▼
              POST /api/listen/{id}/analyze
                      │  append to transcript, take the last 12 utterances (rolling window)
                      │  llm.extract_entities(window)          → order/account ids spoken
                      ▼
              llm.analyze_live_transcript(window, context, prior_intents)  → LiveCoachResult
                      │  Python post-validation (never trust the model):
                      │   • known intent only, not already surfaced
                      │   • confidence ≥ 0.55, ≤ 2 new cards per pass
                      │  read-only agents_client.diagnose() enrichment when the id is known
                      ▼            (NEVER agents_client.execute — no writes on the listen path)
              suggestion cards ──► Accept ──► send()  ──► LangGraph orchestrator (normal chat)
                                              _build_prompt(intent, entities)

              POST /api/listen/{id}/stop
                      │  llm.generate_visit_summary(...)   → VisitSummary   (persisted)
                      │  llm.grade_playbook(...)           → PlaybookGrade  (persisted, stars 1-5)
                      ▼
              recap card ──► Email summary ──► POST /api/listen/{id}/send-summary
                                                 └─ email_reports.send_visit_summary()

Coaching tile ──► GET /api/coaching/recent ──► `coaching` A2UI card (recent graded visits)
                      │
                      ▼
              POST /api/coaching/{session_id} ──► llm.generate_coaching(...) → CoachingRecommendation
                                                    (cached on the session)
```

### Why these choices

- **Why read-only, and why Accept re-enters the normal chat.** A live customer
  conversation is not a rep typing a vetted request — it is unverified, spoken
  input. The watcher may *observe and suggest*; the rep decides. Accepting a
  card calls `_build_prompt(intent, entities)` to turn the suggestion into a
  natural first-person rep request, then routes it through the same `send()`
  every CTA tile and A2UI row uses. So the existing triage → **confirm** →
  execute path — the only code that can mutate an account — is unchanged, and
  Live Listen introduces no parallel resolution or new write path to audit.
  (Same design as click-to-assist in [doc 19](19-store-checkin-queue.md).)
- **Why a rolling 12-utterance window** (`WINDOW_UTTERANCES`). Only the most
  recent utterances go to the model, which bounds token cost per pass and stops
  a stale id spoken early in the visit from binding to a later, unrelated issue.
  Ids are re-extracted from the *window*, not the whole transcript, for the same
  reason.
- **Why post-validate the model in Python.** The model's suggestions are
  filtered before they ever reach the rep: only intents in the real `Intent`
  enum, nothing already surfaced this session, a confidence floor
  (`MIN_CONFIDENCE = 0.55`), and at most two new cards per pass
  (`MAX_SUGGESTIONS_PER_CALL`) so the rep is never flooded mid-conversation.
  Untrusted transcript input is also bounded (`MAX_UTTERANCE_CHARS`,
  `MAX_UTTERANCES_PER_CALL`).
- **Why the known account/order matters.** The queue entry already carries the
  customer's `account_id`/`order_id` ([doc 19](19-store-checkin-queue.md)), so
  suggestion cards — and the read-only diagnose — can be enriched **without
  re-prompting** the rep for ids the customer's record already holds.
- **Why diagnose-only enrichment.** For an intent that has a real resolver *and*
  whose required id is already known, the analyze pass calls
  `agents_client.diagnose()` to attach `can_resolve` / `root_cause` /
  `human_prompt` to the card. It **never** calls `execute()`. If the id isn't
  known or diagnose fails, the card still ships, just without root-cause detail.
- **Why grade and summarize at Stop, not live.** Both need the *whole*
  conversation; running them mid-visit would be noise. Both are **best-effort** —
  a model failure logs a warning and never blocks ending the session — and both
  are persisted on the session so the rep-triggered email reuses them.
- **Prompt-injection monitoring.** Each analyze pass scans the transcript
  (`source=direct`) and the interpolated context — customer name/phone from the
  public check-in form plus extracted ids — (`source=indirect`) for injection
  patterns, logged to `guardrail_events` exactly like the chat nodes. Detection
  is log-only and never alters the pass. See [Observability](16-observability.md).

---

## Playbook scoring

The **Playbook** is the standard a rep is graded against, expressed as a set of
guidelines managed from **Settings → Playbook**. Guidelines are grouped into two
categories — **Customer Needs** (did the rep understand and meet what the
customer came in for?) and **Sales Positioning** (did the rep surface the sales
opportunities the customer was eligible for?). Sensible defaults are seeded on
first run (`db.seed_playbook_defaults_if_empty()`).

At **Stop**, `llm.grade_playbook()` evaluates the transcript, the surfaced
suggestions, and the customer's eligibility against the active guidelines and
returns a `PlaybookGrade`:

| Field | Meaning |
|---|---|
| `stars` | Overall 1–5 score of how well the rep followed the Playbook |
| `headline` | One-line verdict |
| `per_guideline` | One `{guideline, met, note}` entry per active guideline |
| `strengths` / `gaps` | Short phrases on what went well and what to improve |

The grade is persisted (`listen_sessions.playbook_score` + `playbook_grade`) and
rendered as a star card in the recap.

## GenAI coaching

The **Coaching** tile (Front desk group) fetches recently graded visits
(`GET /api/coaching/recent`) as a `coaching` A2UI card — each row showing the
customer, visit reason, star score, and how long ago. Selecting a visit calls
`POST /api/coaching/{session_id}`, which runs `llm.generate_coaching()` over the
same conversation + grade and returns a `CoachingRecommendation`:

- `summary` — a 2–3 sentence coaching overview
- `what_went_well` — things the rep handled well
- `improvements` — prioritized, **guideline-linked** advice for next time
- `suggested_script` — an example of what the rep could have said to better meet
  the Playbook, especially for positioning a sales opportunity

Coaching is **read-only** over listen-session data and cached on the session
(`listen_sessions.coaching`) so re-opening a visit doesn't re-bill the model.

Every LLM function here — analyze, summary, grade, coaching — is **offline-safe**:
with no `ANTHROPIC_API_KEY` it degrades to a deterministic rule-based fallback,
and each call is logged to the `llm_calls` token ledger
([doc 16](16-observability.md)), so Live Listen shows up in true token
economics like every other model call.

---

## API

| Method & path | Purpose |
|---|---|
| `POST /api/listen/start` | Start a session for a **waiting** queue entry — `{rep_id, queue_entry_id, thread_id?, mode}`. Claims the entry, creates the `listen_sessions` row, returns `{session, thread_id, entities, eligibility, opportunities}` |
| `POST /api/listen/{id}/analyze` | Analyze buffered utterances — `{utterances:[{speaker?, text}]}`. Appends to the transcript and returns `{suggestions, entities}`. Empty/whitespace calls short-circuit without a model pass |
| `POST /api/listen/{id}/stop` | End the session; returns `{session, recap}` with the visit summary + Playbook grade |
| `POST /api/listen/{id}/send-summary` | Email the visit summary to Live Listen subscribers (rep-triggered from the recap) |
| `GET /api/coaching/recent?limit=` | Recent graded visits as a `coaching` A2UI card |
| `POST /api/coaching/{session_id}` | Coaching recommendation for one visit (generated on first request, then cached) |
| `GET·POST·PATCH·DELETE /api/playbook/guidelines` | CRUD over Playbook guidelines (Settings → Playbook) |

Code: [`backend/app/api/listen.py`](../backend/app/api/listen.py),
[`backend/app/api/coaching.py`](../backend/app/api/coaching.py),
[`backend/app/api/playbook.py`](../backend/app/api/playbook.py); model calls in
[`backend/app/llm.py`](../backend/app/llm.py)
(`analyze_live_transcript`, `generate_visit_summary`, `grade_playbook`,
`generate_coaching`, `extract_entities`); the summary email in
[`email_reports.py`](../backend/app/api/email_reports.py)
(`build_visit_summary_html`, `send_visit_summary`).

---

## Data model

| Table | Purpose |
|---|---|
| `listen_sessions` | One row per Live Listen session: `rep_id`, `thread_id`, `queue_entry_id`, the copied `customer_name`/`customer_phone`/`reason`/`account_id`/`order_id`, `mode` (`mic`\|`demo`), `status` (`active`\|`ended`), `eligibility`, and the accumulating `transcript`/`suggestions` plus the generated `summary`, `playbook_score`, `playbook_grade`, and `coaching` |
| `playbook_guidelines` | One row per guideline: `category` (`Customer Needs`\|`Sales Positioning`), `text`, `active`, `sort_order` |
| `email_subscribers.subscribed_visit_summary` | Per-subscriber flag for the customer-facing visit-summary email (see [doc 11](11-email-reports.md)) |

Per-session `threading.Lock`s serialize the read-analyze-record sequence so two
overlapping analyze calls on one session can't race on the JSON columns
(duplicate cards / lost transcript appends).

---

## Frontend

| File | Role |
|---|---|
| `frontend/src/components/ChatWidget.tsx` | Headset launcher + `openListenSetup`/`startListen`/`stopListen`, mic `SpeechRecognition` and demo playback, the analyze debounce, the docked transcript panel, the recap + `sendSummary`, and the `showCoaching`/`onCoach` tile handlers |
| `frontend/src/components/A2UI.tsx` | `LiveSuggestionCard` (`live_suggestion`), `CoachingListCard` (`coaching`), and the shared `Stars` component |
| `frontend/src/components/SettingsPage.tsx` | The **Playbook** guideline editor and the **Live Listen** column in the Email Reports subscriber table |
| `frontend/src/api.ts` / `types.ts` | `listenStart`/`listenAnalyze`/`listenStop`/`listenSendSummary`, `coachingRecent`/`coachingRecommend`; `ListenSession`, `ListenUtterance`, `PlaybookGrade`, `CoachingResult`, `VisitSummary` |

---

## Known limitations & future work

- **Transcription is browser-side.** Mic mode depends on the Web Speech API
  (Chrome/Edge); where it's unavailable the session still runs but without live
  text — Demo mode is the credential-free fallback for everywhere else.
- **Suggestions are point-in-time.** Cards are produced per analyze pass; there
  is no re-ranking or expiry of a card once surfaced (dedupe is by intent for
  the life of the session).
- **Uploaded transcript is not retained as PII-scrubbed.** As with order
  context elsewhere, a production deployment should scrub/tokenize customer
  utterances before they reach the model and disable model-side retention
  ([doc 01 §8](01-solution-architecture.md)).
- **Grade/summary/coaching are best-effort.** If the model call fails they are
  simply absent from the recap rather than retried; a production build would
  queue a retry.
- **One active session per rep in the UI.** Starting a new Live Listen while one
  is running stops the previous session first.
