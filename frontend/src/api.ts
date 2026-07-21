import type { A2UIElement, A2UIResponse, AccountSummary, AnalyzeResult, CallAgentResult, CandidateDefect, CapabilityGap, Cart, CesRouting, ChatResponse, CheckInResult, CheckoutView, CoachingResult, CXOverview, EmailSettings, EmailSubscriber, EnhancementVideo, FileDefectResult, HuddleItem, JiraDefectItem, ListenUtterance, LiveQueueSnapshot, MetricsOverview, OSTArticleRef, PerformanceSummary, PingResult, PlaybookGuideline, ProductionAnalyzeResult, ProductionIssue, ProductionOverview, QueueEntry, SendReportResult, SendSummaryResult, SendToPhoneResult, DistrictRollup, RollupBrief, StartListenResult, StopListenResult, StoreManagerBrief, StoreManagerOverview, SystemHealth, TerritoryRollup, Ticket, TicketAnalyzeResult, TrainingEnhancement, VideoStoryboard, Walkthrough } from "./types";

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

  liveQueue: () => http<LiveQueueSnapshot>("/api/queue/live"),

  checkIn: (body: { customer_name?: string; customer_phone?: string; reason: string; account_id?: string; order_id?: string }) =>
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

  listenAnalyze: (session_id: string, utterances: ListenUtterance[], record_only = false) =>
    http<AnalyzeResult>(`/api/listen/${session_id}/analyze`, {
      method: "POST",
      body: JSON.stringify({ utterances, record_only }),
    }),

  listenStop: (session_id: string) =>
    http<StopListenResult>(`/api/listen/${session_id}/stop`, { method: "POST" }),

  listenSendSummary: (session_id: string) =>
    http<SendSummaryResult>(`/api/listen/${session_id}/send-summary`, { method: "POST" }),

  // Coaching
  coachingRecent: () => http<A2UIResponse>("/api/coaching/recent"),
  coachingRecommend: (session_id: string) =>
    http<CoachingResult>(`/api/coaching/${session_id}`, { method: "POST" }),

  // Training & enablement (Settings + walkthroughs)
  trainingEnhancements: () => http<TrainingEnhancement[]>("/api/training/enhancements"),
  setEnhancementHidden: (title: string, hidden: boolean) =>
    http<{ title: string; hidden: boolean }>("/api/training/enhancements/hide", {
      method: "POST",
      body: JSON.stringify({ title, hidden }),
    }),
  generateStoryboard: (body: { title: string; detail: string; answer: string; walkthrough?: Walkthrough | null }) =>
    http<VideoStoryboard>("/api/training/storyboard", { method: "POST", body: JSON.stringify(body) }),
  // Multipart upload — must NOT set Content-Type (the browser sets the boundary).
  uploadEnhancementVideo: async (enhancementTitle: string, file: File): Promise<EnhancementVideo> => {
    const form = new FormData();
    form.append("enhancement_title", enhancementTitle);
    form.append("file", file);
    const res = await fetch("/api/training/video", { method: "POST", body: form });
    if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
    return res.json();
  },
  deleteEnhancementVideo: (id: number) =>
    fetch(`/api/training/video/${id}`, { method: "DELETE" }).then(() => undefined),

  // Playbook management (Settings)
  listPlaybookGuidelines: () => http<PlaybookGuideline[]>("/api/playbook/guidelines"),
  addPlaybookGuideline: (category: string, text: string) =>
    http<PlaybookGuideline>("/api/playbook/guidelines", {
      method: "POST",
      body: JSON.stringify({ category, text }),
    }),
  updatePlaybookGuideline: (id: number, patch: Partial<Pick<PlaybookGuideline, "category" | "text" | "active" | "sort_order">>) =>
    http<PlaybookGuideline>(`/api/playbook/guidelines/${id}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  removePlaybookGuideline: (id: number) =>
    fetch(`/api/playbook/guidelines/${id}`, { method: "DELETE" }).then(() => undefined),

  // Shopping (in-chat add-a-line / upgrade)
  shopAccount: (account_id?: string | null) =>
    http<{ summary: AccountSummary; elements: A2UIElement[] }>(`/api/shop/account${qs({ account_id: account_id ?? undefined })}`),
  shopCart: (thread_id: string) => http<Cart>(`/api/shop/cart/${thread_id}`),

  // Guided POS checkout (View Together → payment → signature), shared by the
  // rep screen and the customer phone view (/checkout/{id}).
  checkoutStart: (thread_id: string, account_id?: string | null, rep_id = "rep.demo") =>
    http<CheckoutView>("/api/shop/checkout/start", {
      method: "POST",
      body: JSON.stringify({ thread_id, account_id: account_id ?? null, rep_id }),
    }),
  checkoutGet: (id: string) => http<CheckoutView>(`/api/shop/checkout/${id}`),
  checkoutAdvance: (id: string, to = "payment") =>
    http<CheckoutView>(`/api/shop/checkout/${id}/advance`, { method: "POST", body: JSON.stringify({ to }) }),
  checkoutPay: (id: string, payment_method: string, fulfillment?: string) =>
    http<CheckoutView>(`/api/shop/checkout/${id}/pay`, {
      method: "POST",
      body: JSON.stringify({ payment_method, fulfillment: fulfillment ?? null }),
    }),
  checkoutSign: (id: string, signature?: string | null, receipt_channel?: string | null) =>
    http<CheckoutView>(`/api/shop/checkout/${id}/sign`, {
      method: "POST",
      body: JSON.stringify({ signature: signature ?? null, receipt_channel: receipt_channel ?? null }),
    }),
  checkoutSendToPhone: (id: string, channel: "sms" | "qr", origin: string) =>
    http<SendToPhoneResult>(`/api/shop/checkout/${id}/send-to-phone`, {
      method: "POST",
      body: JSON.stringify({ channel, origin }),
    }),

  // CES Routing (Settings → CES Routing)
  getCesRouting: () => http<CesRouting>("/api/settings/ces-routing"),
  setCesRoute: (intent: string, enabled: boolean, entry_agent?: string | null) =>
    http<{ intent: string; enabled: boolean; entry_agent: string | null }>("/api/settings/ces-routing", {
      method: "POST",
      body: JSON.stringify({ intent, enabled, entry_agent: entry_agent ?? null }),
    }),

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

  // Store Manager dashboard
  storeManagerOverview: () => http<StoreManagerOverview>("/api/store-manager/overview"),
  storeManagerBrief: () => http<StoreManagerBrief>("/api/store-manager/brief"),

  // District & Territory rollups (field leadership)
  districtRollup: () => http<DistrictRollup>("/api/rollup/district"),
  districtBrief: () => http<RollupBrief>("/api/rollup/district/brief"),
  territoryRollup: () => http<TerritoryRollup>("/api/rollup/territory"),
  territoryBrief: () => http<RollupBrief>("/api/rollup/territory/brief"),

  // Email reports
  emailSettings: () => http<EmailSettings>("/api/email/settings"),
  listSubscribers: () => http<EmailSubscriber[]>("/api/email/subscribers"),
  addSubscriber: (email: string, name: string, subscribed_performance: boolean, subscribed_cx: boolean, subscribed_visit_summary = true) =>
    http<EmailSubscriber>("/api/email/subscribers", {
      method: "POST",
      body: JSON.stringify({ email, name: name || null, subscribed_performance, subscribed_cx, subscribed_visit_summary }),
    }),
  updateSubscriber: (email: string, patch: Partial<Pick<EmailSubscriber, "name" | "subscribed_performance" | "subscribed_cx" | "subscribed_alerts" | "subscribed_visit_summary" | "active">>) =>
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
