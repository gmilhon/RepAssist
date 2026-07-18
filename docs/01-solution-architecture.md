# Solution Architecture

## 1. System context

Rep Assist sits inside the retail sales application and brokers between the rep
and the existing fleet of resolver agents, the knowledge base, order systems, and
the human Resolution Desk.

```mermaid
flowchart TB
    subgraph RetailApp["Retail sales application"]
        Widget["Rep Assist widget<br/>(embedded React)"]
    end
    Rep(["🧑‍💼 Retail Rep"]) --> Widget
    Widget -->|HTTPS / JSON| Orch["Rep Assist Orchestrator<br/>(LangGraph + FastAPI)"]

    Orch -->|classify / compose| LLM["Claude (Anthropic API)<br/>+ offline fallback"]
    Orch -->|REST| AGT["Existing Agent Services<br/>Activation · Promo · Pending Order"]
    Orch -->|REST| ORD["Order / Account context"]
    Orch -->|REST| KB["Knowledge Base"]
    Orch -->|read/write| DB[("Tickets + Feedback<br/>store")]

    Tier(["🛠️ Tier 1/2 Specialist"]) --> Desk["Resolution Desk<br/>(embedded React)"]
    Desk -->|HTTPS / JSON| Orch
    Lead(["📋 Agent Dev / Product"]) --> Insights["Insights<br/>(capability backlog)"]
    Insights --> Orch
```

**Trust boundaries.** The rep and Tier 1/2 UIs are authenticated retail surfaces.
The orchestrator is the only component that talks to the agent services, the
LLM, and the store; nothing in the browser holds credentials for those systems.

## 2. Container / component view

```mermaid
flowchart LR
    subgraph FE["Frontend (Vite/React)"]
        Chat["ChatWidget"]
        A2UI["A2UIRenderer<br/>(recent orders)"]
        Console["ReviewConsole"]
        Dash["OperationsDashboard<br/>+ CXDashboard"]
        Settings["SettingsPage"]
    end

    subgraph BE["Orchestrator service (FastAPI)"]
        API["/api/chat · /api/tickets · /api/insights · /api/metrics · /api/cx<br/>/api/mcp · /api/email · /api/queue · /api/production · /api/system-health<br/>/api/listen · /api/coaching · /api/playbook · /api/training · /api/huddle"]
        subgraph G["LangGraph orchestrator"]
            Triage["triage"]
            Route{"router"}
            RA["activation"]
            RP["pending_order"]
            RM["promo"]
            RK["knowledge"]
            RC["confirm (interrupt)"]
            RT["ticket_fallback"]
            RCmp["compose"]
        end
        Listen["listen.py — read-only copilot<br/>analyze · grade · coach (no writes)"]
        MCP["mcp/ — stub MCPClient<br/>+ orders/queue/news servers (A2UI)"]
        LLMmod["llm.py (Claude / mock)"]
        Adapter["agents_client.py"]
        Store["store (SQLModel)"]
    end

    subgraph EXT["Existing agent microservices (mocked locally)"]
        SA["/activation"]
        SP["/pending-order"]
        SM["/promo"]
        SO["/orders/lookup"]
        SK["/kb/search"]
    end

    Chat --> API
    Chat --> A2UI
    A2UI --> API
    Console --> API
    Dash --> API
    Settings --> API
    API --> G
    API --> MCP
    API --> Listen
    Triage --> LLMmod
    RCmp --> LLMmod
    Route --> RA & RP & RM & RK
    RA & RP & RM --> Adapter
    RK --> Adapter
    Adapter --> SA & SP & SM & SO & SK
    Listen --> LLMmod
    Listen -.->|diagnose only, never execute| Adapter
    Listen --> Store
    RT --> Store
    API --> Store
```

