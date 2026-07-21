import { useEffect, useState, type ReactNode } from "react";
import { api } from "../api";
import type {
  DistrictRollup,
  Pace,
  RollupBrief,
  RollupDistrict,
  RollupStore,
  TerritoryRollup,
} from "../types";

type Level = "district" | "territory";

const pct = (x: number) => `${Math.round(x * 100)}%`;
const idxPace = (p: Pace) => (p === "ahead" ? "ahead" : p === "on" ? "on" : "behind");

// Attainment cell color: red well under plan, amber under, green at/over.
function metricCls(v: number) {
  return v >= 1 ? "good" : v >= 0.75 ? "" : v >= 0.6 ? "warn" : "bad";
}

function Kpi({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: string; tone?: "good" | "warn" }) {
  return (
    <div className={`kpi ${tone ?? ""}`}>
      <div className="kpi-val">{value}</div>
      <div className="kpi-label">{label}</div>
      {sub && <div className="kpi-sub">{sub}</div>}
    </div>
  );
}

function TrendTag({ trend, wow }: { trend: string; wow?: number }) {
  const cls = trend === "up" ? "up" : trend === "down" ? "down" : "flat";
  const arrow = trend === "up" ? "▲" : trend === "down" ? "▼" : "▬";
  return (
    <span className={`sm-rank-trend sm-rank-trend--${cls}`}>
      {arrow}{wow !== undefined ? ` ${wow > 0 ? "+" : ""}${wow.toFixed(1)}` : ""}
    </span>
  );
}

// --------------------------------------------------------------------------- //
// AI outlier-management brief (cached per level; live Claude + offline mock)
// --------------------------------------------------------------------------- //
const BRIEF_TTL_MS = 3 * 60 * 1000;
const briefCache: Record<Level, { brief: RollupBrief; ts: number } | null> = { district: null, territory: null };

const URGENCY_LABEL: Record<string, string> = { now: "Now", today: "Today", week: "This week", watch: "Watch" };

function RollupBriefPanel({ level }: { level: Level }) {
  const [brief, setBrief] = useState<RollupBrief | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  function generate(force: boolean) {
    const cached = briefCache[level];
    if (!force && cached && Date.now() - cached.ts < BRIEF_TTL_MS) {
      setBrief(cached.brief); setErr(null); setLoading(false); return;
    }
    setLoading(true); setErr(null);
    const call = level === "district" ? api.districtBrief() : api.territoryBrief();
    call
      .then((b) => { briefCache[level] = { brief: b, ts: Date.now() }; setBrief(b); })
      .catch((e) => setErr(String(e)))
      .finally(() => setLoading(false));
  }

  useEffect(() => generate(false), [level]); // eslint-disable-line react-hooks/exhaustive-deps

  const modelLabel = brief ? (brief.model === "mock" ? "Mock brief" : `claude-${brief.model.split("-").slice(1).join("-")}`) : null;
  const title = level === "district" ? "District Brief" : "Territory Brief";

  return (
    <section className="exec-summary sm-brief">
      <div className="exec-summary-head">
        <h3>✦ {title} · Outlier Management</h3>
        <div className="exec-summary-right">
          {modelLabel && <span className="ai-badge">✦ {modelLabel}</span>}
          <button className="btn ghost small" onClick={() => generate(true)} disabled={loading}>
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
      {!loading && err && <p className="muted" style={{ margin: "12px 0 0" }}>Could not generate brief: {err}</p>}

      {!loading && brief && (
        <>
          <p className="exec-headline">{brief.headline}</p>

          {brief.outliers.length > 0 && (
            <div className="sm-outliers">
              {brief.outliers.map((o, i) => (
                <div key={i} className={`sm-outlier sm-outlier--${o.direction}`}>
                  <div className="sm-outlier-top">
                    <span className="sm-outlier-arrow">{o.direction === "up" ? "▲" : "▼"}</span>
                    <span className="sm-outlier-name">{o.name}</span>
                  </div>
                  <div className="sm-outlier-detail">{o.detail}</div>
                </div>
              ))}
            </div>
          )}

          {brief.priorities.length > 0 && (
            <div className="sm-priorities">
              {brief.priorities.map((p, i) => (
                <div key={i} className={`sm-priority sm-urg-${p.urgency}`}>
                  <span className={`sm-urg-badge sm-urg-badge-${p.urgency}`}>{URGENCY_LABEL[p.urgency] ?? p.urgency}</span>
                  <div className="sm-priority-body">
                    <div className="sm-priority-title"><span className="sm-priority-scope">{p.scope}</span>{p.title}</div>
                    <div className="sm-priority-detail">{p.detail}</div>
                  </div>
                </div>
              ))}
            </div>
          )}

          <div className="exec-cols">
            <div className="exec-col exec-col-ok" style={{ gridColumn: "1 / -1" }}>
              <div className="exec-col-title">What's working — sustain &amp; replicate</div>
              <p className="exec-col-text">{brief.momentum}</p>
            </div>
          </div>
        </>
      )}
    </section>
  );
}

