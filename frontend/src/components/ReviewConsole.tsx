import { useEffect, useState } from "react";
import { api } from "../api";
import type { Ticket } from "../types";

const GAP_TYPES = [
  { value: "missing_agent", label: "Missing agent — no automation exists" },
  { value: "agent_failed", label: "Agent failed — exists but returned wrong/none" },
  { value: "missing_knowledge", label: "Missing knowledge — no KB article" },
  { value: "bad_data", label: "Bad data — upstream/system issue" },
  { value: "training", label: "Training — rep education, not software" },
  { value: "none", label: "None — one-off, nothing to build" },
];

const STATUS_FILTERS = ["open", "in_review", "resolved", "all"];

export default function ReviewConsole() {
  const [filter, setFilter] = useState("open");
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [selected, setSelected] = useState<Ticket | null>(null);
  const agent = "tier2.you";

  // resolution form
  const [notes, setNotes] = useState("");
  const [rootCause, setRootCause] = useState("");
  const [capability, setCapability] = useState("");
  const [gapType, setGapType] = useState("missing_agent");

  async function load() {
    const list = await api.listTickets(filter === "all" ? undefined : filter);
    setTickets(list);
    if (selected) {
      const fresh = list.find((t) => t.id === selected.id);
      setSelected(fresh ?? null);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter]);

  function pick(t: Ticket) {
    setSelected(t);
    setNotes(t.resolution_notes ?? "");
    setRootCause(t.root_cause_category ?? "");
    setCapability(t.recommended_capability ?? "");
    setGapType(t.gap_type ?? "missing_agent");
  }

  async function claim() {
    if (!selected) return;
    await api.claimTicket(selected.id, agent);
    await load();
  }

  async function resolve(closeOnly: boolean) {
    if (!selected) return;
    await api.resolveTicket(selected.id, {
      resolution_notes: notes,
      root_cause_category: rootCause,
      recommended_capability: capability,
      gap_type: gapType,
      resolved_by: agent,
      close_only: closeOnly,
    });
    await load();
  }

  return (
    <div className="desk">
      <div className="queue">
        <div className="queue-head">
          <h3>Ticket queue</h3>
          <select value={filter} onChange={(e) => setFilter(e.target.value)}>
            {STATUS_FILTERS.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
        {tickets.length === 0 && <p className="muted pad">No tickets in this view.</p>}
        {tickets.map((t) => (
          <button
            key={t.id}
            className={`queue-item ${selected?.id === t.id ? "sel" : ""}`}
            onClick={() => pick(t)}
          >
            <div className="qi-top">
              <span className="ticket-id">{t.id}</span>
              <span className={`pri ${t.priority}`}>{t.priority}</span>
            </div>
            <div className="qi-sum">{t.summary}</div>
            <div className="qi-meta">
              <span className="tag">{t.intent.replace("_", " ")}</span>
              <span className={`status-dot ${t.status}`}>{t.status}</span>
            </div>
          </button>
        ))}
      </div>

      <div className="detail">
        {!selected ? (
          <div className="empty pad">
            <h2>Resolution Desk</h2>
            <p className="muted">
              Select a ticket to review the order, the conversation, and what the
              assistant tried — then resolve it and tell the dev team what to build.
            </p>
          </div>
        ) : (
          <>
            <div className="detail-head">
              <div>
                <span className="ticket-id big">{selected.id}</span>
                <span className={`status-dot ${selected.status}`}>{selected.status}</span>
              </div>
              {selected.status === "open" && (
                <button className="btn ghost" onClick={claim}>Claim ticket</button>
              )}
            </div>

            <div className="detail-grid">
              <section>
                <h4>Conversation</h4>
                <div className="transcript">
                  {selected.conversation.map((m, i) => (
                    <div key={i} className={`t-line ${m.role}`}>
                      <b>{m.role === "user" ? "Rep" : "Assistant"}</b>
                      <span>{m.content}</span>
                    </div>
                  ))}
                </div>

                <h4>What the assistant tried</h4>
                <div className="trace">
                  {selected.trace.map((s, i) => (
                    <code key={i}>{s.node}{s.intent ? ` · ${s.intent}` : ""}</code>
                  ))}
                </div>
              </section>

              <section>
                <h4>Order context</h4>
                <pre className="ctx">
                  {JSON.stringify(selected.order_context ?? { note: "none captured" }, null, 2)}
                </pre>
              </section>
            </div>

            <div className="resolve-form">
              <h4>Resolve &amp; give feedback</h4>
              <label>Resolution notes</label>
              <textarea value={notes} onChange={(e) => setNotes(e.target.value)}
                placeholder="What you did to fix it for the customer…" />

              <label>Root cause</label>
              <input value={rootCause} onChange={(e) => setRootCause(e.target.value)}
                placeholder="Underlying cause" />

              <div className="form-row">
                <div>
                  <label>Recommended agent / skill for the dev team</label>
                  <input value={capability} onChange={(e) => setCapability(e.target.value)}
                    placeholder="e.g. wearable-settings-agent" />
                </div>
                <div>
                  <label>Gap type</label>
                  <select value={gapType} onChange={(e) => setGapType(e.target.value)}>
                    {GAP_TYPES.map((g) => <option key={g.value} value={g.value}>{g.label}</option>)}
                  </select>
                </div>
              </div>

              <div className="form-actions">
                <button className="btn primary" disabled={!notes} onClick={() => resolve(false)}>
                  Resolve &amp; flag capability gap
                </button>
                <button className="btn ghost" disabled={!notes} onClick={() => resolve(true)}>
                  Close (no gap)
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
