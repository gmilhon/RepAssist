import type { A2UIResponse, CapabilityGap, ChatResponse, CXOverview, EmailSettings, EmailSubscriber, HuddleItem, MetricsOverview, OSTArticleRef, PerformanceSummary, SendReportResult, Ticket } from "./types";

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
  updateSubscriber: (email: string, patch: Partial<Pick<EmailSubscriber, "name" | "subscribed_performance" | "subscribed_cx" | "active">>) =>
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
