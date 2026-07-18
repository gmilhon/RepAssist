import type { A2UIResponse, AnalyzeResult, CallAgentResult, CandidateDefect, CapabilityGap, ChatResponse, CheckInResult, CXOverview, EmailSettings, EmailSubscriber, FileDefectResult, HuddleItem, JiraDefectItem, ListenUtterance, MetricsOverview, OSTArticleRef, PerformanceSummary, PingResult, ProductionAnalyzeResult, ProductionIssue, ProductionOverview, QueueEntry, SendReportResult, StartListenResult, StopListenResult, SystemHealth, Ticket, TicketAnalyzeResult } from "./types";

async function http<T>(url: string, opts?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json() as Promise<T>;
}

function qs(params: Record<string, string | undefined>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== "") p.set(k, v);
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}

export const api = {
  health: () => http<Record<string, any>>("/health"),

  // System health status
  getSystemHealth: () => http<SystemHealth>("/api/system-health"),
  setSystemHealth: (body: { status: string; description: string; workaround: string; hard_stop: boolean; notify?: boolean }) =>
    http<SystemHealth>("/api/system-health", { method: "POST", body: JSON.stringify(body) }),
  healthEventsUrl: () => "/api/system-health/events",
  ping: () => http<PingResult>("/api/system-health/ping"),
  pingRegion: (region: "east" | "central" | "west") =>
    http<PingResult>(`/api/system-health/ping/${region}`),

  // Production Monitor
  productionOverview: () => http<ProductionOverview>("/api/production/overview"),
  productionAnalyze: () =>
    http<ProductionAnalyzeResult>("/api/production/analyze", { method: "POST" }),
  productionSimulate: (scenario: string) =>
    http<{ scenario: string; created: number }>("/api/production/simulate", {
      method: "POST", body: JSON.stringify({ scenario }),
    }),
  productionDefects: () => http<{ issues: JiraDefectItem[]; total: number }>("/api/production/defects"),
  resolveProductionIssue: (id: string) =>
    http<ProductionIssue>(`/api/production/issues/${id}/resolve`, { method: "POST" }),
  productionEventsUrl: () => "/api/production/events",

  chat: (message: string, thread_id: string | null, rep_id = "rep.demo", initial_entities?: Record<string, string>) =>
    http<ChatResponse>("/api/chat", {
      method: "POST",
      body: JSON.stringify({ message, thread_id, rep_id, initial_entities: initial_entities ?? null }),
    }),

  confirm: (thread_id: string, approved: boolean) =>
    http<ChatResponse>("/api/chat/confirm", {
      method: "POST",
      body: JSON.stringify({ thread_id, approved }),
    }),

  // A2UI elements sourced from MCP tools
  recentOrders: (rep_id = "rep.demo") =>
    http<A2UIResponse>(`/api/mcp/recent-orders${qs({ rep_id })}`),

  openTickets: (rep_id = "rep.demo") =>
    http<A2UIResponse>(`/api/mcp/open-tickets${qs({ rep_id })}`),

  systemEnhancements: () => http<A2UIResponse>("/api/mcp/system-enhancements"),

  morningHuddle: () => http<A2UIResponse>("/api/mcp/morning-huddle"),

  ostArticle: (id: string) => http<A2UIResponse>(`/api/mcp/ost-article${qs({ id })}`),

  queue: () => http<A2UIResponse>("/api/mcp/queue"),

  checkIn: (body: { customer_name?: string; customer_phone?: string; reason: string }) =>
    http<CheckInResult>("/api/queue/checkin", { method: "POST", body: JSON.stringify(body) }),

  assistQueueEntry: (id: string, rep_id = "rep.demo", thread_id?: string | null) =>
    http<{ entry: QueueEntry }>(`/api/queue/${id}/assist`, {
      method: "POST",
      body: JSON.stringify({ rep_id, thread_id: thread_id ?? null }),
    }),

  // Live Listen
  listenStart: (queue_entry_id: string, thread_id: string | null, mode: "mic" | "demo", rep_id = "rep.demo") =>
    http<StartListenResult>("/api/listen/start", {
      method: "POST",
      body: JSON.stringify({ rep_id, queue_entry_id, thread_id, mode }),
    }),

  listenAnalyze: (session_id: string, utterances: ListenUtterance[]) =>
    http<AnalyzeResult>(`/api/listen/${session_id}/analyze`, {
      method: "POST",
      body: JSON.stringify({ utterances }),
    }),

  listenStop: (session_id: string) =>
    http<StopListenResult>(`/api/listen/${session_id}/stop`, { method: "POST" }),

  // Morning Huddle management (Settings)
  listHuddleItems: () => http<HuddleItem[]>("/api/huddle/items"),
  listHuddleArticles: () => http<OSTArticleRef[]>("/api/huddle/articles"),
  addHuddleItem: (body: { category: string; title: string; blurb: string; article_id: string | null }) =>
    http<HuddleItem>("/api/huddle/items", { method: "POST", body: JSON.stringify(body) }),
  updateHuddleItem: (id: number, patch: Partial<Pick<HuddleItem, "category" | "title" | "blurb" | "article_id" | "active" | "sort_order">>) =>
    http<HuddleItem>(`/api/huddle/items/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
  removeHuddleItem: (id: number) =>
    fetch(`/api/huddle/items/${id}`, { method: "DELETE" }),

  listTickets: (status?: string) =>
    http<Ticket[]>(`/api/tickets${status ? `?status=${status}` : ""}`),

  getTicket: (id: string) => http<Ticket>(`/api/tickets/${id}`),

  claimTicket: (id: string, agent: string) =>
    http<Ticket>(`/api/tickets/${id}/claim`, {
      method: "POST",
      body: JSON.stringify({ agent }),
    }),

  resolveTicket: (
    id: string,
    body: {
      resolution_notes: string;
      root_cause_category: string;
      recommended_capability: string;
      gap_type: string;
      resolved_by: string;
      close_only?: boolean;
    }
  ) =>
    http<Ticket>(`/api/tickets/${id}/resolve`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  analyzeTickets: (status: "open" | "in_review") =>
    http<TicketAnalyzeResult>("/api/tickets/analyze", {
      method: "POST",
      body: JSON.stringify({ status }),
    }),

  resolveEducation: (id: string, body: { article_id: string; resolved_by: string; notes?: string }) =>
    http<Ticket>(`/api/tickets/${id}/resolve-education`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  callAgent: (id: string, resolved_by: string) =>
    http<CallAgentResult>(`/api/tickets/${id}/call-agent`, {
      method: "POST",
      body: JSON.stringify({ resolved_by }),
    }),

  candidateDefects: (id: string) =>
    http<{ issues: CandidateDefect[] }>(`/api/tickets/${id}/candidate-defects`),

  fileDefect: (
    id: string,
    body: { resolved_by: string; gap_type: string; attach_to?: string; recommended_capability?: string }
  ) =>
    http<FileDefectResult>(`/api/tickets/${id}/file-defect`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  capabilityGaps: (start?: string, end?: string) =>
    http<{ gaps: CapabilityGap[]; count: number }>(`/api/insights/capability-gaps${qs({ start, end })}`),

  metricsOverview: (start?: string, end?: string) =>
    http<MetricsOverview>(`/api/metrics/overview${qs({ start, end })}`),

  metricsSummary: (start?: string, end?: string) =>
    http<PerformanceSummary>(`/api/metrics/summary${qs({ start, end })}`),

  cxOverview: (start?: string, end?: string) =>
    http<CXOverview>(`/api/cx/overview${qs({ start, end })}`),

  // Email reports
  emailSettings: () => http<EmailSettings>("/api/email/settings"),
  listSubscribers: () => http<EmailSubscriber[]>("/api/email/subscribers"),
  addSubscriber: (email: string, name: string, subscribed_performance: boolean, subscribed_cx: boolean) =>
    http<EmailSubscriber>("/api/email/subscribers", {
      method: "POST",
      body: JSON.stringify({ email, name: name || null, subscribed_performance, subscribed_cx }),
    }),
  updateSubscriber: (email: string, patch: Partial<Pick<EmailSubscriber, "name" | "subscribed_performance" | "subscribed_cx" | "subscribed_alerts" | "active">>) =>
    http<EmailSubscriber>(`/api/email/subscribers/${encodeURIComponent(email)}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  removeSubscriber: (email: string) =>
    fetch(`/api/email/subscribers/${encodeURIComponent(email)}`, { method: "DELETE" }),
  sendReport: (report_type: "performance" | "cx", start?: string, end?: string) =>
    http<SendReportResult>("/api/email/send-report", {
      method: "POST",
      body: JSON.stringify({ report_type, start: start ?? null, end: end ?? null }),
    }),
};
