import { useEffect, useState, type ReactNode } from "react";
import { api } from "../api";
import type { MetricsOverview, PerformanceSummary } from "../types";
import { CapabilityBacklog } from "./InsightsPanel";
import SendReportButton from "./SendReportButton";

const pct = (x: number) => `${Math.round(x * 100)}%`;
const niceIntent = (s: string) => s.replace("_", " ");

// --------------------------------------------------------------------------- #
// Date range helpers
// --------------------------------------------------------------------------- #
type Preset = "1d" | "1w" | "1m" | "ytd";

function toISO(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function presetRange(p: Preset): { start: string; end: string } {
  const today = new Date();
  const end = toISO(today);
  if (p === "1d") return { start: end, end };
  if (p === "1w") {
    const s = new Date(today);
    s.setDate(s.getDate() - 6);
    return { start: toISO(s), end };
  }
  if (p === "1m") {
    const s = new Date(today);
    s.setDate(s.getDate() - 29);
    return { start: toISO(s), end };
  }
  // ytd
  return { start: `${today.getFullYear()}-01-01`, end };
}

// --------------------------------------------------------------------------- #
// DateBar
// --------------------------------------------------------------------------- #
const PRESETS: { key: Preset; label: string }[] = [
  { key: "1d", label: "1 Day" },
  { key: "1w", label: "1 Week" },
  { key: "1m", label: "1 Month" },
  { key: "ytd", label: "YTD" },
];

function DateBar({
  preset,
  range,
  onPreset,
  onRangeChange,
}: {
  preset: Preset | null;
  range: { start: string; end: string };
  onPreset: (p: Preset) => void;
  onRangeChange: (r: { start: string; end: string }) => void;
}) {
  return (
    <div className="date-bar">
      <div className="date-presets">
        {PRESETS.map(({ key, label }) => (
          <button
            key={key}
            className={`preset-btn${preset === key ? " active" : ""}`}
            onClick={() => onPreset(key)}
          >
            {label}
          </button>
        ))}
      </div>
      <div className="date-divider" />
      <div className="date-inputs">
        <input
          type="date"
          value={range.start}
          max={range.end}
          onChange={(e) => {
            if (e.target.value) onRangeChange({ ...range, start: e.target.value });
          }}
        />
        <span className="date-sep">→</span>
        <input
          type="date"
          value={range.end}
          min={range.start}
          onChange={(e) => {
            if (e.target.value) onRangeChange({ ...range, end: e.target.value });
          }}
        />
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------- #
// ExecSummaryPanel — re-generates whenever start/end changes
// --------------------------------------------------------------------------- #
function ExecSummaryPanel({ start, end }: { start: string; end: string }) {
  const [summary, setSummary] = useState<PerformanceSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  function load() {
    setLoading(true);
    setErr(null);
    api
      .metricsSummary(start, end)
      .then(setSummary)
      .catch((e) => setErr(String(e)))
      .finally(() => setLoading(false));
  }
  useEffect(load, [start, end]); // eslint-disable-line react-hooks/exhaustive-deps

  const modelLabel = summary
    ? summary.model === "mock"
      ? "Mock summary"
      : `claude-${summary.model.split("-").slice(1).join("-")}`
    : null;

  return (
    <section className="exec-summary">
      <div className="exec-summary-head">
        <h3>Executive Summary</h3>
        <div className="exec-summary-right">
          {modelLabel && <span className="ai-badge">✦ {modelLabel}</span>}
          <button className="btn ghost small" onClick={load} disabled={loading}>
            {loading ? "Generating…" : "↻ Regenerate"}
          </button>
        </div>
      </div>

      {loading && (
        <div className="exec-loading">
          <div className="exec-shimmer exec-shimmer-headline" />
          <div className="exec-cols">
            <div className="exec-shimmer exec-shimmer-col" />
            <div className="exec-shimmer exec-shimmer-col" />
            <div className="exec-shimmer exec-shimmer-col" />
          </div>
        </div>
      )}

      {!loading && err && (
        <p className="muted" style={{ margin: "12px 0 0" }}>
          Could not generate summary: {err}
        </p>
      )}

      {!loading && summary && (
        <>
          <p className="exec-headline">{summary.headline}</p>
          <div className="exec-cols">
            <div className="exec-col exec-col-warn">
              <div className="exec-col-title">Trending Issues</div>
              <p className="exec-col-text">{summary.trending_issues}</p>
            </div>
            <div className="exec-col exec-col-info">
              <div className="exec-col-title">Containment &amp; Escalation</div>
              <p className="exec-col-text">{summary.containment_escalation}</p>
            </div>
            <div className="exec-col exec-col-ok">
              <div className="exec-col-title">Backlog Priorities</div>
              <p className="exec-col-text">{summary.backlog_priorities}</p>
            </div>
          </div>
          <div className="exec-meta">
            Generated{" "}
            {new Date(summary.generated_at).toLocaleTimeString([], {
              hour: "2-digit",
              minute: "2-digit",
            })}
          </div>
        </>
      )}
    </section>
  );
}

// --------------------------------------------------------------------------- #
// Main dashboard
// --------------------------------------------------------------------------- #
export default function OperationsDashboard() {
  const [m, setM] = useState<MetricsOverview | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [preset, setPreset] = useState<Preset | null>("1m");
  const [dateRange, setDateRange] = useState(() => presetRange("1m"));

  function handlePreset(p: Preset) {
    setPreset(p);
    setDateRange(presetRange(p));
  }

  function handleRangeChange(r: { start: string; end: string }) {
    setPreset(null);
    setDateRange(r);
  }

  function load() {
    api
      .metricsOverview(dateRange.start, dateRange.end)
      .then(setM)
      .catch((e) => setErr(String(e)));
  }
  useEffect(load, [dateRange.start, dateRange.end]); // eslint-disable-line react-hooks/exhaustive-deps

  // Human-readable date label for the subtitle
  const fmt = (iso: string, showYear = false) =>
    new Date(`${iso}T12:00:00`).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      ...(showYear ? { year: "numeric" } : {}),
    });
  const dateLabel =
    dateRange.start === dateRange.end
      ? fmt(dateRange.start, true)
      : `${fmt(dateRange.start)} – ${fmt(dateRange.end, true)}`;

  if (err)
    return (
      <div className="dash">
        <p className="muted pad">Couldn't load metrics: {err}</p>
      </div>
    );
  if (!m)
    return (
      <div className="dash">
        <p className="muted pad">Loading metrics…</p>
      </div>
    );

  const o = m.outcomes;
  const c = m.confirmations;
  const maxIntent = Math.max(1, ...m.intents.map((i) => i.count));
  const maxCap = Math.max(1, ...m.capabilities.map((c2) => c2.resolutions));

  return (
    <div className="dash">
      <div className="dash-head">
        <div>
          <h2>Performance</h2>
          <p className="muted">
            Live KPIs for the Rep Assist solution · {dateLabel}
          </p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <SendReportButton reportType="performance" start={dateRange.start} end={dateRange.end} />
          <button className="btn ghost" onClick={load}>↻ Refresh</button>
        </div>
      </div>

      <DateBar
        preset={preset}
        range={dateRange}
        onPreset={handlePreset}
        onRangeChange={handleRangeChange}
      />

      <ExecSummaryPanel start={dateRange.start} end={dateRange.end} />

      {/* KPI cards */}
      <div className="kpi-grid">
        <Kpi label="Conversations" value={m.engagement.conversations} sub={`${m.engagement.active_reps} active reps`} />
        <Kpi label="Containment rate" value={pct(o.containment_rate)} sub={`${o.auto_resolved} auto-resolved`} tone="good" big />
        <Kpi label="Escalation rate" value={pct(o.escalation_rate)} sub={`${o.escalated} to humans`} tone="warn" />
        <Kpi label="Confirm approval" value={pct(c.approval_rate)} sub={`${c.approved}/${c.approved + c.declined} approved`} />
        <Kpi label="Avg triage confidence" value={pct(m.engagement.avg_confidence)} />
        <Kpi label="Open tickets" value={m.tickets.open} sub={`${m.tickets.total} total`} tone={m.tickets.open > 12 ? "warn" : undefined} />
        <Kpi label="Avg resolution" value={m.tickets.avg_resolution_hours != null ? `${m.tickets.avg_resolution_hours}h` : "—"} sub="time on desk" />
        <Kpi label="Declined fixes" value={o.cancelled} sub="rep said no" />
      </div>

      {/* Outcomes + timeseries */}
      <div className="dash-row">
        <section className="panel">
          <div className="panel-head"><h3>Outcomes</h3><span className="panel-sub">{o.total} interactions</span></div>
          <div className="stack">
            <div className="stack-seg resolved" style={{ width: `${(o.auto_resolved / o.total) * 100}%` }} title={`Auto-resolved: ${o.auto_resolved}`} />
            <div className="stack-seg cancelled" style={{ width: `${(o.cancelled / o.total) * 100}%` }} title={`Declined: ${o.cancelled}`} />
            <div className="stack-seg escalated" style={{ width: `${(o.escalated / o.total) * 100}%` }} title={`Escalated: ${o.escalated}`} />
          </div>
          <div className="legend">
            <span><i className="sw resolved" /> Auto-resolved {o.auto_resolved}</span>
            <span><i className="sw cancelled" /> Declined {o.cancelled}</span>
            <span><i className="sw escalated" /> Escalated {o.escalated}</span>
          </div>
          <div className="funnel">
            <FunnelStep label="Interactions" value={m.engagement.interactions} of={m.engagement.interactions} />
            <FunnelStep label="Confirmations requested" value={c.requested} of={m.engagement.interactions} />
            <FunnelStep label="Resolved by agent" value={o.auto_resolved} of={m.engagement.interactions} tone="good" />
            <FunnelStep label="Escalated to human" value={o.escalated} of={m.engagement.interactions} tone="warn" />
          </div>
        </section>

        <section className="panel">
          <div className="panel-head"><h3>Interactions over time</h3><span className="panel-sub">resolved vs escalated / day</span></div>
          <TimeSeries data={m.timeseries} />
        </section>
      </div>

      {/* Intent + capability */}
      <div className="dash-row">
        <section className="panel">
          <div className="panel-head"><h3>Volume by intent</h3><span className="panel-sub">containment per intent</span></div>
          <div className="hbars">
            {m.intents.map((it) => (
              <div key={it.intent} className="hbar-row">
                <div className="hbar-label">{niceIntent(it.intent)}</div>
                <div className="hbar-track">
                  <div className="hbar-fill" style={{ width: `${(it.count / maxIntent) * 100}%` }}>
                    <span className="hbar-inner">{Math.round((it.auto_resolved / it.count) * 100) || 0}% contained</span>
                  </div>
                </div>
                <div className="hbar-num">{it.count}</div>
              </div>
            ))}
          </div>
        </section>

        <section className="panel">
          <div className="panel-head"><h3>Top resolving agents</h3><span className="panel-sub">auto-resolutions</span></div>
          <div className="hbars">
            {m.capabilities.map((cap) => (
              <div key={cap.capability} className="hbar-row">
                <div className="hbar-label wide">{cap.capability}</div>
                <div className="hbar-track">
                  <div className="hbar-fill green" style={{ width: `${(cap.resolutions / maxCap) * 100}%` }} />
                </div>
                <div className="hbar-num">{cap.resolutions}</div>
              </div>
            ))}
          </div>
        </section>
      </div>

      {/* Ticket health */}
      <section className="panel">
        <div className="panel-head"><h3>Resolution Desk health</h3><span className="panel-sub">human-in-the-loop queue</span></div>
        <div className="ticket-stats">
          <TicketStat label="Open" value={m.tickets.open} tone="open" />
          <TicketStat label="In review" value={m.tickets.in_review} tone="review" />
          <TicketStat label="Resolved" value={m.tickets.resolved} tone="resolved" />
          <TicketStat label="Closed" value={m.tickets.closed} />
          <TicketStat label="Avg time" value={m.tickets.avg_resolution_hours != null ? `${m.tickets.avg_resolution_hours}h` : "—"} />
        </div>
        <div className="by-intent">
          {m.tickets.by_intent.map((b) => (
            <span key={b.intent} className="chip-stat"><b>{b.count}</b> {niceIntent(b.intent)}</span>
          ))}
        </div>
      </section>

      <CapabilityBacklog start={dateRange.start} end={dateRange.end} />
    </div>
  );
}

// --------------------------------------------------------------------------- #
// Small presentational components (unchanged)
// --------------------------------------------------------------------------- #
function Kpi({ label, value, sub, tone, big }: { label: string; value: ReactNode; sub?: string; tone?: "good" | "warn"; big?: boolean }) {
  return (
    <div className={`kpi ${tone ?? ""} ${big ? "big" : ""}`}>
      <div className="kpi-val">{value}</div>
      <div className="kpi-label">{label}</div>
      {sub && <div className="kpi-sub">{sub}</div>}
    </div>
  );
}

function FunnelStep({ label, value, of, tone }: { label: string; value: number; of: number; tone?: "good" | "warn" }) {
  return (
    <div className="funnel-step">
      <div className="funnel-bar-track">
        <div className={`funnel-bar ${tone ?? ""}`} style={{ width: `${of ? (value / of) * 100 : 0}%` }} />
      </div>
      <div className="funnel-meta"><span>{label}</span><b>{value}</b></div>
    </div>
  );
}

function TicketStat({ label, value, tone }: { label: string; value: ReactNode; tone?: string }) {
  return (
    <div className={`tstat ${tone ?? ""}`}>
      <div className="tstat-val">{value}</div>
      <div className="tstat-label">{label}</div>
    </div>
  );
}

function TimeSeries({ data }: { data: MetricsOverview["timeseries"] }) {
  // Fixed viewBox: a constant aspect ratio keeps the chart from collapsing
  // vertically when there are many days (e.g. YTD ~ 190 points). Bar widths
  // and label density adapt to the number of points instead of the width.
  const W = 760;
  const H = 170;
  const pad = { l: 28, r: 8, t: 12, b: 26 };
  const n = Math.max(1, data.length);
  const max = Math.max(1, ...data.map((d) => d.auto_resolved + d.escalated));
  const innerH = H - pad.t - pad.b;
  const step = (W - pad.l - pad.r) / n;
  const bw = Math.max(1.5, Math.min(26, step * 0.7));
  // Cap visible x-axis labels to ~12 so they never overlap.
  const labelEvery = Math.max(1, Math.ceil(n / 12));

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="ts" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Interactions per day, resolved versus escalated">
      {[0, 0.5, 1].map((g) => {
        const y = pad.t + innerH * (1 - g);
        return <g key={g}>
          <line x1={pad.l} y1={y} x2={W - pad.r} y2={y} className="ts-grid" />
          <text x={4} y={y + 3} className="ts-axis">{Math.round(max * g)}</text>
        </g>;
      })}
      {data.map((d, i) => {
        const x = pad.l + i * step + (step - bw) / 2;
        const rH = (d.auto_resolved / max) * innerH;
        const eH = (d.escalated / max) * innerH;
        const yR = pad.t + innerH - rH;
        const yE = yR - eH;
        const label = d.date.slice(5);
        return (
          <g key={d.date}>
            <rect x={x} y={yR} width={bw} height={rH} className="ts-resolved" rx={bw > 3 ? 2 : 0} />
            <rect x={x} y={yE} width={bw} height={eH} className="ts-escalated" rx={bw > 3 ? 2 : 0} />
            {i % labelEvery === 0 && <text x={x + bw / 2} y={H - 8} className="ts-axis" textAnchor="middle">{label}</text>}
          </g>
        );
      })}
    </svg>
  );
}