// --------------------------------------------------------------------------- //
// District view (daily) — store leaderboard
// --------------------------------------------------------------------------- //
function DistrictView({ d }: { d: DistrictRollup }) {
  const k = d.kpis;
  return (
    <>
      <div className="kpi-grid sm-kpi-grid">
        <Kpi label="District index" value={k.district_index} sub={k.pace} tone={k.pace === "behind" ? "warn" : "good"} />
        <Kpi label="Stores behind" value={`${k.stores_behind}/${k.stores}`} tone={k.stores_behind > k.stores / 2 ? "warn" : undefined} />
        <Kpi label="Coverage gaps" value={k.coverage_gaps} sub="stores today" tone={k.coverage_gaps > 0 ? "warn" : "good"} />
        <Kpi label="Deals at risk" value={k.at_risk_deals} sub="live, district-wide" tone={k.at_risk_deals > 0 ? "warn" : "good"} />
        <Kpi label="Ops alerts" value={k.ops_alerts} sub="open items" />
        <Kpi label="Traffic today" value={k.traffic_today.toLocaleString()} sub="forecast" />
      </div>

      <section className="panel">
        <div className="panel-head">
          <h3>Store leaderboard</h3>
          <span className="panel-sub">ranked by scorecard index · 100 = on plan</span>
        </div>
        <div className="sm-table-wrap">
          <table className="sm-table">
            <thead>
              <tr>
                <th>#</th><th>Store</th><th className="num">Index</th>
                <th className="num">PGA</th><th className="num">Upg</th><th className="num">M+H</th>
                <th>Coverage</th><th className="num">Ops</th><th className="num">At risk</th><th>Focus</th>
              </tr>
            </thead>
            <tbody>
              {d.stores.map((s) => <StoreRow key={s.id} s={s} />)}
            </tbody>
          </table>
        </div>
      </section>

      <OutlierCallouts
        lagging={d.outliers.lagging.map((s) => ({ name: s.name, sub: s.manager, index: s.index, note: s.flags.slice(0, 2).join(" · ") }))}
        leading={d.outliers.leading.map((s) => ({ name: s.name, sub: s.manager, index: s.index, note: `${pct(s.pga)} PGA · model store` }))}
        laggingLabel="Needs a touch-base today"
        leadingLabel="Model stores to learn from"
      />
    </>
  );
}

