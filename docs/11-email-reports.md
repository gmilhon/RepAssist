# Email Reports & Settings

Rep Assist can email **HTML dashboard reports** on demand from the **Performance**
and **CX Monitor** tabs, to a managed list of subscribers. A **Settings** tab
manages who receives which report.

The feature works with **zero credentials**: without SMTP configured, "Send
Report" returns an **in-browser preview** of the exact email that would be sent,
so you can build and demo the flow before wiring up a mail server.

---

## User flow

1. **Settings tab** — add subscribers (email + optional name) and toggle their
   subscriptions to **Performance** and/or **CX Monitor** reports. A status badge
   shows whether SMTP is configured.
2. **Performance / CX Monitor tabs** — click **✉ Send Report**. The backend builds
   the report for the current date range and either:
   - **sends** it to active subscribers of that report type (SMTP configured), or
   - returns a **preview** (`preview_html`) rendered inline in an iframe.

---

## Architecture

```
React                                   FastAPI
  SettingsPage.tsx      ── CRUD ────►     /api/email/subscribers
  SendReportButton.tsx  ── send ────►     /api/email/send-report
                                            ↳ fetch /api/metrics/overview  (performance)
                                            ↳ fetch /api/cx/overview       (cx)
                                            ↳ build_*_html(...)            (inline-styled HTML)
                                            ↳ smtplib (TLS/SSL) OR preview
  (status badge)        ── read ────►     /api/email/settings
```

Subscribers persist in SQLite (`EmailSubscriber` in
[`store/models.py`](../backend/app/store/models.py)). Report HTML is generated
with email-client-safe inline styles.

---

## API

| Method & path | Purpose |
|---|---|
| `GET /api/email/subscribers` | List subscribers |
| `POST /api/email/subscribers` | Add (or re-activate) a subscriber |
| `PATCH /api/email/subscribers/{email}` | Update name / subscriptions / active |
| `DELETE /api/email/subscribers/{email}` | Deactivate (soft delete) |
| `POST /api/email/send-report` | Build + send (or preview) a report |
| `GET /api/email/settings` | SMTP status (no secrets returned) |

**Send report body:** `{ "report_type": "performance" | "cx", "start"?, "end"? }`.

**Send report result:**

```jsonc
{
  "sent": 2,                 // recipients emailed (0 in preview mode)
  "previewed": false,        // true when SMTP not configured or send failed
  "recipients": ["a@x.com"],
  "preview_html": "…",       // present when previewed=true or no subscribers
  "warning": "…",            // e.g. no subscribers / SMTP not configured
  "error": "…"               // present if an SMTP send raised
}
```

Code: [`backend/app/api/email_reports.py`](../backend/app/api/email_reports.py).

---

## Configuration (`backend/.env`)

| Var | Default | Purpose |
|---|---|---|
| `SMTP_HOST` | _(empty)_ | e.g. `smtp.gmail.com`. Empty → preview-only mode. |
| `SMTP_PORT` | `587` | `587` for STARTTLS, `465` for SSL. |
| `SMTP_USER` | _(empty)_ | SMTP username / from address. |
| `SMTP_PASSWORD` | _(empty)_ | For Gmail, use an **App Password**, not the account password. |
| `SMTP_FROM` | _(empty)_ | Display From (falls back to `SMTP_USER`). |
| `SMTP_TLS` | `true` | `true` → STARTTLS on `SMTP_PORT`; `false` → implicit SSL. |

`settings.smtp_enabled` is `True` only when both host and user are set.

> **TLS note.** SMTP uses `certifi`'s CA bundle explicitly
> (`ssl.create_default_context(cafile=certifi.where())`) so certificate
> verification works on macOS, where the system Python does not wire up the CA
> store automatically.

### Gmail example

```dotenv
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASSWORD=<16-char app password>   # https://myaccount.google.com/apppasswords
SMTP_FROM=Rep Assist <you@gmail.com>
SMTP_TLS=true
```

---

## Report contents

| Report | Source | KPI cards |
|---|---|---|
| **Performance** | `/api/metrics/overview` | Conversations, Containment, Escalation rate, Avg confidence, Approval rate, Active reps — plus a **volume-by-intent** table |
| **CX Monitor** | `/api/cx/overview` | Conversations, P50, P99, Error rate, Avg tokens, Avg cost/conv — plus a LangSmith live/sample note |

Both share a branded header and footer and respect the date range selected on the
tab when **Send Report** is clicked.

---

## Frontend

| File | Role |
|---|---|
| `frontend/src/components/SettingsPage.tsx` | Subscriber table + add form + SMTP badge |
| `frontend/src/components/SendReportButton.tsx` | Button + result toast + iframe preview |
| `frontend/src/components/OperationsDashboard.tsx` | "Send Report" (performance) in header |
| `frontend/src/components/CXDashboard.tsx` | "Send Report" (cx) in header |
| `frontend/src/types.ts` | `EmailSubscriber`, `SendReportResult`, `EmailSettings` |
| `frontend/src/api.ts` | subscriber CRUD + `sendReport()` + `emailSettings()` |

---

## Production notes

- **Scheduling.** Today reports are on-demand. For scheduled digests, drive
  `send-report` from a cron/worker (e.g. Cloud Scheduler → an authenticated
  endpoint) on a daily/weekly cadence.
- **Deliverability.** Use a transactional provider (SendGrid/SES/Postmark) with
  SPF/DKIM rather than a personal Gmail for anything beyond a demo.
- **Auth.** The subscriber endpoints are unauthenticated in the prototype; gate
  them behind the same SSO as the rest of the app before pilot.
