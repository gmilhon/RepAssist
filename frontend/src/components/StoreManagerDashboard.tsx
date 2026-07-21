import { useEffect, useState, type ReactNode } from "react";
import { api } from "../api";
import type {
  StoreEngagement,
  StoreManagerBrief,
  StoreManagerOverview,
  StorePerson,
  StoreTarget,
  StoreTrafficHour,
} from "../types";

const pct = (x: number) => `${Math.round(x * 100)}%`;

// --------------------------------------------------------------------------- //
// AI daily brief — mirrors the Performance dashboard's exec summary (live
// Claude call, offline-safe) but for the store's current operating picture.
// Cached module-level so tab switches don't re-call within the TTL.
// --------------------------------------------------------------------------- //
const BRIEF_TTL_MS = 3 * 60 * 1000;
let briefCache: { brief: StoreManagerBrief; ts: number } | null = null;

const URGENCY_LABEL: Record<string, string> = { now: "Now", today: "Today", watch: "Watch" };
const AREA_ICON: Record<string, string> = { staffing: "👥", sales: "📈", operations: "📦" };

function BriefPanel() {
  const [brief, setBrief] = useState<StoreManagerBrief | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  function generate(force: boolean) {
    if (!force && briefCache && Date.now() - briefCache.ts < BRIEF_TTL_MS) {
      setBrief(briefCache.brief);
      setErr(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    setErr(null);
    api
      .storeManagerBrief()
      .then((b) => {
        briefCache = { brief: b, ts: Date.now() };
        setBrief(b);
      })
      .catch((e) => setErr(String(e)))
      .finally(() => setLoading(false));
  }

  useEffect(() => generate(false), []);

  const modelLabel = brief
    ? brief.model === "mock"
      ? "Mock brief"
      : `claude-${brief.model.split("-").slice(1).join("-")}`
    : null;

  return (
    <section className="exec-summary sm-brief">
      <div className="exec-summary-head">
        <h3>✦ Manager Brief</h3>
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

      {!loading && err && (
        <p className="muted" style={{ margin: "12px 0 0" }}>
          Could not generate brief: {err}
        </p>
      )}

      {!loading && brief && (
        <>
          <p className="exec-headline">{brief.headline}</p>

          {brief.priorities.length > 0 && (
            <div className="sm-priorities">
              {brief.priorities.map((p, i) => (
                <div key={i} className={`sm-priority sm-urg-${p.urgency}`}>
                  <span className={`sm-urg-badge sm-urg-badge-${p.urgency}`}>{URGENCY_LABEL[p.urgency] ?? p.urgency}</span>
                  <div className="sm-priority-body">
                    <div className="sm-priority-title">
                      <span className="sm-priority-area">{AREA_ICON[p.area] ?? "•"}</span>
                      {p.title}
                    </div>
                    <div className="sm-priority-detail">{p.detail}</div>
                  </div>
                </div>
              ))}
            </div>
          )}

          <div className="exec-cols">
            <div className="exec-col exec-col-info">
              <div className="exec-col-title">Right Now · Staffing</div>
              <p className="exec-col-text">{brief.staffing_focus}</p>
            </div>
            <div className="exec-col exec-col-ok">
              <div className="exec-col-title">Sales Focus</div>
              <p className="exec-col-text">{brief.sales_focus}</p>
            </div>
            <div className="exec-col exec-col-warn">
              <div className="exec-col-title">Operations</div>
              <p className="exec-col-text">{brief.operations_focus}</p>
            </div>
          </div>
          <div className="exec-meta">
            Brief as of {brief.as_of_label}
          </div>
        </>
      )}
    </section>
  );
}

// --------------------------------------------------------------------------- //
// Small shared pieces
// --------------------------------------------------------------------------- //
function SectionHead({ icon, title, sub }: { icon: string; title: string; sub?: string }) {
  return (
    <div className="sm-section-head">
      <span className="sm-section-icon">{icon}</span>
      <h3 className="sm-section-title">{title}</h3>
      {sub && <span className="sm-section-sub">{sub}</span>}
    </div>
  );
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

// --------------------------------------------------------------------------- //
// Staffing
// --------------------------------------------------------------------------- //
const STATE_META: Record<string, { label: string; cls: string }> = {
  working: { label: "On floor", cls: "working" },
  lunch: { label: "Lunch", cls: "lunch" },
  break: { label: "Break", cls: "break" },
  scheduled: { label: "Scheduled", cls: "scheduled" },
  done: { label: "Clocked out", cls: "done" },
};
const SEGMENT_LABEL: Record<string, string> = { opener: "Opener", mid: "Mid", closer: "Closer" };

function PersonRow({ p }: { p: StorePerson }) {
  const withCust = p.with_customer && p.state === "working";
  const meta = withCust ? { label: "With customer", cls: "assisting" } : (STATE_META[p.state] ?? STATE_META.working);
  const statusText =
    p.state === "scheduled" ? `In at ${p.until}` :
    p.state === "lunch" || p.state === "break" ? `Back ${p.until}` :
    p.state === "done" ? `Ended ${p.until}` :
    `${p.worked_hours}h in`;
  return (
    <div className={`sm-person${p.break_due ? " sm-person--break-due" : ""}`}>
      <div className={`sm-avatar sm-avatar--${withCust ? "assisting" : meta.cls}`}>{p.initials}</div>
      <div className="sm-person-main">
        <div className="sm-person-top">
          <span className="sm-person-name">{p.name}</span>
          <span className={`sm-seg sm-seg--${p.segment}`}>{SEGMENT_LABEL[p.segment]}</span>
        </div>
        <div className="sm-person-sub">{p.role} · {p.specialty}</div>
      </div>
      <div className="sm-person-right">
        <span className={`sm-status sm-status--${meta.cls}`}>{meta.label}</span>
        <span className="sm-person-shift">{p.shift}</span>
      </div>
      <div className="sm-person-when">
        {p.break_due
          ? <span className="sm-break-flag">Break due</span>
          : <span className="sm-when-text">{statusText}</span>}
      </div>
    </div>
  );
}

// --- Live floor: who's with a customer, opportunity vs. cart, risk to close ---
const RISK_META: Record<string, { label: string; cls: string }> = {
  high: { label: "Needs help", cls: "high" },
  watch: { label: "Watch", cls: "watch" },
  none: { label: "On track", cls: "none" },
};
const STAGE_ICON: Record<string, string> = {
  Browsing: "👀", Quoting: "🧮", "Building cart": "🛒", Checkout: "💳", Signature: "✍️",
};

function EngagementCard({ e }: { e: StoreEngagement }) {
  const risk = RISK_META[e.risk_level] ?? RISK_META.none;
  return (
    <div className={`sm-engage sm-engage--${e.risk_level}`}>
      <div className="sm-engage-head">
        <div className="sm-avatar sm-avatar--assisting sm-avatar--sm">{e.initials}</div>
        <div className="sm-engage-id">
          <div className="sm-engage-rep">{e.rep} <span className="sm-engage-cust">· {e.customer}</span></div>
          <div className="sm-engage-meta">{STAGE_ICON[e.stage] ?? "•"} {e.reason} · {e.stage} · {e.since_min}m in</div>
        </div>
        <span className={`sm-risk-badge sm-risk-badge--${risk.cls}`}>{risk.label}</span>
      </div>

      <div className="sm-oppbar">
        <div className="sm-oppbar-labels">
          <span className="sm-oppbar-cart">Cart ${e.cart_value.toLocaleString()}</span>
          <span className="sm-oppbar-opp">Opportunity ${e.opportunity_value.toLocaleString()}</span>
        </div>
        <div className="sm-oppbar-track">
          <div className={`sm-oppbar-fill sm-oppbar-fill--${e.risk_level}`} style={{ width: `${e.attach_ratio * 100}%` }} />
        </div>
        <div className="sm-oppbar-foot">
          <span>{pct(e.attach_ratio)} attached</span>
          {e.gap_value > 0 && <span className="sm-oppbar-gap">${e.gap_value.toLocaleString()} on the table</span>}
        </div>
      </div>

      {e.gap.length > 0 && (
        <div className="sm-engage-gaps">
          {e.gap.map((g, i) => <span key={i} className="sm-gap-chip">+ {g}</span>)}
        </div>
      )}
      {e.risk_level !== "none" && <div className="sm-engage-risk">{e.risk_reason}</div>}
    </div>
  );
}

function AssistingNow({ engagements }: { engagements: StoreEngagement[] }) {
  if (!engagements.length) return null;
  const atRisk = engagements.filter((e) => e.risk_level === "high").length;
  return (
    <section className="panel sm-live-panel">
      <div className="panel-head">
        <h3><span className="sm-live-dot" /> Assisting now — live opportunities</h3>
        <span className="panel-sub">
          {engagements.length} with customers{atRisk > 0 && <> · <b className="sm-live-risk">{atRisk} need{atRisk === 1 ? "s" : ""} help</b></>}
        </span>
      </div>
      <div className="sm-live-grid">
        {engagements.map((e) => <EngagementCard key={e.rep} e={e} />)}
      </div>
    </section>
  );
}

function Staffing({ o }: { o: StoreManagerOverview }) {
  const s = o.staffing;
  const c = s.counts;
  // Openers first, then mids, then closers; within a segment show who's on the
  // floor before who's scheduled/done.
  const order: Record<string, number> = { opener: 0, mid: 1, closer: 2 };
  const stateOrder: Record<string, number> = { working: 0, lunch: 1, break: 1, scheduled: 2, done: 3 };
  const people = [...s.people].sort(
    (a, b) => order[a.segment] - order[b.segment] || stateOrder[a.state] - stateOrder[b.state]
  );

  return (
    <>
      <SectionHead icon="👥" title="Staffing & Live Floor" sub={`${c.scheduled_today} scheduled today`} />
      <div className="kpi-grid sm-kpi-grid">
        <Kpi label="On the floor" value={c.on_floor} sub="right now" />
        <Kpi label="With customers" value={c.assisting} sub={c.at_risk > 0 ? `${c.at_risk} need help` : "all on track"} tone={c.at_risk > 0 ? "warn" : "good"} />
        <Kpi label="On break / lunch" value={c.on_break} tone={c.on_break > 0 ? "warn" : undefined} />
        <Kpi label="Needs a break" value={c.needs_break} sub="5h+ no meal" tone={c.needs_break > 0 ? "warn" : "good"} />
        <Kpi label="Coming in later" value={c.coming_later} sub={s.next_in ? `next ${s.next_in.until}` : undefined} />
        <Kpi label="Closing tonight" value={c.closers} />
      </div>

      <AssistingNow engagements={s.assisting} />

      <section className="panel">
        <div className="panel-head">
          <h3>Today's team</h3>
          <span className="panel-sub">openers → closers · live status</span>
        </div>
        <div className="sm-roster">
          {people.map((p) => <PersonRow key={p.name} p={p} />)}
        </div>
      </section>
    </>
  );
}

// --------------------------------------------------------------------------- //
// Traffic forecast vs. coverage
// --------------------------------------------------------------------------- //
function TrafficChart({ hours, max }: { hours: StoreTrafficHour[]; max: number }) {
  return (
    <div className="sm-traffic-chart">
      {hours.map((h) => {
        const booked = h.appointments + h.ispu;
        const walkins = Math.max(0, h.forecast - booked);
        return (
          <div
            key={h.hour}
            className={`sm-tcol${h.is_current ? " current" : ""}${h.gap ? " gap" : ""}${h.is_past ? " past" : ""}`}
            title={`${h.label}: ~${h.forecast} customers (${h.appointments} appts, ${h.ispu} pickups) · ${h.staffed} on floor${h.gap ? " · understaffed" : ""}`}
          >
            <div className="sm-tbar-wrap">
              <div className="sm-tbar-num">{h.forecast}</div>
              <div className="sm-tbar" style={{ height: `${(h.forecast / max) * 100}%` }}>
                <div className="sm-tbar-walkins" style={{ height: `${(walkins / h.forecast) * 100}%` }} />
                <div className="sm-tbar-booked" style={{ height: `${(booked / h.forecast) * 100}%` }} />
              </div>
            </div>
            <div className={`sm-tstaff${h.gap ? " warn" : ""}`}>
              <span className="sm-tstaff-ico">{h.gap ? "⚠" : "👤"}</span>{h.staffed}
            </div>
            <div className={`sm-thour${h.is_current ? " current" : ""}`}>{h.label}</div>
          </div>
        );
      })}
    </div>
  );
}

function Traffic({ o }: { o: StoreManagerOverview }) {
  const t = o.traffic;
  return (
    <>
      <SectionHead icon="📊" title="Traffic Forecast" sub={`store hours ${o.hours_label}`} />
      <div className="kpi-grid sm-kpi-grid">
        <Kpi label="Peak hour" value={t.peak_hour_label} sub={`~${t.peak_forecast} customers`} />
        <Kpi label="Appointments" value={t.appointments_today} sub="booked today" />
        <Kpi label="In-store pickups" value={t.ispu_today} sub="scheduled today" />
        <Kpi label="Coverage gaps" value={t.gap_hours} sub={t.gap_hours ? "hours understaffed" : "well staffed"} tone={t.gap_hours > 0 ? "warn" : "good"} />
      </div>
      <section className="panel">
        <div className="panel-head">
          <h3>Expected volume by hour vs. floor coverage</h3>
          <div className="sm-legend">
            <span><i className="sm-sw sm-sw-walkins" /> Walk-ins</span>
            <span><i className="sm-sw sm-sw-booked" /> Appts + pickups</span>
            <span><i className="sm-sw sm-sw-gap" /> Understaffed</span>
          </div>
        </div>
        <TrafficChart hours={t.hours} max={t.max_forecast} />
        {t.gap_hours > 0 && (
          <p className="sm-traffic-note">
            ⚠ Forecast outruns the floor at{" "}
            <b>{t.hours.filter((h) => h.gap).map((h) => h.label).join(", ")}</b> — flex a break or call in
            coverage before the {t.peak_hour_label} peak.
          </p>
        )}
      </section>
    </>
  );
}

// --------------------------------------------------------------------------- //
// Sales performance
// --------------------------------------------------------------------------- //
const PACE_META: Record<string, { label: string; cls: string }> = {
  ahead: { label: "Ahead", cls: "ahead" },
  on: { label: "On pace", cls: "on" },
  behind: { label: "Behind", cls: "behind" },
};

function TargetBar({ t }: { t: StoreTarget }) {
  const actualLabel = t.unit === "pct" ? pct(t.actual) : t.actual.toLocaleString();
  const targetLabel = t.unit === "pct" ? pct(t.target) : t.target.toLocaleString();
  const pace = PACE_META[t.pace] ?? PACE_META.on;
  const fill = Math.min(100, t.attainment * 100);
  return (
    <div className="sm-target">
      <div className="sm-target-top">
        <span className="sm-target-label">{t.label}</span>
        <span className={`sm-pace sm-pace--${pace.cls}`}>{pace.label}</span>
      </div>
      <div className="sm-target-nums">
        <b>{actualLabel}</b> <span className="muted">/ {targetLabel}</span>
        <span className="sm-target-attain">{pct(t.attainment)}</span>
      </div>
      <div className="sm-target-track">
        <div className={`sm-target-fill sm-target-fill--${pace.cls}`} style={{ width: `${fill}%` }} />
      </div>
      {t.pace !== "ahead" && <div className="sm-target-hint">{t.hint}</div>}
    </div>
  );
}

function Sales({ o }: { o: StoreManagerOverview }) {
  const s = o.sales;
  return (
    <>
      <SectionHead icon="📈" title="Sales Performance" sub={s.period} />
      <div className="sm-ranks">
        {s.rankings.map((r) => (
          <div key={r.scope} className="sm-rank">
            <div className="sm-rank-scope">{r.scope}</div>
            <div className="sm-rank-val">
              <span className="sm-rank-hash">#</span>{r.rank}
              <span className="sm-rank-of">of {r.of}</span>
            </div>
            <div className={`sm-rank-trend sm-rank-trend--${r.trend}`}>
              {r.trend === "up" ? "▲" : "▼"} {r.delta} {r.trend === "up" ? "spots" : "spot"} vs last wk
            </div>
            <div className="sm-rank-name">{r.name}</div>
          </div>
        ))}
      </div>

      <div className="dash-row sm-sales-row">
        <section className="panel">
          <div className="panel-head">
            <h3>Targets &amp; areas of focus</h3>
            <span className="panel-sub">{s.period} attainment</span>
          </div>
          <div className="sm-targets">
            {s.targets.map((t) => <TargetBar key={t.key} t={t} />)}
          </div>
        </section>

        <section className="panel">
          <div className="panel-head">
            <h3>High-priority upgrades</h3>
            <span className="panel-sub">at-risk · upgrade-eligible</span>
          </div>
          <div className="sm-atrisk">
            {s.at_risk_upgrades.map((a) => (
              <div key={a.account} className="sm-atrisk-row">
                <span className={`sm-prio-dot sm-prio-dot--${a.priority}`} />
                <div className="sm-atrisk-main">
                  <div className="sm-atrisk-top">
                    <span className="sm-atrisk-name">{a.customer}</span>
                    <span className="sm-atrisk-acct">{a.account}</span>
                  </div>
                  <div className="sm-atrisk-device">{a.device}</div>
                  <div className="sm-atrisk-reason">{a.reason}</div>
                </div>
                <span className="sm-atrisk-value">{a.value}</span>
              </div>
            ))}
          </div>
        </section>
      </div>
    </>
  );
}

// --------------------------------------------------------------------------- //
// Operations
// --------------------------------------------------------------------------- //
const SHIP_STATUS: Record<string, string> = {
  out_for_delivery: "Out for delivery",
  in_transit: "In transit",
  label_created: "Label created",
};

function Operations({ o }: { o: StoreManagerOverview }) {
  const ops = o.operations;
  const tr = ops.training;
  return (
    <>
      <SectionHead icon="📦" title="Operations & Inventory" sub="inventory · pickups · people" />
      <div className="sm-ops-grid">
        {/* Inbound shipments */}
        <section className="panel sm-ops-card">
          <div className="panel-head"><h3>Incoming shipments</h3><span className="panel-sub">{ops.counts.inbound_units} units</span></div>
          <div className="sm-list">
            {ops.shipments.map((sh) => (
              <div key={sh.id} className="sm-li">
                <div className="sm-li-main">
                  <div className="sm-li-title">{sh.summary}</div>
                  <div className="sm-li-sub">{sh.carrier} · {sh.id}</div>
                </div>
                <div className="sm-li-right">
                  <span className={`sm-tag${sh.status === "out_for_delivery" ? " sm-tag--go" : ""}`}>{SHIP_STATUS[sh.status] ?? sh.status}</span>
                  <span className="sm-li-when">{sh.eta}</span>
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* Unpicked pickups */}
        <section className="panel sm-ops-card">
          <div className="panel-head">
            <h3>Unpicked pickups</h3>
            <span className="panel-sub">{ops.counts.ispu_call_first} need a call</span>
          </div>
          <div className="sm-list">
            {ops.unpicked_ispu.map((u) => (
              <div key={u.order} className={`sm-li${u.call_first ? " sm-li--alert" : ""}`}>
                <div className="sm-li-main">
                  <div className="sm-li-title">{u.customer} · {u.item}</div>
                  <div className="sm-li-sub">{u.order} · waiting {u.days_waiting}d</div>
                </div>
                <div className="sm-li-right">
                  {u.call_first
                    ? <span className="sm-tag sm-tag--alert">Call {u.phone}</span>
                    : <span className="sm-tag">Holding</span>}
                  <span className="sm-li-when">Cancels {u.auto_cancel.toLowerCase()}</span>
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* Exchanges to return */}
        <section className="panel sm-ops-card">
          <div className="panel-head"><h3>Exchanges to return</h3><span className="panel-sub">{ops.counts.exchanges_due} due ≤2d</span></div>
          <div className="sm-list">
            {ops.exchanges_to_return.map((e) => (
              <div key={e.rma} className={`sm-li${e.days_left <= 2 ? " sm-li--alert" : ""}`}>
                <div className="sm-li-main">
                  <div className="sm-li-title">{e.device} <span className="muted">{e.imei_tail}</span></div>
                  <div className="sm-li-sub">{e.rma} · {e.reason}</div>
                </div>
                <div className="sm-li-right">
                  <span className={`sm-tag${e.days_left <= 2 ? " sm-tag--alert" : ""}`}>{e.days_left}d left</span>
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* Planogram + launches */}
        <section className="panel sm-ops-card">
          <div className="panel-head"><h3>Merchandising & launches</h3><span className="panel-sub">planogram · devices</span></div>
          <div className="sm-list">
            {ops.planogram_changes.map((p) => (
              <div key={p.name} className="sm-li">
                <div className="sm-li-main">
                  <div className="sm-li-title">🗺 {p.name}</div>
                  <div className="sm-li-sub">{p.note}</div>
                </div>
                <span className="sm-li-when">{p.date}</span>
              </div>
            ))}
            {ops.device_launches.map((d) => (
              <div key={d.device} className="sm-li">
                <div className="sm-li-main">
                  <div className="sm-li-title">🚀 {d.device}</div>
                  <div className="sm-li-sub">{d.note}</div>
                </div>
                <div className="sm-li-right">
                  <span className="sm-tag">Preorder {d.preorder_date}</span>
                  <span className="sm-li-when">Launch {d.launch_date}</span>
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* Training compliance */}
        <section className="panel sm-ops-card">
          <div className="panel-head"><h3>Training compliance</h3><span className="panel-sub">{tr.compliant}/{tr.total} current</span></div>
          <div className="sm-compliance">
            <div className="sm-compliance-bar">
              <div className="sm-compliance-fill" style={{ width: `${tr.pct * 100}%` }} />
            </div>
            <div className="sm-compliance-pct">{pct(tr.pct)}</div>
          </div>
          <div className="sm-list">
            {tr.overdue.map((t) => (
              <div key={t.rep + t.course} className="sm-li sm-li--alert">
                <div className="sm-li-main">
                  <div className="sm-li-title">{t.rep}</div>
                  <div className="sm-li-sub">{t.course}</div>
                </div>
                <span className="sm-tag sm-tag--alert">{t.due}</span>
              </div>
            ))}
            {tr.overdue.length === 0 && <div className="muted" style={{ fontSize: 12 }}>Everyone is current. 🎉</div>}
          </div>
        </section>

        {/* Open positions */}
        <section className="panel sm-ops-card">
          <div className="panel-head"><h3>Open positions</h3><span className="panel-sub">{ops.counts.open_positions} open</span></div>
          <div className="sm-list">
            {ops.open_positions.map((p) => (
              <div key={p.title} className="sm-li">
                <div className="sm-li-main">
                  <div className="sm-li-title">{p.title}</div>
                  <div className="sm-li-sub">{p.candidates} candidate{p.candidates === 1 ? "" : "s"} · open {p.days_open}d</div>
                </div>
                <span className={`sm-tag${p.stage === "Interviewing" ? " sm-tag--go" : ""}`}>{p.stage}</span>
              </div>
            ))}
          </div>
        </section>
      </div>
    </>
  );
}

// --------------------------------------------------------------------------- //
// Main
// --------------------------------------------------------------------------- //
export default function StoreManagerDashboard() {
  const [o, setO] = useState<StoreManagerOverview | null>(null);
  const [err, setErr] = useState<string | null>(null);

  function load() {
    api.storeManagerOverview().then(setO).catch((e) => setErr(String(e)));
  }
  useEffect(load, []);

  if (err) return <div className="dash"><p className="muted pad">Couldn't load store data: {err}</p></div>;
  if (!o) return <div className="dash"><p className="muted pad">Loading store…</p></div>;

  return (
    <div className="dash sm-dash">
      <div className="dash-head">
        <div>
          <h2>{o.store.name} <span className="sm-store-id">#{o.store.id}</span></h2>
          <p className="muted">
            {o.day_label} · as of {o.as_of_label} · {o.store.territory} · {o.store.district}
          </p>
        </div>
        <button className="btn ghost" onClick={load}>↻ Refresh</button>
      </div>

      <BriefPanel />
      <Staffing o={o} />
      <Traffic o={o} />
      <Sales o={o} />
      <Operations o={o} />
    </div>
  );
}
