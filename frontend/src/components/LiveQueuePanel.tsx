import { useEffect } from "react";
import type { LiveQueueEntry, LiveQueueSnapshot } from "../types";

interface Props {
  snapshot: LiveQueueSnapshot | null;
  onClose: () => void;
  onRefresh?: () => void;
  refreshing?: boolean;
}

function repName(id: string | null): string {
  if (!id) return "";
  const base = id.replace(/^rep\./, "").replace(/[._]/g, " ");
  return base.charAt(0).toUpperCase() + base.slice(1);
}

function personName(e: LiveQueueEntry): string {
  return e.customer_name ?? e.customer_phone ?? "Customer";
}

type RowKind = "waiting" | "assisting" | "ispu_to_pick" | "ispu_ready" | "appointment";

function QueueRow({ entry, kind }: { entry: LiveQueueEntry; kind: RowKind }) {
  const sub =
    entry.customer_name && entry.customer_phone ? entry.customer_phone
    : entry.order_id ? entry.order_id
    : "";
  return (
    <div className="lq-row">
      <div className={`lq-row-tick lq-row-tick--${kind}`} />
      <div className="lq-row-main">
        <span className="lq-row-name">{personName(entry)}</span>
        <span className="lq-row-reason">
          {entry.reason_label}
          {sub && <span className="lq-row-reason-sub"> · {sub}</span>}
        </span>
      </div>
      <div className="lq-row-meta">
        {kind === "appointment" ? (
          <>
            <span className="lq-row-time">{entry.scheduled_label}</span>
            <span className="lq-row-hint">{entry.eta_label}</span>
          </>
        ) : kind === "assisting" ? (
          <>
            <span className="lq-row-time">{entry.wait_label}</span>
            <span className="lq-row-hint">{repName(entry.assigned_rep_id) || "in progress"}</span>
          </>
        ) : (
          <>
            <span className="lq-row-time">{entry.wait_label}</span>
            <span className="lq-row-hint">
              {kind === "ispu_ready" ? "staged" : kind === "ispu_to_pick" ? "to pick" : "waiting"}
            </span>
          </>
        )}
      </div>
    </div>
  );
}

function Section({
  title,
  count,
  emptyLabel,
  children,
}: {
  title: string;
  count: number;
  emptyLabel: string;
  children: React.ReactNode;
}) {
  return (
    <div className="hpanel-section">
      <div className="hpanel-section-head hpanel-section-head--row">
        <span>{title}</span>
        <span className="lq-count-chip">{count}</span>
      </div>
      {count === 0 ? <div className="lq-empty">{emptyLabel}</div> : <div className="lq-rows">{children}</div>}
    </div>
  );
}

export default function LiveQueuePanel({ snapshot, onClose, onRefresh, refreshing }: Props) {
  useEffect(() => {
    function onKey(e: KeyboardEvent) { if (e.key === "Escape") onClose(); }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const c = snapshot?.counts;
  const ispu = snapshot ? [...snapshot.ispu_to_pick, ...snapshot.ispu_ready] : [];

  return (
    <>
      <div className="hpanel-backdrop" onClick={onClose} />
      <div className="hpanel" role="dialog" aria-label="Live queue">
        {/* Header */}
        <div className="hpanel-header">
          <div className="hpanel-title">
            <span className="lq-title-icon">🧑‍🤝‍🧑</span>
            Live Queue
          </div>
          <button className="hpanel-close" onClick={onClose} aria-label="Close">✕</button>
        </div>

        {/* Summary chips */}
        <div className="lq-summary">
          <div className="lq-stat">
            <span className="lq-stat-num">{c?.waiting ?? "–"}</span>
            <span className="lq-stat-label">Waiting</span>
          </div>
          <div className="lq-stat">
            <span className="lq-stat-num">{c?.assisting ?? "–"}</span>
            <span className="lq-stat-label">Assisting</span>
          </div>
          <div className="lq-stat">
            <span className="lq-stat-num">{c?.ispu ?? "–"}</span>
            <span className="lq-stat-label">ISPU</span>
          </div>
          <div className="lq-stat">
            <span className="lq-stat-num">{c?.appointments ?? "–"}</span>
            <span className="lq-stat-label">Appts</span>
          </div>
        </div>

        {onRefresh && (
          <div className="lq-refresh-row">
            <button className="hpanel-action-btn" onClick={onRefresh} disabled={refreshing}>
              {refreshing ? "Refreshing…" : "Refresh"}
            </button>
          </div>
        )}

        {!snapshot ? (
          <div className="hpanel-section"><div className="lq-empty">Loading queue…</div></div>
        ) : (
          <>
            <Section title="Waiting" count={snapshot.waiting.length} emptyLabel="No one waiting right now.">
              {snapshot.waiting.map((e) => <QueueRow key={e.id} entry={e} kind="waiting" />)}
            </Section>

            <Section title="Being assisted" count={snapshot.assisting.length} emptyLabel="No active sessions.">
              {snapshot.assisting.map((e) => <QueueRow key={e.id} entry={e} kind="assisting" />)}
            </Section>

            <Section title="In-store pickups (ISPU)" count={ispu.length} emptyLabel="No pickups queued.">
              {snapshot.ispu_to_pick.length > 0 && (
                <div className="lq-subgroup-label">Ready to be picked</div>
              )}
              {snapshot.ispu_to_pick.map((e) => <QueueRow key={e.id} entry={e} kind="ispu_to_pick" />)}
              {snapshot.ispu_ready.length > 0 && (
                <div className="lq-subgroup-label">Picked · awaiting customer</div>
              )}
              {snapshot.ispu_ready.map((e) => <QueueRow key={e.id} entry={e} kind="ispu_ready" />)}
            </Section>

            <Section
              title="Future appointments · today"
              count={snapshot.appointments.length}
              emptyLabel="No more appointments today."
            >
              {snapshot.appointments.map((e) => <QueueRow key={e.id} entry={e} kind="appointment" />)}
            </Section>
          </>
        )}
      </div>
    </>
  );
}