function StoreRow({ s }: { s: RollupStore }) {
  return (
    <tr className={s.is_self ? "sm-tr-self" : ""}>
      <td className="sm-td-rank">{s.rank}</td>
      <td>
        <div className="sm-td-name">{s.name}{s.is_self && <span className="sm-self-tag">Your store</span>}</div>
        <div className="sm-td-sub">{s.manager}</div>
      </td>
      <td className="num"><span className={`sm-index sm-index--${idxPace(s.pace)}`}>{s.index}</span></td>
      <td className={`num sm-metric sm-metric--${metricCls(s.pga)}`}>{pct(s.pga)}</td>
      <td className={`num sm-metric sm-metric--${metricCls(s.upgrades)}`}>{pct(s.upgrades)}</td>
      <td className={`num sm-metric sm-metric--${metricCls(s.mobile_home)}`}>{pct(s.mobile_home)}</td>
      <td><span className={`sm-cov sm-cov--${s.coverage}`}>{s.coverage === "ok" ? "OK" : s.coverage === "thin" ? "Thin" : "Gap"}</span></td>
      <td className="num">{s.ops_alerts}</td>
      <td className="num">{s.at_risk_deals > 0 ? <span className="sm-atrisk-num">{s.at_risk_deals}</span> : "—"}</td>
      <td>
        <div className="sm-flags">
          {s.flags.length === 0 ? <span className="sm-flag sm-flag--ok">On plan</span>
            : s.flags.slice(0, 2).map((f, i) => <span key={i} className="sm-flag">{f}</span>)}
          {s.flags.length > 2 && <span className="sm-flag sm-flag--more">+{s.flags.length - 2}</span>}
        </div>
      </td>
    </tr>
  );
}

// --------------------------------------------------------------------------- //
// Territory view (weekly) — district rollup
// --------------------------------------------------------------------------- //
function TerritoryView({ t }: { t: TerritoryRollup }) {
  const k = t.kpis;
  return (
    <>
      <div className="kpi-grid sm-kpi-grid">
        <Kpi label="Territory index" value={k.territory_index} sub={k.pace} tone={k.pace === "behind" ? "warn" : "good"} />
        <Kpi label="Week over week" value={`${k.wow > 0 ? "+" : ""}${k.wow.toFixed(1)}`} sub="index pts" tone={k.wow < 0 ? "warn" : "good"} />
        <Kpi label="Districts behind" value={`${k.districts_behind}/${k.districts}`} tone={k.districts_behind > 0 ? "warn" : "good"} />
        <Kpi label="Red-flag stores" value={k.red_stores} sub={`of ${k.stores}`} tone={k.red_stores > 0 ? "warn" : "good"} />
        <Kpi label="Training" value={pct(k.training_pct)} sub="territory-wide" tone={k.training_pct < 0.85 ? "warn" : "good"} />
        <Kpi label="Open roles" value={k.open_positions} sub="hiring pipeline" />
      </div>

      <section className="panel">
        <div className="panel-head">
          <h3>District rollup</h3>
          <span className="panel-sub">ranked by index · week-over-week trend</span>
        </div>
        <div className="sm-table-wrap">
          <table className="sm-table">
            <thead>
              <tr>
                <th>#</th><th>District</th><th className="num">Stores</th><th className="num">Index</th>
                <th className="num">WoW</th><th className="num">Red</th><th>Top / Bottom store</th><th className="num">Training</th>
              </tr>
            </thead>
            <tbody>
              {t.districts.map((dd) => <DistrictRow key={dd.id} d={dd} />)}
            </tbody>
          </table>
        </div>
      </section>

      <OutlierCallouts
        lagging={t.outliers.declining.map((dd) => ({ name: dd.name, sub: `DM ${dd.dm}`, index: dd.index, note: `${dd.wow.toFixed(1)} pts WoW · ${dd.red_stores} red stores` }))}
        leading={t.outliers.rising.map((dd) => ({ name: dd.name, sub: `DM ${dd.dm}`, index: dd.index, note: `+${dd.wow.toFixed(1)} pts WoW · replicate` }))}
        laggingLabel="Sliding — Director's focus this week"
        leadingLabel="Surging — study & replicate"
      />
    </>
  );
}

function DistrictRow({ d }: { d: RollupDistrict }) {
  return (
    <tr className={d.is_home ? "sm-tr-self" : ""}>
      <td className="sm-td-rank">{d.rank}</td>
      <td>
        <div className="sm-td-name">{d.name}{d.is_home && <span className="sm-self-tag">Your district</span>}</div>
        <div className="sm-td-sub">DM {d.dm}</div>
      </td>
      <td className="num">{d.stores}</td>
      <td className="num"><span className={`sm-index sm-index--${idxPace(d.pace)}`}>{d.index}</span></td>
      <td className="num"><TrendTag trend={d.trend} wow={d.wow} /></td>
      <td className="num">{d.red_stores > 0 ? <span className="sm-atrisk-num">{d.red_stores}</span> : "—"}</td>
      <td>
        <div className="sm-topbottom">
          <span className="sm-tb-top">▲ {d.top}</span>
          <span className="sm-tb-bottom">▼ {d.bottom}</span>
        </div>
      </td>
      <td className={`num sm-metric sm-metric--${metricCls(d.training_pct)}`}>{pct(d.training_pct)}</td>
    </tr>
  );
}

