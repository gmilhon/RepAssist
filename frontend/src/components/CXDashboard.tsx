import { useEffect, useState } from "react";
import { api } from "../api";
import type { CXOverview } from "../types";

// --------------------------------------------------------------------------- //
// Helpers
// --------------------------------------------------------------------------- //
type Preset = "7d" | "1m" | "3m" | "ytd";

function toISO(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function presetRange(p: Preset): { start: string; end: string } {
  const end = new Date();
  const start = new Date(end);
  if (p === "7d") { start.setDate(end.getDate() - 6); }
  else if (p === "1m") { start.setMonth(end.getMonth() - 1); }
  else if (p === "3m") { start.setMonth(end.getMonth() - 3); }
  else {
    start.setMonth(0); start.setDate(1);
  }
  return { start: toISO(start), end: toISO(end) };
}

function fmt(n: number, dec = 0) {
  return n.toLocaleString(undefined, { maximumFractionDigits: dec });
}

function fmtMs(ms: number) {
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms`;
}

function fmtPct(n: number) {
  return `${(n * 100).toFixed(2)}%`;
}

function fmtCost(n: number) {
  return n < 0.001 ? `$${n.toFixed(5)}` : `$${n.toFixed(3)}`;
}

// --------------------------------------------------------------------------- //
// Sub-components
// --------------------------------------------------------------------------- //

function StatusBanner({ data }: { data: CXOverview }) {
  if (data.configured && data.no_traces_yet) {
    return (
      <div className="cx-banner cx-banner--live">
        LangSmith connected · project: <strong>{data.langsmith_project}</strong> ·{" "}
        No traces yet — send a conversation through Rep Assist to start tracing.
      </div>
    );
  }
  if (data.configured) {
    return (
      <div className="cx-banner cx-banner--live">
        LangSmith connected · project: <strong>{data.langsmith_project}</strong> ·{" "}
        {fmt(data.overview.traces_captured)} traces captured
      </div>
    );
  }
  if (data.error) {
    const is403 = data.error.includes("403") || data.error.includes("Forbidden");
    return (
      <div className="cx-banner cx-banner--error">
        {is403
          ? "Service key detected — tracing is active but this dashboard requires a Personal API key to read traces. Go to smith.langchain.com → Settings → API Keys → Create API Key (Personal Access Token, starts with lsv2_pt_)."
          : "LangSmith key set but returned an error — showing sample data. Check your key at smith.langchain.com and restart the backend."}
        <br />
        <span className="cx-banner-detail">{data.error}</span>
      </div>
    );
  }
  return (
    <div className="cx-banner cx-banner--mock">
      LangSmith not configured — showing sample data. Add{" "}
      <code>LANGCHAIN_API_KEY</code> to <code>backend/.env</code> to enable live
      tracing.
    </div>
  );
}

interface KpiCardProps {
  label: string;
  value: string;
  sub?: string;
}
function KpiCard({ label, value, sub }: KpiCardProps) {
  return (
    <div className="cx-kpi-card">
      <div className="cx-kpi-label">{label}</div>
      <div className="cx-kpi-value">{value}</div>
      {sub && <div className="cx-kpi-sub">{sub}</div>}
    </div>
  );
}

function LatencyBar({ intent, avg_ms, max_ms }: { intent: string; avg_ms: number; max_ms: number }) {
  const pct = max_ms > 0 ? (avg_ms / max_ms) * 100 : 0;
  return (
    <div className="cx-bar-row">
      <span className="cx-bar-label">{intent}</span>
      <div className="cx-bar-track">
        <div className="cx-bar-fill" style={{ width: `${pct}%` }} />
      </div>
      <span className="cx-bar-value">{fmtMs(avg_ms)}</span>
    </div>
  );
}

function Timeseries({ rows }: { rows: CXOverview["timeseries"] }) {
  if (!rows.length) return null;

  if (rows.length === 1) {
    const r = rows[0];
    return (
      <div className="cx-chart-single">
        <div className="cx-chart-single-dot cx-chart-single-dot--conv" />
        <div className="cx-chart-single-text">
          <strong>{r.date}</strong> — {r.conversations} conversation{r.conversations !== 1 ? "s" : ""},
          avg latency {fmtMs(r.avg_latency_ms)}
        </div>
        <div className="cx-chart-single-hint">
          Chart will populate as data spans multiple days.
        </div>
      </div>
    );
  }

  const maxConv = Math.max(...rows.map((r) => r.conversations));
  const maxLat  = Math.max(...rows.map((r) => r.avg_latency_ms));
  const W = 700, H = 120, PAD = 30;
  const xScale     = (i: number) => PAD + (i / (rows.length - 1)) * (W - PAD * 2);
  const yScaleConv = (v: number) => H - PAD - ((v / (maxConv || 1)) * (H - PAD * 2));
  const yScaleLat  = (v: number) => H - PAD - ((v / (maxLat  || 1)) * (H - PAD * 2));

  const convPath = rows
    .map((r, i) => `${i === 0 ? "M" : "L"}${xScale(i).toFixed(1)},${yScaleConv(r.conversations).toFixed(1)}`)
    .join(" ");
  const latPath = rows
    .map((r, i) => `${i === 0 ? "M" : "L"}${xScale(i).toFixed(1)},${yScaleLat(r.avg_latency_ms).toFixed(1)}`)
    .join(" ");

  const labelEvery = Math.ceil(rows.length / 6);
  const labels = rows.filter((_, i) => i % labelEvery === 0 || i === rows.length - 1);

  return (
    <div className="cx-chart-wrap">
      <div className="cx-chart-legend">
        <span className="cx-legend-conv">Conversations / day</span>
        <span className="cx-legend-lat">Avg latency</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="cx-chart">
        <path d={convPath} stroke="var(--cx-conv)" strokeWidth="2" fill="none" />
        <path d={latPath}  stroke="var(--cx-lat)"  strokeWidth="2" fill="none" strokeDasharray="4 2" />
        {rows.map((r, i) => (
          <circle key={i} cx={xScale(i)} cy={yScaleConv(r.conversations)} r="2.5" fill="var(--cx-conv)" />
        ))}
        {labels.map((r, i) => {
          const idx = rows.indexOf(r);
          return (
            <text key={i} x={xScale(idx)} y={H - 4} fontSize="9" textAnchor="middle" fill="var(--text-muted)">
              {r.date.slice(5)}
            </text>
          );
        })}
      </svg>
    </div>
  );
}

function TraceRow({ t }: { t: CXOverview["recent_traces"][0] }) {
  const ts = new Date(t.started_at).toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
  return (
    <tr className={t.error ? "cx-trace-error" : ""}>
      <td className="cx-trace-ts">{ts}</td>
      <td>{fmtMs(t.latency_ms)}</td>
      <td>{t.total_tokens != null ? fmt(t.total_tokens) : "—"}</td>
      <td>{t.intent ?? "—"}</td>
      <td className="cx-trace-err-cell">{t.error ? t.error.split(":")[0] : "—"}</td>
      <td>
        {t.url ? (
          <a href={t.url} target="_blank" rel="noreferrer" className="cx-trace-link">
            Open ↗
          </a>
        ) : (
          <span className="cx-trace-no-link">n/a</span>
        )}
      </td>
    </tr>
  );
}

// --------------------------------------------------------------------------- //
// Main component
// --------------------------------------------------------------------------- //
export default function CXDashboard() {
  const [preset, setPreset]   = useState<Preset>("1m");
  const [dateRange, setDateRange] = useState(presetRange("1m"));
  const [data, setData]       = useState<CXOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    api
      .cxOverview(dateRange.start, dateRange.end)
      .then(setData)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [dateRange.start, dateRange.end]);

  function handlePreset(p: Preset) {
    setPreset(p);
    setDateRange(presetRange(p));
  }

  function handleRangeChange(field: "start" | "end", val: string) {
    setPreset("" as Preset);
    setDateRange((r) => ({ ...r, [field]: val }));
  }

  const presets: Preset[] = ["7d", "1m", "3m", "ytd"];
  const presetLabels: Record<Preset, string> = { "7d": "7D", "1m": "1M", "3m": "3M", ytd: "YTD" };

  const maxIntentMs = data
    ? Math.max(...data.latency_ms.by_intent.map((b) => b.avg_ms), 1)
    : 1;

  return (
    <div className="cx-dashboard">
      {/* ── Date bar ─────────────────────────────────────────────────── */}
      <div className="date-bar">
        <div className="date-presets">
          {presets.map((p) => (
            <button
              key={p}
              className={`preset-btn${preset === p ? " active" : ""}`}
              onClick={() => handlePreset(p)}
            >
              {presetLabels[p]}
            </button>
          ))}
        </div>
        <div className="date-divider" />
        <div className="date-inputs">
          <input
            type="date"
            value={dateRange.start}
            onChange={(e) => handleRangeChange("start", e.target.value)}
          />
          <span className="date-sep">→</span>
          <input
            type="date"
            value={dateRange.end}
            onChange={(e) => handleRangeChange("end", e.target.value)}
          />
        </div>
      </div>

      {loading && <div className="cx-loading">Loading CX data…</div>}
      {error   && <div className="cx-error">Error: {error}</div>}

      {data && !loading && (
        <>
          <StatusBanner data={data} />

          {/* ── KPI row ──────────────────────────────────────────────── */}
          <div className="cx-kpi-row">
            <KpiCard
              label="Conversations"
              value={fmt(data.overview.conversations)}
              sub={`${dateRange.start} – ${dateRange.end}`}
            />
            <KpiCard
              label="P50 Latency"
              value={fmtMs(data.latency_ms.p50)}
              sub={`P95: ${fmtMs(data.latency_ms.p95)}`}
            />
            <KpiCard
              label="P99 Latency"
              value={fmtMs(data.latency_ms.p99)}
              sub={`avg: ${fmtMs(data.latency_ms.avg)}`}
            />
            <KpiCard
              label="Error Rate"
              value={fmtPct(data.overview.error_rate)}
              sub={`${fmt(data.overview.error_count)} errors`}
            />
            <KpiCard
              label="Avg Tokens"
              value={fmt(data.tokens.avg_total)}
              sub={`in: ${fmt(data.tokens.avg_input)} / out: ${fmt(data.tokens.avg_output)}`}
            />
            <KpiCard
              label="Avg Cost / Conv"
              value={fmtCost(data.cost_usd.avg_per_conversation)}
              sub={`total: $${data.cost_usd.total.toFixed(2)}`}
            />
          </div>

          {/* ── 2-col body ───────────────────────────────────────────── */}
          <div className="cx-body">
            <div className="cx-col">
              <div className="cx-section">
                <h3 className="cx-section-title">Latency by Intent</h3>
                {data.latency_ms.by_intent.length === 0 ? (
                  <p className="cx-empty">Intent breakdown available once LangSmith is configured with intent metadata.</p>
                ) : (
                  <div className="cx-bars">
                    {data.latency_ms.by_intent.map((b) => (
                      <LatencyBar key={b.intent} {...b} max_ms={maxIntentMs} />
                    ))}
                  </div>
                )}
              </div>

              <div className="cx-section">
                <h3 className="cx-section-title">Cost Breakdown</h3>
                <table className="cx-cost-table">
                  <tbody>
                    <tr><td>Model</td><td>{data.cost_usd.model}</td></tr>
                    <tr>
                      <td>Input rate</td>
                      <td>${data.cost_usd.input_rate_per_million.toFixed(2)} / M tokens</td>
                    </tr>
                    <tr>
                      <td>Output rate</td>
                      <td>${data.cost_usd.output_rate_per_million.toFixed(2)} / M tokens</td>
                    </tr>
                    <tr><td>Total input tokens</td><td>{fmt(data.tokens.total_input)}</td></tr>
                    <tr><td>Total output tokens</td><td>{fmt(data.tokens.total_output)}</td></tr>
                    <tr className="cx-cost-total">
                      <td>Estimated total cost</td>
                      <td>${data.cost_usd.total.toFixed(2)}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>

            <div className="cx-col cx-col--wide">
              <div className="cx-section">
                <h3 className="cx-section-title">Conversations &amp; Latency Over Time</h3>
                <Timeseries rows={data.timeseries} />
              </div>

              <div className="cx-section">
                <h3 className="cx-section-title">Recent Traces</h3>
                {data.recent_traces.length === 0 ? (
                  <p className="cx-empty">No traces yet.</p>
                ) : (
                  <div className="cx-table-wrap">
                    <table className="cx-trace-table">
                      <thead>
                        <tr>
                          <th>Time</th>
                          <th>Latency</th>
                          <th>Tokens</th>
                          <th>Intent</th>
                          <th>Error</th>
                          <th>Link</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.recent_traces.map((t) => (
                          <TraceRow key={t.id} t={t} />
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
