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

export type A2UIElement = A2UIRecentOrders | A2UIOpenTickets;

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