// --------------------------------------------------------------------------- //
// Shared outlier callouts (two columns: needs focus / to replicate)
// --------------------------------------------------------------------------- //
type Callout = { name: string; sub: string; index: number; note: string };
function OutlierCallouts({ lagging, leading, laggingLabel, leadingLabel }: {
  lagging: Callout[]; leading: Callout[]; laggingLabel: string; leadingLabel: string;
}) {
  return (
    <div className="dash-row sm-outlier-row">
      <section className="panel">
        <div className="panel-head"><h3>⚠ {laggingLabel}</h3><span className="panel-sub">{lagging.length}</span></div>
        <div className="sm-callouts">
          {lagging.length === 0 && <div className="muted" style={{ fontSize: 12 }}>Nothing flagged. 🎉</div>}
          {lagging.map((c) => (
            <div key={c.name} className="sm-callout sm-callout--down">
              <div className="sm-callout-idx sm-callout-idx--down">{c.index}</div>
              <div className="sm-callout-main">
                <div className="sm-callout-name">{c.name}</div>
                <div className="sm-callout-sub">{c.sub}</div>
                <div className="sm-callout-note">{c.note}</div>
              </div>
            </div>
          ))}
        </div>
      </section>
      <section className="panel">
        <div className="panel-head"><h3>★ {leadingLabel}</h3><span className="panel-sub">{leading.length}</span></div>
        <div className="sm-callouts">
          {leading.length === 0 && <div className="muted" style={{ fontSize: 12 }}>None this period.</div>}
          {leading.map((c) => (
            <div key={c.name} className="sm-callout sm-callout--up">
              <div className="sm-callout-idx sm-callout-idx--up">{c.index}</div>
              <div className="sm-callout-main">
                <div className="sm-callout-name">{c.name}</div>
                <div className="sm-callout-sub">{c.sub}</div>
                <div className="sm-callout-note">{c.note}</div>
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Main
// --------------------------------------------------------------------------- //
export default function RollupDashboard({ level }: { level: Level }) {
  const [district, setDistrict] = useState<DistrictRollup | null>(null);
  const [territory, setTerritory] = useState<TerritoryRollup | null>(null);
  const [err, setErr] = useState<string | null>(null);

  function load() {
    setErr(null);
    if (level === "district") api.districtRollup().then(setDistrict).catch((e) => setErr(String(e)));
    else api.territoryRollup().then(setTerritory).catch((e) => setErr(String(e)));
  }
  useEffect(load, [level]); // eslint-disable-line react-hooks/exhaustive-deps

  const data = level === "district" ? district : territory;
  if (err) return <div className="dash"><p className="muted pad">Couldn't load rollup: {err}</p></div>;
  if (!data) return <div className="dash"><p className="muted pad">Loading {level}…</p></div>;

  const scope = data.scope;
  const cadence = level === "district" ? "Daily review" : "Weekly review";
  const icon = level === "district" ? "🗺️" : "🌎";

  return (
    <div className="dash sm-dash">
      <div className="dash-head">
        <div>
          <h2>{icon} {scope.name} <span className="sm-store-id">{data.period}</span></h2>
          <p className="muted">
            {scope.leader_role} · {scope.leader} · {cadence}
            {level === "district" ? ` · ${(data as DistrictRollup).scope.territory}` : ` · ${(data as TerritoryRollup).scope.market}`}
          </p>
        </div>
        <button className="btn ghost" onClick={load}>↻ Refresh</button>
      </div>

      <RollupBriefPanel level={level} />

      {level === "district"
        ? <DistrictView d={data as DistrictRollup} />
        : <TerritoryView t={data as TerritoryRollup} />}
    </div>
  );
}