> **Live Listen is read-only.** The `listen` router calls the LLM (analyze /
> grade / coach) and, at most, an agent **diagnose** — it never routes through
> the graph and never executes a write. Accepting a suggestion re-enters the
> normal `Chat → /api/chat → LangGraph` path above, so every account change
> still passes the `confirm` gate. See [Live Listen](20-live-listen.md).

| Component | Responsibility | Code |
|---|---|---|
| `ChatWidget` | Rep conversation, resolution cards, confirm/deny | [`frontend/src/components/ChatWidget.tsx`](../frontend/src/components/ChatWidget.tsx) |
| `A2UIRenderer` | Generative-UI elements in chat (recent orders, open tickets, queue, live suggestions, coaching, enhancements, huddle); `type`→component registry | [`frontend/src/components/A2UI.tsx`](../frontend/src/components/A2UI.tsx) |
| `ReviewConsole` | Tier 1/2 ticket queue, detail, resolve + feedback, plus AI-assisted triage (Analyze → education/agent_action/system_defect one-click resolution) | [`frontend/src/components/ReviewConsole.tsx`](../frontend/src/components/ReviewConsole.tsx) |
| `OperationsDashboard` / `CXDashboard` | Performance KPIs + AI summary; LangSmith CX telemetry | [`frontend/src/components/`](../frontend/src/components) |
| `SettingsPage` / `SendReportButton` | Email-report subscribers + on-demand send/preview | [`frontend/src/components/`](../frontend/src/components) |
| API routers | HTTP surface (`chat, tickets, insights, metrics, cx, mcp, email, admin, queue, listen, coaching, playbook, training, huddle, production, system_health`) | [`backend/app/api/`](../backend/app/api) |
| Orchestrator graph | Triage → route → resolve → confirm → compose | [`backend/app/graph/`](../backend/app/graph) |
| **Live Listen** (read-only copilot) | Analyze a live transcript for triageable issues, grade the visit vs. the Playbook, generate coaching — no graph, no writes | [`listen.py`](../backend/app/api/listen.py), [`coaching.py`](../backend/app/api/coaching.py), [`playbook.py`](../backend/app/api/playbook.py) · [doc 20](20-live-listen.md) |
| **Training & Enablement** | Unified "Show me how" (generated steps + committed demo GIF + uploaded video), AI storyboard generator, training-video upload | [`training.py`](../backend/app/api/training.py) · [doc 21](21-training-and-enablement.md) |
| **MCP layer (stub)** | Agent-to-UI tool boundary; `orders` / `queue` / `news` / `ost` / `system` servers return A2UI elements | [`backend/app/mcp/`](../backend/app/mcp) |
| LLM | Triage + reply composition, live-transcript analysis, Playbook grading, coaching, summaries, storyboards (all structured-output, offline-safe) | [`backend/app/llm.py`](../backend/app/llm.py) |
| Agent adapter | HTTP client for existing agents (`diagnose` / `execute`) | [`backend/app/integrations/agents_client.py`](../backend/app/integrations/agents_client.py) |
| Store | Tickets + feedback + analytics + email subscribers + queue/listen/playbook/huddle | [`backend/app/store/`](../backend/app/store) |

## 3. Primary sequence — automated resolution with confirmation

```mermaid
sequenceDiagram
    participant Rep
    participant UI as ChatWidget
    participant API as FastAPI
    participant G as LangGraph
    participant LLM as Claude
    participant AG as Activation Resolver

    Rep->>UI: "ACT-1001 stuck in activation"
    UI->>API: POST /api/chat
    API->>G: invoke(thread)
    G->>LLM: classify (structured output)
    LLM-->>G: intent=activation, conf=0.9, order=ACT-1001
    G->>AG: POST /activation/diagnose
    AG-->>G: can_resolve, proposed_action=resend_provisioning
    G-->>G: interrupt() — pause for confirmation
    API-->>UI: status=needs_confirmation + prompt
    Rep->>UI: Approve
    UI->>API: POST /api/chat/confirm {approved:true}
    API->>G: resume(Command(resume=true))
    G->>AG: POST /activation/execute
    AG-->>G: success + actions_taken
    G->>LLM: compose rep-facing reply
    G-->>API: resolution card
    API-->>UI: status=answered + card
```

