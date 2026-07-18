// ── A2UI (agent-to-UI) elements ──────────────────────────────────────────
// Structured UI component specs returned by MCP tools; the chat renders each
// element by its `type`. Extend the union as new element types are added.
export interface A2UIOrder {
  order_id: string;
  order_type: string;
  status: string;
  status_tone: "ok" | "warn" | "info" | "danger";
  device: string | null;
  line: string | null;
  account_id: string | null;
  customer: string | null;
  opened_label: string;
  prompt: string;
}

export interface A2UIRecentOrders {
  type: "recent_orders";
  title: string;
  subtitle?: string;
  orders: A2UIOrder[];
}

export interface A2UITicket {
  ticket_id: string;
  summary: string;
  intent: string;
  priority: "high" | "normal" | "low";
  status: string;
  status_label: string;
  status_tone: "ok" | "warn" | "info" | "danger";
  age_label: string;
  prompt: string;
}

export interface A2UIOpenTickets {
  type: "open_tickets";
  title: string;
  subtitle?: string;
  tickets: A2UITicket[];
}

export interface A2UIEnhancement {
  tag: string;
  title: string;
  detail: string;
}

export interface A2UISystemEnhancements {
  type: "system_enhancements";
  title: string;
  subtitle?: string;
  enhancements: A2UIEnhancement[];
  suggestions: string[];
}

export interface A2UIHuddleItem {
  category: string;
  tone: "ok" | "warn" | "info" | "danger";
  title: string;
  blurb: string;
  article_id?: string | null;
}

export interface A2UIHuddleTodo {
  title: string;
  detail: string;
  article_id?: string | null;
}

export interface A2UIMorningHuddle {
  type: "morning_huddle";   // internal type; product name is "The Opener"
  title: string;
  subtitle?: string;
  todos: A2UIHuddleTodo[];
  items: A2UIHuddleItem[];
}

export interface A2UIArticleSection {
  heading: string;
  body: string;
}

export interface A2UIKnowledgeArticle {
  type: "knowledge_article";
  article_id: string;
  title: string;
  category: string;
  updated_label: string;
  summary: string;
  sections: A2UIArticleSection[];
  source: string;
}

export interface A2UIQueueEntry {
  id: string;
  customer_name: string | null;
  customer_phone: string | null;
  reason: string;
  reason_label: string;
  status: "waiting" | "in_progress";
  wait_label: string;
  assigned_rep_id: string | null;
  prompt: string;
}

export interface A2UIQueue {
  type: "queue";
  title: string;
  subtitle?: string;
  entries: A2UIQueueEntry[];
}

// Live Listen suggestion surfaced mid-conversation (see ListenSuggestion below).
export interface A2UILiveSuggestion extends ListenSuggestion {
  type: "live_suggestion";
}

export type A2UIElement =
  | A2UIRecentOrders
  | A2UIOpenTickets
  | A2UISystemEnhancements
  | A2UIMorningHuddle
  | A2UIKnowledgeArticle
  | A2UIQueue
  | A2UILiveSuggestion;

// ── Store check-in ─────────────────────────────────────────────────────────

export const VISIT_REASONS: { value: string; label: string }[] = [
  { value: "new_service", label: "New to Verizon" },
  { value: "upgrade", label: "Upgrade" },
  { value: "home", label: "Home Internet" },
  { value: "appointment", label: "Appointment" },
  { value: "pickup", label: "In-Store Pickup" },
  { value: "support", label: "Account / Billing Support" },
  { value: "other", label: "Something Else" },
];

export interface QueueEntry {
  id: string;
  created_at: string;
  updated_at: string;
  customer_name: string | null;
  customer_phone: string | null;
  reason: string;
  status: "waiting" | "in_progress";
  assigned_rep_id: string | null;
  thread_id: string | null;
  started_at: string | null;
}

export interface CheckInResult {
  entry: QueueEntry;
  queue_position: number;
}

// ── Live Listen ────────────────────────────────────────────────────────────

export interface ListenUtterance {
  speaker: string | null;
  text: string;
}

export interface ListenDiagnosis {
  can_resolve: boolean;
  root_cause: string | null;
  human_prompt: string | null;
}

export interface ListenSuggestion {
  id: string;
  intent: string;
  capability: string;
  title: string;
  summary: string;
  prompt: string;
  entities: Record<string, string>;
  confidence: number;
  tone: "info" | "warn" | "danger";
  diagnosis: ListenDiagnosis | null;
}

export interface ListenSession {
  id: string;
  rep_id: string;
  thread_id: string;
  queue_entry_id: string | null;
  customer_name: string | null;
  customer_phone: string | null;
  reason: string;
  mode: "mic" | "demo";
  status: "active" | "ended";
  created_at: string;
  ended_at: string | null;
}

export interface StartListenResult {
  session: ListenSession;
  thread_id: string;
  entities: Record<string, string>;
}

export interface AnalyzeResult {
  suggestions: ListenSuggestion[];
  entities: Record<string, string>;
}

export interface StopListenResult {
  session: ListenSession;
  recap: { utterances: number; suggestions: number; duration_label: string };
}

