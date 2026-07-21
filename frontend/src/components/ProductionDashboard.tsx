import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type {
  JiraDefectItem, ProductionAnalyzeResult, ProductionIssue, ProductionOverview, TicketBrief,
} from "../types";
import ProductionImpactMap from "./ProductionImpactMap";

const CATEGORY_LABEL: Record<string, string> = {
  payment: "Payment", etni: "ETNI · Number Inventory", activation: "Activation",
  backend: "Backend System", promo: "Promo Engine", billing: "Billing", other: "Other",
};

const CLOUD_SHORT: Record<string, string> = { aws_east: "AWS E", aws_west: "AWS W" };

const SCENARIOS = [
  { key: "payment", label: "Payment gateway (P1)" },
  { key: "etni", label: "ETNI outage (P2)" },
  { key: "activation", label: "Activation failures (P2)" },
  { key: "billing", label: "Billing errors (P3)" },
  { key: "promo", label: "Promo misses (P4)" },
];

function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function fmtAgo(iso: string | null | undefined): string {
  if (!iso) return "never";
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

// --------------------------------------------------------------------------- #
// Issue card
// --------------------------------------------------------------------------- #
function IssueCard({ issue, onResolve }: { issue: ProductionIssue; onResolve: (id: string) => void }) {
  const [expanded, setExpanded] = useState(false);
  const critical = issue.severity === "critical";
  return (
    <div className={`prod-issue prod-issue--${critical ? "critical" : "noncritical"}${issue.status === "resolved" ? " prod-issue--resolved" : ""}`}>
      <div className="prod-issue-head">
        <div className="prod-issue-badges">
          <span className={`prod-plevel prod-plevel--${issue.priority_level}`} title={issue.priority_label}>
            {issue.priority_level}
          </span>
          <span className="prod-cat">{CATEGORY_LABEL[issue.category] ?? issue.category}</span>
          {issue.order_blocking
            ? <span className="prod-blocking">SALES-BLOCKING</span>
            : issue.workaround_available && <span className="prod-workaround">Workaround available</span>}
          {issue.status === "resolved" && <span className="prod-resolved-tag">Resolved</span>}
        </div>
        <span className="prod-issue-time">{fmtAgo(issue.detected_at)}</span>
      </div>

      <h4 className="prod-issue-title">{issue.title}</h4>

      {/* Impact — the scope behind the P-level */}
      <div className="prod-impact">
        <span className="prod-impact-metric">
          <b>{issue.store_count}</b> store{issue.store_count === 1 ? "" : "s"}
        </span>
        <span className="prod-impact-metric">
          <b>{issue.channels.length}</b> channel{issue.channels.length === 1 ? "" : "s"}
        </span>
        <span className="prod-impact-chips">
          {issue.channels.map((key, i) => (
            <span key={key} className={`prod-chip prod-chip--chan chan--${key}`}>
              {issue.channel_labels[i] ?? key}
            </span>
          ))}
        </span>
        <span className="prod-impact-chips">
          {issue.cloud_labels.map(c => (
            <span key={c} className="prod-chip prod-chip--cloud">☁ {c}</span>
          ))}
        </span>
      </div>

      <div className="prod-issue-section">
        <div className="prod-issue-label">Problem</div>
        <p>{issue.problem_statement}</p>
      </div>
      <div className="prod-issue-section prod-issue-fix">
        <div className="prod-issue-label">Recommended fix</div>
        <p>{issue.recommended_fix}</p>
      </div>

      <div className="prod-issue-foot">
        <button className="prod-tickets-toggle" onClick={() => setExpanded(v => !v)}>
          {issue.ticket_count} escalated {issue.ticket_count === 1 ? "ticket" : "tickets"} {expanded ? "▴" : "▾"}
        </button>
        <div className="prod-issue-actions">
          {critical && (
            <span className={`prod-alert-status${issue.alert_sent ? " sent" : ""}`}>
              {issue.alert_sent ? "✉ Alert sent" : "✉ Alert not sent (no SMTP or no subscribers)"}
            </span>
          )}
          {issue.defect_key && <span className="prod-defect-key">🐞 {issue.defect_key}</span>}
          {issue.status === "active" && (
            <button className="prod-resolve-btn" onClick={() => onResolve(issue.id)}>Mark resolved</button>
          )}
        </div>
      </div>
      {expanded && (
        <div className="prod-ticket-ids">
          {issue.ticket_ids.map(id => <span key={id} className="prod-ticket-id">{id}</span>)}
        </div>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------- #
// Dashboard
// --------------------------------------------------------------------------- #
export default function ProductionDashboard() {
  const [overview, setOverview] = useState<ProductionOverview | null>(null);
  const [defects, setDefects] = useState<JiraDefectItem[]>([]);
  const [liveFeed, setLiveFeed] = useState<TicketBrief[]>([]);
  const [analyzing, setAnalyzing] = useState(false);
  const [lastResult, setLastResult] = useState<ProductionAnalyzeResult | null>(null);
  const [alertPreview, setAlertPreview] = useState<string | null>(null);
  const [simulating, setSimulating] = useState(false);
  const [scenario, setScenario] = useState("etni");
  const [expandedDefect, setExpandedDefect] = useState<string | null>(null);
  const esRef = useRef<EventSource | null>(null);

  async function reload() {
    try {
      const [ov, dj] = await Promise.all([api.productionOverview(), api.productionDefects()]);
      setOverview(ov);
      setDefects(dj.issues);
      setLiveFeed(ov.inflow.recent);
    } catch { /* backend down; keep last */ }
  }

  useEffect(() => {
    reload();
    const es = new EventSource(api.productionEventsUrl());
    esRef.current = es;
    es.addEventListener("ticket_created", (e: MessageEvent) => {
      try {
        const t: TicketBrief = JSON.parse(e.data);
        setLiveFeed(prev => [t, ...prev].slice(0, 12));
        setOverview(prev => {
          if (!prev) return prev;
          const buckets = [...prev.inflow.buckets];
          if (buckets.length) buckets[buckets.length - 1] = {
            ...buckets[buckets.length - 1],
            count: buckets[buckets.length - 1].count + 1,
          };
          return {
            ...prev,
            inflow: {
              ...prev.inflow,
              last_24h: prev.inflow.last_24h + 1,
              last_hour: prev.inflow.last_hour + 1,
              buckets,
              recent: [t, ...prev.inflow.recent].slice(0, 12),
            },
          };
        });
      } catch { /* ignore */ }
    });
    es.addEventListener("analysis_complete", () => { reload(); });
    es.addEventListener("issue_resolved", () => { reload(); });
    const poll = setInterval(reload, 60_000);
    return () => { es.close(); clearInterval(poll); };
  }, []);

  async function runAnalysis() {
    setAnalyzing(true);
    setAlertPreview(null);
    try {
      const r = await api.productionAnalyze();
      setLastResult(r);
      const preview = r.alerts?.find(a => a.preview_html)?.preview_html;
      if (preview) setAlertPreview(preview);
      await reload();
    } finally {
      setAnalyzing(false);
    }
  }

  async function simulate() {
    setSimulating(true);
    try {
      await api.productionSimulate(scenario);
      await reload();
    } finally {
      setSimulating(false);
    }
  }

  async function resolveIssue(id: string) {
    await api.resolveProductionIssue(id);
    await reload();
  }

  const inflow = overview?.inflow;
  const monitor = overview?.monitor;
  const issues = overview?.issues ?? [];
  const activeIssues = issues.filter(i => i.status === "active");
  const criticals = activeIssues.filter(i => i.severity === "critical");
  const nonCriticals = activeIssues.filter(i => i.severity === "non_critical");
  const resolved = issues.filter(i => i.status === "resolved");
  const maxBucket = Math.max(...(inflow?.buckets.map(b => b.count) ?? [0]), 1);
  const trendUp = (inflow?.last_hour ?? 0) > (inflow?.prev_hour ?? 0);

  return (
    <div className="dash">
      <div className="dash-head">
        <div>
          <h2>Production Monitor</h2>
          <p className="dash-sub">
            Live escalation inflow · AI theme detection · alerts &amp; defect filing
          </p>
        </div>
        <div className="prod-head-actions">
          <div className="prod-sim">
            <select value={scenario} onChange={e => setScenario(e.target.value)} disabled={simulating}>
              {SCENARIOS.map(s => <option key={s.key} value={s.key}>{s.label}</option>)}
            </select>
            <button className="btn ghost" onClick={simulate} disabled={simulating}>
              {simulating ? "Injecting…" : "⚡ Simulate incident"}
            </button>
          </div>
          <button className="btn primary" onClick={runAnalysis} disabled={analyzing || monitor?.running}>
            {analyzing || monitor?.running ? "Analyzing…" : "🔎 Analyze now"}
          </button>
        </div>
      </div>

      {/* KPI row */}
      <div className="kpi-grid">
        <div className="kpi big">
          <div className="kpi-val">{inflow?.last_24h ?? "—"}</div>
          <div className="kpi-label">Escalations · 24h</div>
        </div>
        <div className={`kpi${trendUp ? " warn" : ""}`}>
          <div className="kpi-val">{inflow?.last_hour ?? "—"}</div>
          <div className="kpi-label">This hour</div>
          <div className="kpi-sub">{trendUp ? "▲" : "▼"} vs {inflow?.prev_hour ?? 0} prev hour</div>
        </div>
        <div className={`kpi${criticals.length ? " warn" : " good"}`}>
          <div className="kpi-val">{criticals.length}</div>
          <div className="kpi-label">Critical issues</div>
          <div className="kpi-sub">{criticals.length ? "action required" : "none active"}</div>
        </div>
        <div className="kpi">
          <div className="kpi-val">{defects.length}</div>
          <div className="kpi-label">Defects filed</div>
          <div className="kpi-sub">JIRA (stub MCP)</div>
        </div>
        <div className="kpi">
          <div className="kpi-val">{monitor?.new_since_analysis ?? 0}</div>
          <div className="kpi-label">New since analysis</div>
          <div className="kpi-sub">auto-run at {monitor?.auto_analyze_every ?? 5} · last {fmtAgo(monitor?.last_analysis_at)}</div>
        </div>
      </div>

      {/* Impact map — escalation geography + cloud health */}
      {overview?.geo && <ProductionImpactMap geo={overview.geo} />}

      {/* Inflow chart + live feed */}
      <div className="dash-row">
        <div className="panel">
          <h3 className="prod-panel-title">Ticket inflow — last 24h <span className="prod-live-dot" title="live" /></h3>
          <div className="prod-chart">
            {inflow?.buckets.map((b, i) => (
              <div key={i} className="prod-bar-col" title={`${b.hour} — ${b.count} escalations`}>
                <div
                  className={`prod-bar${i === inflow.buckets.length - 1 ? " prod-bar--now" : ""}`}
                  style={{ height: `${Math.max(3, Math.round((b.count / maxBucket) * 100))}%` }}
                />
                {i % 4 === 0 && <span className="prod-bar-hour">{b.hour}</span>}
              </div>
            ))}
          </div>
        </div>
        <div className="panel">
          <h3 className="prod-panel-title">Live escalation feed</h3>
          <div className="prod-feed">
            {liveFeed.length === 0 && <div className="prod-empty">No escalations in the last 24h.</div>}
            {liveFeed.map(t => (
              <div key={t.id} className="prod-feed-row">
                <span className="prod-feed-time">{fmtTime(t.created_at)}</span>
                <span className={`prod-feed-pri prod-feed-pri--${t.priority}`}>{t.priority}</span>
                <span className="prod-feed-summary" title={t.summary}>{t.summary}</span>
                {t.channel && (
                  <span className={`prod-feed-chan chan--${t.channel}`} title={t.channel_label ?? t.channel}>
                    {t.channel_label ?? t.channel}
                  </span>
                )}
                {t.cloud_env && (
                  <span
                    className={`prod-feed-cloud prod-feed-cloud--${t.cloud_env}`}
                    title={t.city && t.state ? `${t.city}, ${t.state} · ${CLOUD_SHORT[t.cloud_env] ?? t.cloud_env}` : undefined}
                  >
                    {CLOUD_SHORT[t.cloud_env] ?? t.cloud_env}
                  </span>
                )}
                <span className="prod-feed-id">{t.id}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Analysis result strip */}
      {lastResult && !lastResult.status && (
        <div className="prod-result-strip">
          Analyzed {lastResult.analyzed_tickets} tickets → {lastResult.issues_found} issue
          {lastResult.issues_found === 1 ? "" : "s"}
          {lastResult.by_priority && (
            <> ({(["P1", "P2", "P3", "P4"] as const)
              .filter(p => (lastResult.by_priority?.[p] ?? 0) > 0)
              .map(p => `${lastResult.by_priority![p]} ${p}`)
              .join(" · ") || "none"})</>
          )}
          {(lastResult.new_defects?.length ?? 0) > 0 && <> · defects filed: {lastResult.new_defects!.join(", ")}</>}
          {lastResult.alerts?.some(a => a.sent > 0) && <> · alert emailed to {lastResult.alerts!.find(a => a.sent > 0)!.recipients?.length} subscriber(s)</>}
        </div>
      )}

      {/* Critical issues */}
      {criticals.length > 0 && (
        <div className="prod-section">
          <h3 className="prod-section-title prod-section-title--critical">
            🚨 Critical production issues
          </h3>
          {criticals.map(i => <IssueCard key={i.id} issue={i} onResolve={resolveIssue} />)}
        </div>
      )}

      {/* Alert preview (SMTP off) */}
      {alertPreview && (
        <div className="prod-section">
          <div className="prod-preview-head">
            <h3 className="prod-section-title">✉ Alert email preview</h3>
            <button className="btn ghost" onClick={() => setAlertPreview(null)}>Close</button>
          </div>
          <iframe className="prod-preview-frame" title="Alert preview" srcDoc={alertPreview} />
        </div>
      )}

      {/* Non-critical themes */}
      {nonCriticals.length > 0 && (
        <div className="prod-section">
          <h3 className="prod-section-title">⚠ Recurring themes (non-critical)</h3>
          {nonCriticals.map(i => <IssueCard key={i.id} issue={i} onResolve={resolveIssue} />)}
        </div>
      )}

      {activeIssues.length === 0 && (
        <div className="panel prod-all-clear">
          <span className="prod-all-clear-icon">✅</span>
          <div>
            <strong>No active production issues detected.</strong>
            <div className="prod-all-clear-sub">
              Analysis window: last {monitor?.window_hours ?? 48}h · last run {fmtAgo(monitor?.last_analysis_at)} ·
              auto-runs after {monitor?.auto_analyze_every ?? 5} new escalations.
            </div>
          </div>
        </div>
      )}

      {/* JIRA defect board */}
      <div className="prod-section">
        <h3 className="prod-section-title">🐞 Defect board — JIRA (stub MCP)</h3>
        {defects.length === 0 && (
          <div className="panel prod-empty">No defects filed yet. Non-critical recurring themes are filed here automatically after analysis.</div>
        )}
        {defects.length > 0 && (
          <div className="panel prod-defect-table">
            {defects.map(d => (
              <div key={d.key} className="prod-defect-row">
                <div className="prod-defect-main" onClick={() => setExpandedDefect(expandedDefect === d.key ? null : d.key)}>
                  <span className="prod-defect-key-cell">{d.key}</span>
                  <span className={`prod-defect-pri prod-defect-pri--${d.priority.toLowerCase()}`}>{d.priority}</span>
                  <span className="prod-defect-summary">{d.summary}</span>
                  <span className="prod-defect-status">{d.status}</span>
                  <span className="prod-defect-when">{fmtAgo(d.created_at)}</span>
                </div>
                {expandedDefect === d.key && (
                  <pre className="prod-defect-desc">{d.description}</pre>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Resolved history */}
      {resolved.length > 0 && (
        <div className="prod-section">
          <h3 className="prod-section-title prod-section-title--muted">Resolved issues</h3>
          {resolved.map(i => <IssueCard key={i.id} issue={i} onResolve={resolveIssue} />)}
        </div>
      )}
    </div>
  );
}