## 4. Escalation sequence — no agent/knowledge can resolve

```mermaid
sequenceDiagram
    participant Rep
    participant G as LangGraph
    participant DB as Ticket store
    participant Tier as Tier 1/2
    participant Dev as Dev/Product

    Rep->>G: unusual issue
    G->>G: triage → low confidence / "other"
    G->>DB: create_ticket(conversation, order_context, trace)
    G-->>Rep: "Opened TCK-xxxx for a specialist"
    Tier->>DB: claim + resolve + feedback(recommended_capability, gap_type)
    Dev->>DB: read capability backlog (ranked)
    Note over Dev,G: Build the recommended agent/skill → assistant resolves it next time
```

## 5. State machine

```mermaid
stateDiagram-v2
    [*] --> triage
    triage --> activation: intent=activation
    triage --> pending_order: intent=pending_order
    triage --> promo: intent=promo
    triage --> knowledge: billing / general
    triage --> ticket_fallback: other / low confidence
    activation --> confirm: proposes a change
    pending_order --> confirm: proposes a change
    promo --> confirm: proposes a change
    activation --> ticket_fallback: cannot resolve
    pending_order --> ticket_fallback: cannot resolve
    promo --> compose: resolved, no change needed
    knowledge --> compose: KB hit
    knowledge --> ticket_fallback: KB miss
    confirm --> compose: approved+executed / declined
    confirm --> ticket_fallback: execution failed
    ticket_fallback --> compose
    compose --> [*]
```

## 6. Data model

```mermaid
erDiagram
    TICKET {
        string id PK
        datetime created_at
        string status "open|in_review|resolved|closed"
        string intent
        string priority
        string summary
        string order_id
        string account_id
        json conversation
        json order_context
        json trace
        string assigned_to
        string resolution_notes
        string root_cause_category
        string recommended_capability "agent/skill to build"
        string gap_type "missing_agent|agent_failed|missing_knowledge|bad_data|training|none"
        string resolved_by
        datetime resolved_at
        string ai_category "education|agent_action|system_defect"
        string ai_reasoning
        string ai_article_id
        string ai_article_title
        string ai_capability
        datetime ai_analyzed_at
    }
    CHECKPOINT {
        string thread_id PK
        blob state "LangGraph conversation state"
    }
```

Two stores: the **ticket/feedback** database (SQLModel/SQLite locally; swap for
Postgres in production) and the **LangGraph checkpointer** (SQLite) that persists
per-conversation state so a paused confirmation can resume on the next request.

`TICKET` is the central entity above; the same SQLModel database also holds the
operational tables that back the dashboards and the newer surfaces. Each is
documented in full by its feature doc:

| Table | Purpose | Doc |
|---|---|---|
| `engagements` | One row per assistant turn/confirmation — the KPI source | [08](08-operations-dashboard.md) |
| `llm_calls` | Per-call token taxonomy + cost + fallback (true token economics) | [16](16-observability.md) |
| `guardrail_events` | Prompt-injection pattern matches (log-only, direct/indirect) | [16](16-observability.md) |
| `email_subscribers` | Report + alert + **visit-summary** recipients | [11](11-email-reports.md) |
| `production_issues`, `jira_defects` | AI-clustered systemic issues + stubbed JIRA board | [14](14-production-monitoring.md) |
| `queue_entries` | Store front-desk check-in / queue | [19](19-store-checkin-queue.md) |
| `listen_sessions` | Live Listen transcript, suggestions, summary, Playbook grade, coaching | [20](20-live-listen.md) |
| `playbook_guidelines` | The standard a Live Listen visit is graded against | [20](20-live-listen.md) |
| `enhancement_videos` | Uploaded training-video metadata (file on disk) | [21](21-training-and-enablement.md) |
| `huddle_items` | *The Opener* morning-huddle field-news items (served by the `news` MCP stub) | [10](10-a2ui-generative-ui.md) |
| `action_audit` | One row per executed mutating action — proof of the confirm-gate invariant | [16](16-observability.md) |