// Morning Huddle items — managed on the Settings page
export interface HuddleItem {
  id: number;
  category: string;
  title: string;
  blurb: string;
  article_id: string | null;
  active: boolean;
  sort_order: number;
  created_at: string;
}

export interface OSTArticleRef {
  article_id: string;
  title: string;
  category: string;
}

export interface A2UIResponse {
  elements: A2UIElement[];
}

export interface ResolutionCard {
  intent: string | null;
  status: "resolved" | "proposed" | "cancelled" | "escalated" | "info";
  root_cause: string | null;
  actions_taken: string[];
  capability: string | null;
  ticket_id: string | null;
  order_context: Record<string, any> | null;
}

export interface ConfirmationPayload {
  type: string;
  prompt: string;
  action: {
    service: string;
    operation: string;
    params: Record<string, any>;
    human_prompt: string;
  };
}

export interface ChatResponse {
  thread_id: string;
  status: "answered" | "needs_confirmation" | "escalated";
  assistant_message: string | null;
  card: ResolutionCard | null;
  a2ui: A2UIElement[] | null;
  confirmation: ConfirmationPayload | null;
  intent: string | null;
  confidence: number | null;
  ticket_id: string | null;
  trace: Array<Record<string, any>>;
}

export interface Ticket {
  id: string;
  created_at: string;
  status: "open" | "in_review" | "resolved" | "closed";
  intent: string;
  priority: string;
  summary: string;
  order_id: string | null;
  account_id: string | null;
  assigned_to: string | null;
  conversation: Array<{ role: string; content: string }>;
  order_context: Record<string, any> | null;
  trace: Array<Record<string, any>>;
  resolution_notes: string | null;
  root_cause_category: string | null;
  recommended_capability: string | null;
  gap_type: string | null;
  resolved_by: string | null;
  // AI Assisted Resolution Desk classification (set by POST /api/tickets/analyze)
  ai_category: "education" | "agent_action" | "system_defect" | null;
  ai_reasoning: string | null;
  ai_article_id: string | null;
  ai_article_title: string | null;
  ai_capability: string | null;
  ai_analyzed_at: string | null;
}

export interface TicketAnalyzeResult {
  analyzed: number;
  education: number;
  agent_action: number;
  system_defect: number;
  tickets: Ticket[];
}

export interface CallAgentResult {
  resolved: boolean;
  ticket: Ticket;
  diagnosis: {
    root_cause: string | null;
    summary: string;
    actions_taken?: string[];
  };
}

export interface CandidateDefect {
  key: string;
  url: string;
  summary: string;
  status: string;
  labels: string[];
}

export interface FileDefectResult {
  ticket: Ticket;
  defect_key: string;
}

export interface CapabilityGap {
  capability: string;
  ticket_count: number;
  score: number;
  gap_types: Record<string, number>;
  intents: Record<string, number>;
  examples: Array<{ ticket_id: string; summary: string }>;
}

export interface PerformanceSummary {
  generated_at: string;
  model: string;
  headline: string;
  trending_issues: string;
  containment_escalation: string;
  backlog_priorities: string;
}

export interface EmailSubscriber {
  id: number;
  email: string;
  name: string | null;
  subscribed_performance: boolean;
  subscribed_cx: boolean;
  subscribed_alerts: boolean;
  active: boolean;
  created_at: string;
}

export interface SendReportResult {
  sent: number;
  previewed: boolean;
  recipients: string[];
  preview_html?: string;
  warning?: string;
  error?: string;
}

export interface EmailSettings {
  smtp_enabled: boolean;
  smtp_host: string | null;
  smtp_port: number;
  smtp_user: string | null;
  smtp_tls: boolean;
}

export interface CXTrace {
  id: string;
  started_at: string;
  latency_ms: number;
  input_tokens: number | null;
  output_tokens: number | null;
  total_tokens: number | null;
  error: string | null;
  intent: string | null;
  url: string | null;
}

export interface CXOverview {
  configured: boolean;
  langsmith_project: string | null;
  generated_at: string;
  error?: string;
  no_traces_yet?: boolean;
  period: { start: string | null; end: string | null };
  overview: {
    conversations: number;
    traces_captured: number;
    error_count: number;
    error_rate: number;
  };
  latency_ms: {
    p50: number;
    p95: number;
    p99: number;
    avg: number;
    by_intent: Array<{ intent: string; avg_ms: number; count: number }>;
  };
  tokens: {
    avg_input: number;
    avg_output: number;
    avg_total: number;
    total_input: number;
    total_output: number;
  };
  cost_usd: {
    avg_per_conversation: number;
    total: number;
    model: string;
    input_rate_per_million: number;
    output_rate_per_million: number;
  };
  timeseries: Array<{
    date: string;
    conversations: number;
    avg_latency_ms: number;
    avg_tokens: number;
    error_count: number;
  }>;
  recent_traces: CXTrace[];
  observability: ObservabilityOverview;
  llm_usage: LLMUsageOverview;
}

// ── Observability P0/P1 (see docs/16 and docs/17) ──────────────────────────

