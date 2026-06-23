import type { CapabilityGap, ChatResponse, MetricsOverview, PerformanceSummary, Ticket } from "./types";

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

  chat: (message: string, thread_id: string | null, rep_id = "rep.demo") =>
    http<ChatResponse>("/api/chat", {
      method: "POST",
      body: JSON.stringify({ message, thread_id, rep_id }),
    }),

  confirm: (thread_id: string, approved: boolean) =>
    http<ChatResponse>("/api/chat/confirm", {
      method: "POST",
      body: JSON.stringify({ thread_id, approved }),
    }),

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
};