## 7. Key architectural decisions

| Decision | Rationale |
|---|---|
| **LangGraph** for orchestration | Native conditional routing + durable **interrupt/resume** for human-in-the-loop, with a checkpointer for per-conversation state. |
| **Existing agents over REST** | Mirrors the real distributed system; the orchestrator depends only on HTTP contracts, so pointing at production agents is a config change (`AGENT_SERVICES_BASE_URL`). |
| **Official `anthropic` SDK**, model `claude-opus-4-8` | Most capable default; triage uses **structured outputs** (`messages.parse`) for reliable intent JSON. Configurable to Sonnet/Haiku for cost. |
| **Deterministic offline fallback** | The assistant degrades gracefully (rule-based triage + templated replies) if the LLM is unavailable or unconfigured — no hard dependency for demos or outages. |
| **Confirmation gate on writes** | Account-mutating actions require explicit rep approval — safety + auditability. |
| **Feedback-as-backlog** | Tier 1/2 resolution captures *why* automation failed and *what to build*, turning support toil into a prioritized dev signal. |
| **AI-assisted triage, human-triggered action** | The Resolution Desk's classifier buckets tickets and proposes a resolution, but every action is still a rep-initiated click (or an override) — the same confirmation-gate philosophy as the live chat: AI narrows the work, a human still triggers the write. |
| **Read-only Live Listen copilot** | The live-conversation watcher only observes, suggests, and at most *diagnoses* — it never routes through the graph or executes. Accepting a suggestion re-enters the normal confirm-gated chat, so the copilot adds no new write path or audit surface. See [Live Listen](20-live-listen.md). |
| **A2UI over an MCP boundary** | Tools return structured UI element specs (not prose); the chat renders them via a `type`→component registry. The stub `MCPClient` has a real `tools/call` shape, so a production MCP order service drops in without touching the API or UI. See [A2UI](10-a2ui-generative-ui.md). |
| **One Cloud Run service (API + built UI)** | FastAPI serves the Vite bundle behind a SPA catch-all — one URL, no CORS, secrets in Secret Manager. See [Deployment](12-deployment-cloud-run.md). |

## 8. Security & compliance (prototype → production)

- **AuthN/Z.** Production: front both UIs with retail SSO; the orchestrator validates
  the rep/agent identity and role (rep vs. Tier 1/2) on every call. The prototype
  uses a stub `rep_id`.
- **Least privilege.** Only the orchestrator holds credentials for the agent
  services, the LLM, and the store. The browser never does.
- **PII handling.** Order/account context is fetched **on demand** for the active
  request and is not embedded in long-lived prompts. For production, scrub or
  tokenize PII before it reaches the model, and disable model-side retention.
- **Auditability.** Every automated change passes through `confirm` and is logged
  with the rep id, the action, params, and outcome. Tickets retain the full
  conversation + trace.
- **Data residency / model hosting.** Claude is available via the first-party
  API, AWS (Claude Platform on AWS / Bedrock), Vertex, and Foundry — choose the
  deployment that satisfies the retailer's data-residency posture without changing
  the orchestration code.

## 9. Scalability & reliability

- **Stateless orchestrator + external checkpointer.** Run N replicas behind a load
  balancer; conversation state lives in the checkpoint store (swap SQLite →
  Postgres/Redis), so any replica can resume any thread.
- **Timeouts + graceful degradation.** Every agent call is time-bounded; a failed
  agent call degrades to a ticket rather than an error.
- **Idempotent writes.** Production resolver `execute` calls should be idempotent
  (keyed by thread/action id) so a retried confirmation cannot double-apply.
