import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { A2UIElement, ChatResponse, ConfirmationPayload, ResolutionCard } from "../types";
import { A2UIRenderer } from "./A2UI";

interface Msg {
  role: "user" | "assistant";
  content?: string;
  card?: ResolutionCard | null;
}

const QUICK_STARTS = [
  "Order ACT-1001 is stuck in activation, the SIM won't activate",
  "ORD-2002 is blocking the customer's new upgrade order",
  "Account AC-3003 is missing their BOGO promo credit",
  "Why is the customer's first bill so high?",
  "Customer wants to rename their smartwatch watch face",
];

const STATUS_LABEL: Record<string, string> = {
  resolved: "Resolved",
  proposed: "Action proposed",
  cancelled: "Cancelled",
  escalated: "Escalated to human",
  info: "Info",
};

export default function ChatWidget() {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [threadId, setThreadId] = useState<string | null>(null);
  const [pending, setPending] = useState<ConfirmationPayload | null>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [a2ui, setA2ui] = useState<A2UIElement[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Proactively load A2UI elements (recent orders) from the MCP layer on mount.
  useEffect(() => {
    api.recentOrders().then((r) => setA2ui(r.elements)).catch(() => setA2ui([]));
  }, []);

  function scrollDown() {
    requestAnimationFrame(() => {
      scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
    });
  }

  function applyResponse(res: ChatResponse) {
    setThreadId(res.thread_id);
    if (res.status === "needs_confirmation") {
      setPending(res.confirmation);
    } else {
      setPending(null);
      setMessages((m) => [...m, { role: "assistant", content: res.assistant_message ?? "", card: res.card }]);
    }
    scrollDown();
  }

  async function send(text: string) {
    if (!text.trim() || busy) return;
    setMessages((m) => [...m, { role: "user", content: text }]);
    setInput("");
    setBusy(true);
    scrollDown();
    try {
      applyResponse(await api.chat(text, threadId));
    } catch (e) {
      setMessages((m) => [...m, { role: "assistant", content: `⚠️ ${e}` }]);
    } finally {
      setBusy(false);
    }
  }

  async function decide(approved: boolean) {
    if (!threadId || !pending) return;
    setBusy(true);
    const label = approved ? "Yes, apply the fix" : "No, don't make changes";
    setMessages((m) => [...m, { role: "user", content: label }]);
    setPending(null);
    try {
      applyResponse(await api.confirm(threadId, approved));
    } finally {
      setBusy(false);
    }
  }

  function reset() {
    setMessages([]);
    setThreadId(null);
    setPending(null);
  }

  return (
    <div className="chat-shell">
      <div className="chat-side">
        <h3>Common issues</h3>
        <p className="muted">Tap to start, or type your own.</p>
        {QUICK_STARTS.map((q) => (
          <button key={q} className="chip" disabled={busy} onClick={() => send(q)}>
            {q}
          </button>
        ))}
        <button className="reset" onClick={reset}>↺ New conversation</button>
      </div>

      <div className="chat-main">
        <div className="messages" ref={scrollRef}>
          {messages.length === 0 && (
            <div className="chat-intro">
              <div className="empty">
                <h2>How can I help with this order?</h2>
                <p className="muted">
                  Describe the activation, pending order, promo, or billing issue. I'll
                  resolve it with the right agent — or open a ticket for a specialist.
                </p>
              </div>
              {a2ui.length > 0 && (
                <div className="a2ui-stack">
                  <A2UIRenderer elements={a2ui} onAction={send} />
                </div>
              )}
            </div>
          )}

          {messages.map((m, i) => (
            <div key={i} className={`bubble ${m.role}`}>
              {m.content && <div className="bubble-text">{m.content}</div>}
              {m.card && <Card card={m.card} />}
            </div>
          ))}

          {pending && (
            <div className="bubble assistant">
              <div className="confirm-card">
                <div className="confirm-head">⚠️ Confirm before I make a change</div>
                <div className="confirm-prompt">{pending.prompt}</div>
                <div className="confirm-meta">
                  <code>{pending.action.service}/{pending.action.operation}</code>
                </div>
                <div className="confirm-actions">
                  <button className="btn primary" disabled={busy} onClick={() => decide(true)}>
                    Approve &amp; apply
                  </button>
                  <button className="btn ghost" disabled={busy} onClick={() => decide(false)}>
                    Decline
                  </button>
                </div>
              </div>
            </div>
          )}

          {busy && <div className="bubble assistant"><div className="typing"><span /><span /><span /></div></div>}
        </div>

        <form
          className="composer"
          onSubmit={(e) => {
            e.preventDefault();
            send(input);
          }}
        >
          <input
            value={input}
            disabled={busy}
            placeholder="Describe the order or service issue…"
            onChange={(e) => setInput(e.target.value)}
          />
          <button className="btn primary" disabled={busy || !input.trim()} type="submit">
            Send
          </button>
        </form>
      </div>
    </div>
  );
}

function Card({ card }: { card: ResolutionCard }) {
  return (
    <div className={`res-card ${card.status}`}>
      <div className="res-head">
        <span className={`badge ${card.status}`}>{STATUS_LABEL[card.status] ?? card.status}</span>
        {card.intent && <span className="tag">{card.intent.replace("_", " ")}</span>}
        {card.capability && <span className="tag muted-tag">{card.capability}</span>}
      </div>
      {card.root_cause && (
        <div className="res-row"><b>Root cause</b><span>{card.root_cause}</span></div>
      )}
      {card.actions_taken?.length > 0 && (
        <div className="res-row">
          <b>Actions</b>
          <ul>{card.actions_taken.map((a, i) => <li key={i}>{a}</li>)}</ul>
        </div>
      )}
      {card.ticket_id && (
        <div className="res-row"><b>Ticket</b><span className="ticket-id">{card.ticket_id}</span></div>
      )}
      {card.order_context && card.order_context.status && (
        <div className="res-row">
          <b>Order</b>
          <span>
            {card.order_context.order_id ?? card.order_context.account_id ?? "—"} ·{" "}
            {card.order_context.status}
            {card.order_context.device ? ` · ${card.order_context.device}` : ""}
          </span>
        </div>
      )}
    </div>
  );
}
