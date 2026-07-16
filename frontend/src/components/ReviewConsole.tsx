import { useEffect, useState } from "react";
import { api } from "../api";
import type { CallAgentResult, CandidateDefect, OSTArticleRef, Ticket, TicketAnalyzeResult } from "../types";

const GAP_TYPES = [
  { value: "missing_agent", label: "Missing agent — no automation exists" },
  { value: "agent_failed", label: "Agent failed — exists but returned wrong/none" },
  { value: "missing_knowledge", label: "Missing knowledge — no KB article" },
  { value: "bad_data", label: "Bad data — upstream/system issue" },
  { value: "training", label: "Training — rep education, not software" },
  { value: "none", label: "None — one-off, nothing to build" },
];

// Subset of GAP_TYPES relevant to a system_defect one-click action.
const DEFECT_GAP_TYPES = GAP_TYPES.filter((g) =>
  ["missing_agent", "agent_failed", "bad_data"].includes(g.value)
);

const AI_CATEGORY_LABEL: Record<string, string> = {
  education: "Education",
  agent_action: "Agent",
  system_defect: "Defect",
};

const STATUS_FILTERS = ["open", "in_review", "resolved", "all"];

export default function ReviewConsole() {
  const [filter, setFilter] = useState("open");
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [selected, setSelected] = useState<Ticket | null>(null);
  const agent = "tier2.you";

  // resolution form (manual fallback, always available)
  const [notes, setNotes] = useState("");
  const [rootCause, setRootCause] = useState("");
  const [capability, setCapability] = useState("");
  const [gapType, setGapType] = useState("missing_agent");

  // AI Assisted Resolution Desk
  const [analyzing, setAnalyzing] = useState(false);
  const [analysis, setAnalysis] = useState<TicketAnalyzeResult | null>(null);
  const [ostArticles, setOstArticles] = useState<OSTArticleRef[]>([]);
  const [articleChoice, setArticleChoice] = useState("");
  const [actionBusy, setActionBusy] = useState(false);
  const [callBusy, setCallBusy] = useState(false);
  const [callDiagnosis, setCallDiagnosis] = useState<CallAgentResult["diagnosis"] | null>(null);
  const [candidates, setCandidates] = useState<CandidateDefect[]>([]);
  const [attachTo, setAttachTo] = useState("");
  const [defectGapType, setDefectGapType] = useState("missing_agent");

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
    setAnalysis(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter]);

  useEffect(() => {
    api.listHuddleArticles().then(setOstArticles).catch(() => {});
  }, []);

  function pick(t: Ticket) {
    setSelected(t);
    setNotes(t.resolution_notes ?? "");
    setRootCause(t.root_cause_category ?? "");
    setCapability(t.recommended_capability ?? "");
    setGapType(t.gap_type ?? "missing_agent");

    setArticleChoice(t.ai_article_id ?? "");
    setCallDiagnosis(null);
    setCandidates([]);
    setAttachTo("");
    setDefectGapType("missing_agent");
    if (t.ai_category === "system_defect") {
      api.candidateDefects(t.id).then((r) => setCandidates(r.issues)).catch(() => {});
    }
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

  async function runAnalyze() {
    if (filter !== "open" && filter !== "in_review") return;
    setAnalyzing(true);
    try {
      const result = await api.analyzeTickets(filter);
      setAnalysis(result);
      await load();
    } finally {
      setAnalyzing(false);
    }
  }

  async function resolveWithArticle() {
    if (!selected || !articleChoice) return;
    setActionBusy(true);
    try {
      await api.resolveEducation(selected.id, { article_id: articleChoice, resolved_by: agent });
      await load();
    } finally {
      setActionBusy(false);
    }
  }

  async function callAgentAction() {
    if (!selected) return;
    setCallBusy(true);
    setCallDiagnosis(null);
    try {
      const result = await api.callAgent(selected.id, agent);
      if (result.resolved) {
        await load();
      } else {
        setCallDiagnosis(result.diagnosis);
      }
    } finally {
      setCallBusy(false);
    }
  }

  async function fileDefectAction() {
    if (!selected) return;
    setActionBusy(true);
    try {
      await api.fileDefect(selected.id, {
        resolved_by: agent,
        gap_type: defectGapType,
        attach_to: attachTo || undefined,
      });
      await load();
    } finally {
      setActionBusy(false);
    }
  }

  const canAnalyze = filter === "open" || filter === "in_review";
  const showAiPanel =
    selected?.ai_category && (selected.status === "open" || selected.status === "in_review");

  return (
    <div className="desk">
      <div className="queue">
        <div className="queue-head">
          <h3>Ticket queue</h3>
          <div className="queue-head-actions">
            <select value={filter} onChange={(e) => setFilter(e.target.value)}>
              {STATUS_FILTERS.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
            <button
              className="btn ghost small"
              disabled={!canAnalyze || analyzing}
              title={canAnalyze ? undefined : "Switch to Open or In review to analyze"}
              onClick={runAnalyze}
            >
              {analyzing ? "Analyzing…" : "Analyze"}
            </button>
          </div>
        </div>

        {analysis && (
          <div className="ai-stats">
            <div className="ai-stat education">
              <span className="ai-stat-count">{analysis.education}</span>
              <span className="ai-stat-label">Education</span>
            </div>
            <div className="ai-stat agent_action">
              <span className="ai-stat-count">{analysis.agent_action}</span>
              <span className="ai-stat-label">Agent action</span>
            </div>
            <div className="ai-stat system_defect">
              <span className="ai-stat-count">{analysis.system_defect}</span>
              <span className="ai-stat-label">System defect</span>
            </div>
          </div>
        )}

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
              {t.ai_category && (
                <span className={`ai-badge ${t.ai_category}`}>{AI_CATEGORY_LABEL[t.ai_category]}</span>
              )}
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

            {showAiPanel && (
              <div className="ai-suggestion">
                <h4>AI suggested resolution — {AI_CATEGORY_LABEL[selected.ai_category!]}</h4>
                <p className="ai-reasoning">{selected.ai_reasoning}</p>

                {selected.ai_category === "education" && (
                  <div className="ai-action-row">
                    <select value={articleChoice} onChange={(e) => setArticleChoice(e.target.value)}>
                      <option value="">Select an OST article…</option>
                      {ostArticles.map((a) => (
                        <option key={a.article_id} value={a.article_id}>
                          {a.article_id} — {a.title}
                        </option>
                      ))}
                    </select>
                    <button
                      className="btn primary"
                      disabled={!articleChoice || actionBusy}
                      onClick={resolveWithArticle}
                    >
                      Resolve — share article
                    </button>
                  </div>
                )}

                {selected.ai_category === "agent_action" && (
                  <div className="ai-action-row">
                    <span className="ai-capability-hint">
                      Suggested: <code>{selected.ai_capability}</code>
                    </span>
                    <button className="btn primary" disabled={callBusy} onClick={callAgentAction}>
                      {callBusy ? "Calling agent…" : "Call agent & resolve"}
                    </button>
                    {callDiagnosis && (
                      <p className="ai-diagnosis-fail">
                        Agent couldn't resolve it automatically — {callDiagnosis.summary}
                        {callDiagnosis.root_cause ? ` (${callDiagnosis.root_cause})` : ""}.
                        Use the manual form below.
                      </p>
                    )}
                  </div>
                )}

                {selected.ai_category === "system_defect" && (
                  <div className="ai-action-col">
                    {candidates.length > 0 && (
                      <>
                        <label>Attach to an existing defect, or file a new one</label>
                        <select value={attachTo} onChange={(e) => setAttachTo(e.target.value)}>
                          <option value="">File a new defect</option>
                          {candidates.map((c) => (
                            <option key={c.key} value={c.key}>{c.key} — {c.summary}</option>
                          ))}
                        </select>
                      </>
                    )}
                    <label>Gap type</label>
                    <select value={defectGapType} onChange={(e) => setDefectGapType(e.target.value)}>
                      {DEFECT_GAP_TYPES.map((g) => <option key={g.value} value={g.value}>{g.label}</option>)}
                    </select>
                    <button className="btn primary" disabled={actionBusy} onClick={fileDefectAction}>
                      {attachTo ? `Attach to ${attachTo} & resolve` : "File defect & resolve"}
                    </button>
                  </div>
                )}
              </div>
            )}

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