export interface ObservabilityOverview {
  generated_at: string;
  conversation_health: {
    turns_per_conversation: { p50: number; p90: number; p99: number; conversations_measured: number };
    looping_threshold: number;
    looping_conversations: number;
    confirmation_reversal_rate: number;
    confirmations_declined: number;
    confirmations_approved: number;
    out_of_scope_rate: number;
    out_of_scope_trend: string | null;
    re_ask_rate: number;
    abandonment_rate: number;
    repeat_contact_rate: number;
  };
  sales_intent: Array<{
    sales_intent: string; // nse | aal | up | unclassified
    count: number;
    auto_resolved: number;
    escalated: number;
    avg_confidence: number;
    containment_rate: number;
  }>;
  guardrail: {
    actions_executed: number;
    unconfirmed_mutation_count: number;
    unconfirmed_mutation_examples: Array<{
      thread_id: string | null; service: string; operation: string; created_at: string;
    }>;
    injection_attempts: number;
    injection_examples: Array<{
      thread_id: string | null; node: string; source: string;
      pattern: string; snippet: string; created_at: string;
    }>;
  };
}

export interface LLMUsageOverview {
  generated_at: string;
  calls_recorded: number;
  token_taxonomy: {
    avg_input: number; avg_output: number; avg_thinking: number;
    avg_cache_creation: number; avg_cache_read: number;
    total_input: number; total_output: number; total_thinking: number;
    total_cache_creation: number; total_cache_read: number;
  };
  cost_usd: {
    total: number; avg_per_call: number;
    cost_of_failure: number; cost_of_failure_pct: number;
  };
  by_function: Array<{
    function: string; calls: number; fallback_calls: number;
    total_cost_usd: number; avg_latency_ms: number; fallback_rate: number;
  }>;
  by_intent: Array<{ intent: string; calls: number; total_cost_usd: number }>;
  by_outcome: Array<{ outcome: string; calls: number; total_cost_usd: number }>;
}

export interface SystemHealth {
  status: "operational" | "degraded" | "outage";
  description: string;
  workaround: string;
  hard_stop: boolean;
  updated_at: string | null;
  notify?: boolean;
}

export interface PingResult {
  ok: boolean;
  server_ts: string;
  client_ip: string;
  region?: string;
}

export interface MetricsOverview {
  generated_at: string;
  engagement: {
    conversations: number;
    interactions: number;
    active_reps: number;
    avg_confidence: number;
    messages_per_conversation: number;
  };
  outcomes: {
    auto_resolved: number;
    escalated: number;
    cancelled: number;
    total: number;
    containment_rate: number;
    escalation_rate: number;
  };
  confirmations: {
    requested: number;
    approved: number;
    declined: number;
    approval_rate: number;
  };
  intents: Array<{
    intent: string;
    count: number;
    auto_resolved: number;
    escalated: number;
    avg_confidence: number;
  }>;
  capabilities: Array<{ capability: string; resolutions: number }>;
  tickets: {
    open: number;
    in_review: number;
    resolved: number;
    closed: number;
    total: number;
    avg_resolution_hours: number | null;
    by_intent: Array<{ intent: string; count: number }>;
  };
  timeseries: Array<{
    date: string;
    interactions: number;
    auto_resolved: number;
    escalated: number;
  }>;
}

// ── Production Monitor ────────────────────────────────────────────────────

export interface TicketBrief {
  id: string;
  created_at: string;
  intent: string;
  priority: string;
  rep_id: string | null;
  summary: string;
}

export interface ProductionIssue {
  id: string;
  detected_at: string | null;
  updated_at: string | null;
  severity: "critical" | "non_critical";
  category: string; // payment | etni | activation | backend | promo | billing | other
  title: string;
  problem_statement: string;
  recommended_fix: string;
  order_blocking: boolean;
  ticket_ids: string[];
  ticket_count: number;
  status: "active" | "resolved";
  alert_sent: boolean;
  defect_key: string | null;
}

export interface ProductionOverview {
  generated_at: string;
  inflow: {
    last_24h: number;
    last_hour: number;
    prev_hour: number;
    buckets: Array<{ hour: string; count: number }>;
    recent: TicketBrief[];
  };
  issues: ProductionIssue[];
  monitor: {
    last_analysis_at: string | null;
    new_since_analysis: number;
    auto_analyze_every: number;
    running: boolean;
    window_hours: number;
  };
}

export interface ProductionAnalyzeResult {
  status?: string; // "already_running"
  analyzed_tickets?: number;
  issues_found?: number;
  critical?: number;
  non_critical?: number;
  alerts?: Array<{
    issue_id: string;
    title: string;
    sent: number;
    previewed?: boolean;
    recipients?: string[];
    preview_html?: string;
    warning?: string;
    error?: string;
  }>;
  new_defects?: string[];
  last_analysis_at?: string;
}

export interface JiraDefectItem {
  key: string;
  url: string;
  summary: string;
  description: string;
  priority: string;
  labels: string[];
  status: string;
  issue_id: string | null;
  created_at: string | null;
}
