import { useEffect, useState } from "react";
import { api } from "../api";
import type { CapabilityGap } from "../types";

/** Embeddable "what to build next" backlog, rendered as a panel inside the
 *  Performance dashboard. Fetches /api/insights/capability-gaps filtered to the
 *  same date range as the rest of the dashboard. */
export function CapabilityBacklog({ start, end }: { start?: string; end?: string }) {
  const [gaps, setGaps] = useState<CapabilityGap[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    setLoaded(false);
    api.capabilityGaps(start, end).then((d) => {
      setGaps(d.gaps);
      setLoaded(true);
    });
  }, [start, end]);

  const max = Math.max(1, ...gaps.map((g) => g.score));

  return (
    <section className="panel">
      <div className="panel-head">
        <h3>Capability backlog — what to build next</h3>
        <span className="panel-sub">ranked from resolved Tier 1/2 feedback</span>
      </div>

      {loaded && gaps.length === 0 && (
        <p className="muted">No confirmed capability gaps yet.</p>
      )}

      <div className="gap-list">
        {gaps.map((g, i) => (
          <div key={g.capability} className="gap-card">
            <div className="gap-rank">#{i + 1}</div>
            <div className="gap-body">
              <div className="gap-top">
                <span className="gap-name">{g.capability}</span>
                <span className="gap-score">priority {g.score}</span>
              </div>
              <div className="bar"><div className="bar-fill" style={{ width: `${(g.score / max) * 100}%` }} /></div>
              <div className="gap-meta">
                <span>{g.ticket_count} ticket{g.ticket_count !== 1 ? "s" : ""}</span>
                {Object.entries(g.gap_types).map(([k, v]) => (
                  <span key={k} className="tag">{k.replace("_", " ")} ×{v}</span>
                ))}
              </div>
              {g.examples.length > 0 && (
                <ul className="gap-examples">
                  {g.examples.map((e) => (
                    <li key={e.ticket_id}><code>{e.ticket_id}</code> {e.summary}</li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

export default CapabilityBacklog;
