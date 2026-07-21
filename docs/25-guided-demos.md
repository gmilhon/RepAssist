# Guided Demos — end-to-end sales & service visits

A **"Run a demo"** launcher on the empty chat window plays a full, hands-free
store visit — **check-in → assist → conversation → completion → visit summary +
Playbook grade** — so anyone can see the whole flow without knowing what to type
or say. Each scenario runs in one of two modes:

- **Chat** — the demo auto-types the rep's requests and the assistant responds and
  acts in the chat thread (builds the cart / resolves the issue).
- **Live Listen** — a simulated spoken customer↔rep conversation plays into the
  Live Listen transcript, and the assistant assists ambiently (the watcher builds
  the cart / surfaces suggestions).

Both modes run under a Live Listen session, so both end with the same graded,
summarized recap.

Code: [`demos.ts`](../frontend/src/demos.ts) (the catalog),
[`ChatWidget.tsx`](../frontend/src/components/ChatWidget.tsx) (`DemoCard`,
`runDemo`, `runnerSend`, `autoCheckout`), plus the shared
[`Checkout.tsx`](../frontend/src/components/Checkout.tsx) and
[`api/listen.py`](../backend/app/api/listen.py) (the `record_only` analyze flag).

---

## The scenarios

Each demo checks in a persona and uses **real** mock accounts/orders so the
resolvers and account context behave correctly.

| Kind | Demo | Persona / account | Journey |
|---|---|---|---|
| Sales | Family upgrade + trade-in | J. Rivera · AC-3003 | Trade-in → Pixel 10 + protection + a new line + Netflix + a case |
| Sales | First-time customer | Sam Carter · new walk-in | First line: iPhone 17 on Unlimited Plus + protection + YouTube TV |
| Sales | Add a watch line | K. Patel · AC-5001 | Apple Watch on Number Share + wearable protection + a charger |
| Service | Stuck activation | Marcus Webb · ACT-1001 | Diagnose + re-provision the stuck line |
| Service | Surprise first bill | Dana Cole · AC-3004 | Explain the prorated first bill (One Source of Truth) |
| Service | Missing promo credit | J. Rivera · AC-3003 | Re-apply the missing monthly promo credit |

---

## How the runner works

`runDemo(demo, mode)` orchestrates the whole visit as a sequence of awaited steps:

1. **Check in** the persona (`POST /api/queue/checkin`).
2. **Start a Live Listen session** on that entry (both modes) — this gives the
   visit its transcript, so it can be graded + summarized at the end. Surfaces the
   account card up front.
3. **Play the scenario:**
   - *Live Listen* — plays the spoken `conversation` on real-time delays; the
     watcher builds the cart / surfaces suggestions.
   - *Chat* — records the `conversation` into the transcript for grading via
     `api.listenAnalyze(..., record_only=true)` (a **transcript-only** append that
     skips the watcher + cart), then sends the rep `chatTurns`, which the assistant
     acts on directly. `runnerSend` auto-approves any confirmation gate the
     assistant proposes (demos run the happy path).
4. **Complete the visit:**
   - *Sales* — `autoCheckout` drives the POS checkout end-to-end
     (`checkoutStart → advance → pay → sign` with a synthetic signature), so the
     View Together → payment → signature → order confirmation all play out.
   - *Service* — the resolution turn routes through the resolver → confirm →
     auto-approve → resolved.
5. **End the visit** (`stopListen`) → the **Playbook grade** (stars + did-well /
   to-improve, graded against the conversation transcript) and the **visit
   summary** (with a Send button) render inline.

A **demo banner** with a **Stop demo** control shows while it runs, and the
composer is disabled so the auto-run isn't disturbed.

### Why both modes run under Live Listen

The visit summary + Playbook grade are Live-Listen recap artifacts generated from
the session transcript. Rather than build a second grading path for Chat mode, the
runner starts a Live Listen session in both modes and, for Chat, seeds the
transcript with the scenario conversation via the new `record_only` analyze flag —
so the grade always reflects the (simulated) customer conversation, and the
summary is sendable / shows up in Coaching just like a real visit.

### Implementation note — `threadIdRef`

The runner holds a stale React render closure across its awaited turns, so
`send()` reads the live thread id from a **`threadIdRef`** (updated synchronously
in `applyResponse`) rather than the `threadId` state — otherwise each turn would
start a fresh thread.

---

## Adding a scenario

Append a `Demo` to [`demos.ts`](../frontend/src/demos.ts): a `checkIn` persona
(reusing a real account/order id), a spoken `conversation`, the rep `chatTurns`,
and (service) a `resolveTurn`. Sales demos auto-checkout; service demos resolve
via the graph. No runner changes needed — `runDemo` is scenario-agnostic.
