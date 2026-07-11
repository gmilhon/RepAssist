import { useRef, useState } from "react";
import { api } from "../api";
import type { A2UIElement, ChatResponse, ConfirmationPayload, ResolutionCard } from "../types";
import { A2UIRenderer } from "./A2UI";

interface Msg {
  role: "user" | "assistant";
  content?: string;
  card?: ResolutionCard | null;
  a2ui?: A2UIElement[];
}

// First-step CTAs — tapping one drops a starter into the composer and focuses it
// so the rep adds the order/account id before sending.
const FIRST_STEPS: { icon: string; label: string; starter: string }[] = [
  { icon: "⚡", label: "Fix an activation", starter: "A line is stuck in activation — order " },
  { icon: "🔓", label: "Unblock an order", starter: "An order is blocking the customer's new order — order " },
  { icon: "🏷️", label: "Apply a promo", starter: "A promo or credit didn't apply — account " },
  { icon: "💵", label: "Explain a charge", starter: "The customer has a question about a charge — account " },
  { icon: "🎁", label: "Request a credit", starter: "The customer is requesting a credit — account " },
];

// Context lookups — tapping one reveals the matching A2UI card in the chat.
const LOOKUPS: { icon: string; label: string; kind: "orders" | "tickets" }[] = [
  { icon: "📦", label: "Recent orders", kind: "orders" },
  { icon: "🎫", label: "My open tickets", kind: "tickets" },
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
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  function scrollDown() {
    requestAnimationFrame(() => {
      scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
    });
  }

  // First-step tile → prefill the composer and focus (cursor at end).
  function prefill(starter: string) {
    setInput(starter);
    requestAnimationFrame(() => {
      const el = inputRef.current;
      if (el) {
        el.focus();
        el.setSelectionRange(el.value.length, el.value.length);
      }
    });
  }

  // Lookup tile → fetch the A2UI element from the MCP layer and show it as a card.
  async function showLookup(kind: "orders" | "tickets") {
    try {
      const res = kind === "orders" ? await api.recentOrders() : await api.openTickets();
      setMessages((m) => [...m, { role: "assistant", a2ui: res.elements }]);
      scrollDown();
    } catch {
      /* MCP unavailable — silently ignore */
    }
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
    setInput("");
  }

  return (
    <div className="chat-shell">
      <div className="chat-side">
        <h3>First steps</h3>
        <p className="muted">Tap to begin, or type your own.</p>

        <div className="cta-tiles">
          {FIRST_STEPS.map((s) => (
            <button key={s.label} className="cta-tile" disabled={busy} onClick={() => prefill(s.starter)}>
              <span className="cta-tile-icon">{s.icon}</span>
              <span className="cta-tile-label">{s.label}</span>
            </button>
          ))}
        </div>

        <div className="cta-subhead">Look up</div>
        <div className="cta-tiles">
          {LOOKUPS.map((c) => (
            <button
              key={c.kind}
              className="cta-tile cta-tile--lookup"
              disabled={busy}
              onClick={() => showLookup(c.kind)}
            >
              <span className="cta-tile-icon">{c.icon}</span>
              <span className="cta-tile-label">{c.label}</span>
              <span className="cta-tile-chevron">›</span>
            </button>
          ))}
        </div>

        <button className="reset" onClick={reset}>↺ New conversation</button>
      </div>

      <div className="chat-main">
        <div className="messages" ref={scrollRef}>
          {messages.length === 0 && (
            <div className="empty">
              <h2>How can I help with this order?</h2>
              <p className="muted">
                Pick a first step, or describe the activation, pending order, promo,
                or billing issue in your own words.
              </p>
            </div>
          )}

          {messages.map((m, i) => (
            <div key={i} className={`bubble ${m.role}`}>
              {m.content && <div className="bubble-text">{m.content}</div>}
              {m.card && <Card card={m.card} />}
              {m.a2ui && <A2UIRenderer elements={m.a2ui} onAction={send} />}
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
            ref={inputRef}
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
