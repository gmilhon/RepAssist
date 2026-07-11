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

// First-step CTAs — tapping one sends a starter prompt; the assistant then asks
// for the specifics it needs (order/account id).
const FIRST_STEPS: { icon: string; label: string; prompt: string }[] = [
  { icon: "⚡", label: "Fix an activation", prompt: "I have a line stuck in activation that I need to fix." },
  { icon: "🔓", label: "Unblock an order", prompt: "A customer's order is blocked and I need to release it." },
  { icon: "🏷️", label: "Apply a promo", prompt: "A promo didn't apply to a customer's account." },
  { icon: "💵", label: "Explain a charge", prompt: "I need help explaining a charge on the customer's bill." },
  { icon: "🎁", label: "Request a credit", prompt: "The customer is requesting a bill credit." },
];

type LookupKind = "orders" | "tickets" | "system" | "huddle";

// Context lookups — tapping one reveals the matching A2UI card in the chat.
const LOOKUPS: { icon: string; label: string; kind: LookupKind }[] = [
  { icon: "📦", label: "Recent orders", kind: "orders" },
  { icon: "🎫", label: "My open tickets", kind: "tickets" },
];

// Briefings — MCP-backed informational cards.
const BRIEFINGS: { icon: string; label: string; kind: LookupKind }[] = [
  { icon: "✨", label: "System enhancements", kind: "system" },
  { icon: "🚀", label: "The Opener", kind: "huddle" },
];

const STATUS_LABEL: Record<string, string> = {
  resolved: "Resolved",
  proposed: "Action proposed",
  cancelled: "Cancelled",
  escalated: "Escalated to human",
  info: "Info",
};

function timeGreeting(): string {
  const h = new Date().getHours();
  if (h < 5) return "Working late";
  if (h < 12) return "Good morning";
  if (h < 17) return "Good afternoon";
  return "Good evening";
}

export default function ChatWidget() {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [threadId, setThreadId] = useState<string | null>(null);
  const [pending, setPending] = useState<ConfirmationPayload | null>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [listening, setListening] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const recognitionRef = useRef<any>(null);

  function scrollDown() {
    requestAnimationFrame(() => {
      scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
    });
  }

  // Lookup/briefing tile → fetch the A2UI element from the MCP layer and show it.
  async function showLookup(kind: LookupKind) {
    try {
      const res =
        kind === "orders" ? await api.recentOrders()
        : kind === "tickets" ? await api.openTickets()
        : kind === "system" ? await api.systemEnhancements()
        : await api.morningHuddle();
      setMessages((m) => [...m, { role: "assistant", a2ui: res.elements }]);
      scrollDown();
    } catch {
      /* MCP unavailable — silently ignore */
    }
  }

  // Morning-Huddle "Read article" link → reveal the linked OST article card.
  async function openArticle(articleId: string) {
    try {
      const res = await api.ostArticle(articleId);
      if (res.elements.length) {
        setMessages((m) => [...m, { role: "assistant", a2ui: res.elements }]);
        scrollDown();
      }
    } catch {
      /* ignore */
    }
  }

  function applyResponse(res: ChatResponse) {
    setThreadId(res.thread_id);
    if (res.status === "needs_confirmation") {
      setPending(res.confirmation);
    } else {
      setPending(null);
      setMessages((m) => [
        ...m,
        { role: "assistant", content: res.assistant_message ?? "", card: res.card, a2ui: res.a2ui ?? undefined },
      ]);
    }
    scrollDown();
  }

  // Voice-to-text via the Web Speech API (Chrome/Edge). Hidden where unsupported.
  const speechSupported =
    typeof window !== "undefined" &&
    ("webkitSpeechRecognition" in window || "SpeechRecognition" in window);

  function toggleMic() {
    if (!speechSupported || busy) return;
    if (listening) {
      recognitionRef.current?.stop();
      return;
    }
    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    const rec = new SR();
    rec.lang = "en-US";
    rec.interimResults = true;
    rec.continuous = false;
    const base = input.trim();
    rec.onresult = (e: any) => {
      let transcript = "";
      for (let i = e.resultIndex; i < e.results.length; i++) transcript += e.results[i][0].transcript;
      setInput((base ? base + " " : "") + transcript);
    };
    rec.onerror = () => setListening(false);
    rec.onend = () => setListening(false);
    recognitionRef.current = rec;
    setListening(true);
    rec.start();
  }

  async function send(text: string, entities?: Record<string, string>) {
    if (!text.trim() || busy) return;
    setMessages((m) => [...m, { role: "user", content: text }]);
    setInput("");
    setBusy(true);
    scrollDown();
    try {
      applyResponse(await api.chat(text, threadId, "rep.demo", entities));
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
            <button key={s.label} className="cta-tile" disabled={busy} onClick={() => send(s.prompt)}>
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

        <div className="cta-subhead">Briefings</div>
        <div className="cta-tiles">
          {BRIEFINGS.map((c) => (
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
              <span className="empty-wave">👋</span>
              <h2>{timeGreeting()}! I'm here to help.</h2>
              <p className="muted">
                Stuck on an activation, a blocked order, a promo, or a billing question?
                Pick a first step and I'll sort it out — or just describe it in your own words.
                I can also keep you in the loop on what's new.
              </p>
              <div className="empty-suggest">
                <span className="empty-suggest-label">Catch up before your first customer</span>
                <div className="empty-suggest-row">
                  <button className="empty-chip" disabled={busy} onClick={() => showLookup("huddle")}>
                    🚀 Check today's Opener
                  </button>
                  <button className="empty-chip" disabled={busy} onClick={() => showLookup("system")}>
                    ✨ What's new in Rep Assist
                  </button>
                </div>
              </div>
            </div>
          )}

          {messages.map((m, i) => (
            <div key={i} className={`bubble ${m.role}`}>
              {m.content && <div className="bubble-text">{m.content}</div>}
              {m.card && <Card card={m.card} />}
              {m.a2ui && <A2UIRenderer elements={m.a2ui} onAction={send} onOpenArticle={openArticle} />}
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
            placeholder={listening ? "Listening…" : "Describe the order or service issue…"}
            onChange={(e) => setInput(e.target.value)}
          />
          {speechSupported && (
            <button
              type="button"
              className={`btn mic${listening ? " listening" : ""}`}
              onClick={toggleMic}
              disabled={busy}
              title={listening ? "Stop listening" : "Voice to text"}
              aria-label="Voice to text"
            >
              {listening ? "◉" : "🎤"}
            </button>
          )}
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
