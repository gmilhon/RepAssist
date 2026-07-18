import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { A2UIElement, A2UIQueue, A2UIQueueEntry, ChatResponse, ConfirmationPayload, ListenSession, ListenUtterance, ResolutionCard } from "../types";
import { VISIT_REASONS } from "../types";
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

type LookupKind = "orders" | "tickets" | "system" | "huddle" | "queue";

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

// Live Listen demo mode — one scripted store visit, played back on a timer.
// The conversation surfaces three suggestions in order: a stuck activation
// (order ACT-1002), a higher-than-expected first bill, and a missing promo
// credit (account AC-5003). Each id is spoken in the SAME utterance as the
// first keywords for its issue so the watcher's window always has the id in
// hand when the suggestion fires (analyze batches are ~2 utterances wide).
const DEMO_SCRIPT: { speaker: "Customer" | "Rep"; text: string; delayMs: number }[] = [
  { speaker: "Rep", text: "Hi, welcome in! What can I help you with today?", delayMs: 2500 },
  { speaker: "Customer", text: "I ordered a new phone — it's order ACT-1002 — but it still says No Service. It never finished activating.", delayMs: 3400 },
  { speaker: "Rep", text: "Sorry about that — let me pull that order up and take a look.", delayMs: 3200 },
  { speaker: "Customer", text: "Thanks. The email said everything went through, but the phone has been sitting like this since last night.", delayMs: 3600 },
  { speaker: "Rep", text: "I see it. The activation never completed on our side — give me a minute to dig in.", delayMs: 3400 },
  { speaker: "Customer", text: "I appreciate it. My old phone shut off the second I opened the box, so I've had no service all morning.", delayMs: 3600 },
  { speaker: "Rep", text: "That's the worst timing. While I look at this, is there anything else going on with the account?", delayMs: 3200 },
  { speaker: "Customer", text: "Actually, yes — my bill came in a lot higher this month than I was quoted when I signed up.", delayMs: 3600 },
  { speaker: "Rep", text: "A higher first bill usually comes from partial-month charges. I can go over it with you line by line.", delayMs: 3400 },
  { speaker: "Customer", text: "That would help — the total seemed way off from what they wrote down for me in the store.", delayMs: 3400 },
  { speaker: "Rep", text: "We'll get it sorted before you leave. Anything else while I have your info up?", delayMs: 3000 },
  { speaker: "Customer", text: "One more thing — I don't think we ever got the twenty dollars off they wrote on my receipt when I signed up.", delayMs: 3600 },
  { speaker: "Rep", text: "Let me check that too — can you read me the account number from the top of the receipt?", delayMs: 3000 },
  { speaker: "Customer", text: "It's account AC-5003 — they said a monthly promo discount would show up on the account, and it never did.", delayMs: 3600 },
];

function formatElapsed(totalSeconds: number): string {
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

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

  // Check-in form state
  const [checkInOpen, setCheckInOpen] = useState(false);
  const [ciReason, setCiReason] = useState(VISIT_REASONS[0].value);
  const [ciName, setCiName] = useState("");
  const [ciPhone, setCiPhone] = useState("");
  const [ciError, setCiError] = useState<string | null>(null);

  // Live Listen state — its own SpeechRecognition instance (never shared with
  // the composer mic) plus batching machinery for the read-only watcher.
  const [listenSession, setListenSession] = useState<ListenSession | null>(null);
  const [listenSetupOpen, setListenSetupOpen] = useState(false);
  const [listenMode, setListenMode] = useState<"mic" | "demo">("mic");
  const [listenQueue, setListenQueue] = useState<A2UIQueueEntry[]>([]);
  const [listenEntryId, setListenEntryId] = useState<string | null>(null);
  const [liveUtterances, setLiveUtterances] = useState<ListenUtterance[]>([]);
  const [listenInterim, setListenInterim] = useState("");
  const [listenElapsed, setListenElapsed] = useState(0);
  const listenSessionRef = useRef<ListenSession | null>(null);
  const listenEntitiesRef = useRef<Record<string, string>>({});
  const listenActiveRef = useRef(false);
  const listenRecRef = useRef<any>(null);
  const pendingBufferRef = useRef<ListenUtterance[]>([]);
  const analyzeTimerRef = useRef<number | null>(null);
  const analyzeInFlightRef = useRef(false);
  const lastAnalyzeRef = useRef(0);
  const demoTimerRef = useRef<number | null>(null);
  const elapsedTimerRef = useRef<number | null>(null);
  const listenStartedAtRef = useRef(0);

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
        : kind === "queue" ? await api.queue()
        : await api.morningHuddle();
      setMessages((m) => [...m, { role: "assistant", a2ui: res.elements }]);
      scrollDown();
    } catch {
      /* MCP unavailable — silently ignore */
    }
  }

  async function submitCheckIn() {
    if (!ciName.trim() && !ciPhone.trim()) {
      setCiError("Enter the customer's name or phone number.");
      return;
    }
    setCiError(null);
    setBusy(true);
    try {
      const res = await api.checkIn({
        customer_name: ciName.trim() || undefined,
        customer_phone: ciPhone.trim() || undefined,
        reason: ciReason,
      });
      const label = res.entry.customer_name ?? res.entry.customer_phone ?? "Customer";
      const reasonLabel = VISIT_REASONS.find((r) => r.value === ciReason)?.label ?? ciReason;
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          content: `✅ ${label} checked in — ${reasonLabel}. #${res.queue_position} in line.`,
        },
      ]);
      setCheckInOpen(false);
      setCiName("");
      setCiPhone("");
      setCiReason(VISIT_REASONS[0].value);
      scrollDown();
    } catch (e) {
      setCiError(String(e));
    } finally {
      setBusy(false);
    }
  }

  // Queue card "Assist" → claim the entry, then drop into a normal chat turn
  // with the customer's name/phone/reason already known.
  async function assistFromQueue(entry: A2UIQueueEntry) {
    try {
      await api.assistQueueEntry(entry.id, "rep.demo", threadId);
    } catch {
      /* best-effort — still let the rep start the conversation */
    }
    const entities: Record<string, string> = { visit_reason: entry.reason };
    if (entry.customer_name) entities.customer_name = entry.customer_name;
    if (entry.customer_phone) entities.customer_phone = entry.customer_phone;
    send(entry.prompt, entities);
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

  // ── Live Listen ──────────────────────────────────────────────────────────
  // A continuous transcription feed (mic or scripted demo) rolls into a
  // transcript; batches go to the read-only watcher, which may return
  // suggestion cards. Analyze runs in the background and never sets `busy`.

  function openListenSetup() {
    if (listenSession) {
      stopListen();
      return;
    }
    setListenMode(speechSupported ? "mic" : "demo");
    setListenEntryId(null);
    setListenQueue([]);
    setListenSetupOpen(true);
    scrollDown();
    api.queue()
      .then((res) => {
        const q = res.elements.find((e): e is A2UIQueue => e.type === "queue");
        setListenQueue((q?.entries ?? []).filter((e) => e.status === "waiting"));
      })
      .catch(() => {
        /* MCP unavailable — leave the picker empty */
      });
  }

  async function startListen() {
    const entry = listenQueue.find((e) => e.id === listenEntryId);
    if (!entry || busy) return;
    setBusy(true);
    try {
      const res = await api.listenStart(entry.id, threadId, listenMode);
      if (listening) recognitionRef.current?.stop(); // composer dictation yields to Live Listen
      setThreadId(res.thread_id);
      listenEntitiesRef.current = res.entities;
      listenSessionRef.current = res.session;
      setListenSession(res.session);
      setListenSetupOpen(false);
      setLiveUtterances([]);
      setListenInterim("");
      pendingBufferRef.current = [];
      lastAnalyzeRef.current = 0;
      listenActiveRef.current = true;
      listenStartedAtRef.current = Date.now();
      setListenElapsed(0);
      elapsedTimerRef.current = window.setInterval(() => {
        setListenElapsed(Math.floor((Date.now() - listenStartedAtRef.current) / 1000));
      }, 1000);
      const label = res.session.customer_name ?? res.session.customer_phone ?? "the customer";
      const reasonLabel = VISIT_REASONS.find((r) => r.value === res.session.reason)?.label ?? res.session.reason;
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          content: `🎧 Live Listen started — assisting ${label} (${reasonLabel}). I'll flag anything I can help with.`,
        },
      ]);
      if (listenMode === "demo") playDemoScript();
      else startListenRecognition();
      scrollDown();
    } catch (e) {
      setMessages((m) => [...m, { role: "assistant", content: `⚠️ ${e}` }]);
    } finally {
      setBusy(false);
    }
  }

  function startListenRecognition() {
    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SR) return;
    const rec = new SR();
    rec.lang = "en-US";
    rec.interimResults = true;
    rec.continuous = true;
    rec.onresult = (e: any) => {
      // stop() can still flush a final result after teardown — drop it so a
      // stale utterance never re-arms the analyze timer or leaks into the
      // next customer's session.
      if (!listenActiveRef.current || listenRecRef.current !== rec) return;
      let interim = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i];
        if (r.isFinal) {
          const text = r[0].transcript.trim();
          if (text) pushUtterance({ speaker: null, text });
        } else {
          interim += r[0].transcript;
        }
      }
      setListenInterim(interim.trim());
    };
    rec.onerror = (e: any) => {
      if (e?.error === "no-speech" || e?.error === "aborted") return; // onend restarts
      // Fatal errors (denied mic, no device, unreachable speech service)
      // recur instantly on restart — detach the instance so onend's identity
      // guard blocks the restart loop, and warn once. The session stays up;
      // the rep can Stop it.
      const fatal = ["not-allowed", "service-not-allowed", "audio-capture", "network"].includes(e?.error);
      if (fatal && listenRecRef.current === rec) listenRecRef.current = null;
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          content: fatal
            ? `⚠️ Live Listen can't use the microphone (${e?.error}) — transcription is off. Press Stop to end the session.`
            : `⚠️ Live Listen mic error (${e?.error ?? "unknown"}) — I'll keep trying; press Stop to end the session.`,
        },
      ]);
    };
    rec.onend = () => {
      // The Web Speech API stops itself on silence — restart until Stop.
      if (listenActiveRef.current && listenRecRef.current === rec) {
        try { rec.start(); } catch { /* already restarting */ }
      }
    };
    listenRecRef.current = rec;
    try { rec.start(); } catch { /* ignore */ }
  }

  function playDemoScript() {
    let i = 0;
    const step = () => {
      if (!listenActiveRef.current || i >= DEMO_SCRIPT.length) return;
      const line = DEMO_SCRIPT[i++];
      demoTimerRef.current = window.setTimeout(() => {
        if (!listenActiveRef.current) return;
        pushUtterance({ speaker: line.speaker, text: line.text });
        step();
      }, line.delayMs);
    };
    step();
  }

  function pushUtterance(u: ListenUtterance) {
    setLiveUtterances((prev) => [...prev, u]);
    pendingBufferRef.current.push(u);
    scheduleAnalyze();
  }

  // Batch utterances to the watcher: fire immediately once ≥6s have passed
  // since the last analyze call, otherwise trail with a 2.5s debounce.
  function scheduleAnalyze() {
    if (Date.now() - lastAnalyzeRef.current >= 6000) {
      runAnalyze();
      return;
    }
    if (analyzeTimerRef.current !== null) window.clearTimeout(analyzeTimerRef.current);
    analyzeTimerRef.current = window.setTimeout(runAnalyze, 2500);
  }

  async function runAnalyze() {
    if (analyzeTimerRef.current !== null) {
      window.clearTimeout(analyzeTimerRef.current);
      analyzeTimerRef.current = null;
    }
    const session = listenSessionRef.current;
    if (!session || pendingBufferRef.current.length === 0) return;
    if (analyzeInFlightRef.current) {
      analyzeTimerRef.current = window.setTimeout(runAnalyze, 2500);
      return;
    }
    const batch = pendingBufferRef.current.splice(0, pendingBufferRef.current.length);
    lastAnalyzeRef.current = Date.now();
    analyzeInFlightRef.current = true;
    try {
      const res = await api.listenAnalyze(session.id, batch);
      // A late response after Stop / New conversation / a new session must
      // not plant cards or entities into a different conversation.
      if (listenSessionRef.current?.id !== session.id) return;
      // Fold newly-learned ids into the session entities so accepting an
      // earlier card still carries them (e.g. an account id spoken after the
      // promo card fired). Same key filter as the backend's per-suggestion
      // entities — notably NOT ticket_ref_id/mtn, which would reroute triage.
      for (const k of ["order_id", "account_id", "customer_name", "customer_phone", "visit_reason"]) {
        if (res.entities[k]) listenEntitiesRef.current[k] = res.entities[k];
      }
      if (res.suggestions.length) {
        setMessages((m) => [
          ...m,
          ...res.suggestions.map((s): Msg => ({ role: "assistant", a2ui: [{ type: "live_suggestion", ...s }] })),
        ]);
        scrollDown();
      }
    } catch (e) {
      console.warn("Live Listen analyze failed", e); // listening must never break chat
    } finally {
      analyzeInFlightRef.current = false;
      if (pendingBufferRef.current.length) scheduleAnalyze();
    }
  }

  function teardownListen() {
    listenActiveRef.current = false;
    if (analyzeTimerRef.current !== null) {
      window.clearTimeout(analyzeTimerRef.current);
      analyzeTimerRef.current = null;
    }
    if (demoTimerRef.current !== null) {
      window.clearTimeout(demoTimerRef.current);
      demoTimerRef.current = null;
    }
    if (elapsedTimerRef.current !== null) {
      window.clearInterval(elapsedTimerRef.current);
      elapsedTimerRef.current = null;
    }
    const rec = listenRecRef.current;
    listenRecRef.current = null;
    try { rec?.stop(); } catch { /* ignore */ }
  }

  async function stopListen() {
    const session = listenSessionRef.current;
    teardownListen();
    listenSessionRef.current = null;
    setListenSession(null);
    setListenInterim("");
    setLiveUtterances([]);
    pendingBufferRef.current = [];
    // Drop the session's customer entities: leaving them would contaminate
    // every later card click with the previous customer's order/account ids
    // (suggestion cards are unaffected — they snapshot their own entities).
    listenEntitiesRef.current = {};
    if (!session) return;
    try {
      const res = await api.listenStop(session.id);
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          content: `🎧 Live Listen ended — ${res.recap.utterances} utterances, ${res.recap.suggestions} suggestions, ${res.recap.duration_label}.`,
        },
      ]);
      scrollDown();
    } catch (e) {
      console.warn("Live Listen stop failed", e);
    }
  }

  // Teardown on unmount — switching tabs kills the session (accepted
  // prototype limitation); still end it server-side best-effort. A hard tab
  // close never fires unmount, so also end the session via sendBeacon on
  // pagehide, otherwise it leaks as 'active' forever.
  useEffect(() => {
    const endOnPageHide = () => {
      const session = listenSessionRef.current;
      if (session) navigator.sendBeacon(`/api/listen/${session.id}/stop`);
    };
    window.addEventListener("pagehide", endOnPageHide);
    return () => {
      window.removeEventListener("pagehide", endOnPageHide);
      const session = listenSessionRef.current;
      if (session) api.listenStop(session.id).catch(() => { /* best-effort */ });
      teardownListen();
    };
  }, []);

  // A2UI card action → normal chat turn. While a Live Listen session is
  // active, its customer entities ride underneath the card's own (order/
  // account ids win) so accepted suggestions carry full context. Never merge
  // outside an active session — stale ids would target the wrong customer.
  function a2uiAction(prompt: string, entities?: Record<string, string>) {
    const listenEntities = listenSessionRef.current ? listenEntitiesRef.current : {};
    const merged = { ...listenEntities, ...(entities ?? {}) };
    send(prompt, Object.keys(merged).length ? merged : undefined);
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
    if (listenSessionRef.current) {
      api.listenStop(listenSessionRef.current.id).catch(() => { /* best-effort */ });
    }
    teardownListen();
    listenSessionRef.current = null;
    listenEntitiesRef.current = {};
    setListenSession(null);
    setListenSetupOpen(false);
    setLiveUtterances([]);
    setListenInterim("");
    pendingBufferRef.current = [];
    setMessages([]);
    setThreadId(null);
    setPending(null);
    setInput("");
    setCheckInOpen(false);
    setCiError(null);
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

        <div className="cta-subhead">Front desk</div>
        <div className="cta-tiles">
          <button
            className="cta-tile"
            disabled={busy}
            onClick={() => {
              setCiError(null);
              setCheckInOpen(true);
            }}
          >
            <span className="cta-tile-icon">📝</span>
            <span className="cta-tile-label">Check In</span>
          </button>
          <button className="cta-tile cta-tile--lookup" disabled={busy} onClick={() => showLookup("queue")}>
            <span className="cta-tile-icon">🧑‍🤝‍🧑</span>
            <span className="cta-tile-label">View queue</span>
            <span className="cta-tile-chevron">›</span>
          </button>
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
              {m.a2ui && (
                <A2UIRenderer elements={m.a2ui} onAction={a2uiAction} onOpenArticle={openArticle} onAssist={assistFromQueue} actionsDisabled={busy} />
              )}
            </div>
          ))}

          {checkInOpen && (
            <div className="bubble assistant">
              <div className="confirm-card checkin-card">
                <div className="confirm-head">📝 Check in a customer</div>
                <div className="checkin-field">
                  <label htmlFor="ci-reason">Reason for visit</label>
                  <select id="ci-reason" value={ciReason} onChange={(e) => setCiReason(e.target.value)}>
                    {VISIT_REASONS.map((r) => (
                      <option key={r.value} value={r.value}>{r.label}</option>
                    ))}
                  </select>
                </div>
                <div className="checkin-row">
                  <div className="checkin-field">
                    <label htmlFor="ci-name">Customer name</label>
                    <input
                      id="ci-name"
                      value={ciName}
                      placeholder="Jane Rivera"
                      onChange={(e) => setCiName(e.target.value)}
                    />
                  </div>
                  <div className="checkin-field">
                    <label htmlFor="ci-phone">Phone number</label>
                    <input
                      id="ci-phone"
                      value={ciPhone}
                      placeholder="(555) 010-1001"
                      onChange={(e) => setCiPhone(e.target.value)}
                    />
                  </div>
                </div>
                <p className="checkin-hint">Name or phone number — at least one is required.</p>
                {ciError && <p className="checkin-error">{ciError}</p>}
                <div className="confirm-actions">
                  <button className="btn primary" disabled={busy} onClick={submitCheckIn}>
                    Check in
                  </button>
                  <button className="btn ghost" disabled={busy} onClick={() => setCheckInOpen(false)}>
                    Cancel
                  </button>
                </div>
              </div>
            </div>
          )}

          {listenSetupOpen && !listenSession && (
            <div className="bubble assistant">
              <div className="confirm-card listen-setup">
                <div className="confirm-head">🎧 Start Live Listen</div>
                <p className="listen-setup-hint">
                  Pick who you're helping — I'll listen along and flag anything I can fix.
                </p>
                {listenQueue.length === 0 ? (
                  <p className="a2ui-empty">No one is waiting — use Check In first.</p>
                ) : (
                  <div className="listen-queue-rows">
                    {listenQueue.map((e) => (
                      <button
                        key={e.id}
                        type="button"
                        className={`listen-queue-row${listenEntryId === e.id ? " selected" : ""}`}
                        onClick={() => setListenEntryId(e.id)}
                      >
                        <span className="listen-queue-name">{e.customer_name ?? e.customer_phone ?? "Customer"}</span>
                        <span className="listen-queue-meta">{e.reason_label} · {e.wait_label} waiting</span>
                      </button>
                    ))}
                  </div>
                )}
                <div className="listen-mode">
                  <span className="listen-mode-label">Audio source</span>
                  <div className="listen-mode-toggle">
                    <button
                      type="button"
                      className={`listen-mode-btn${listenMode === "mic" ? " selected" : ""}`}
                      disabled={!speechSupported}
                      onClick={() => setListenMode("mic")}
                    >
                      🎤 Microphone
                    </button>
                    <button
                      type="button"
                      className={`listen-mode-btn${listenMode === "demo" ? " selected" : ""}`}
                      onClick={() => setListenMode("demo")}
                    >
                      🎬 Demo conversation
                    </button>
                  </div>
                  {!speechSupported && (
                    <p className="checkin-hint">
                      Mic transcription isn't supported in this browser — Demo plays a scripted visit.
                    </p>
                  )}
                </div>
                <div className="confirm-actions">
                  <button className="btn primary" disabled={busy || !listenEntryId} onClick={startListen}>
                    Start listening
                  </button>
                  <button className="btn ghost" disabled={busy} onClick={() => setListenSetupOpen(false)}>
                    Cancel
                  </button>
                </div>
              </div>
            </div>
          )}

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

          {listenSession && (
            <div className="listen-strip">
              <div className="listen-strip-head">
                <span className="listen-live-dot" />
                <span className="listen-strip-label">LIVE</span>
                <span className="listen-strip-cust">
                  {listenSession.customer_name ?? listenSession.customer_phone ?? "Customer"}
                </span>
                <span className="listen-elapsed">{formatElapsed(listenElapsed)}</span>
                <button type="button" className="btn ghost small" onClick={stopListen}>
                  Stop
                </button>
              </div>
              <div className="listen-transcript">
                {liveUtterances.length === 0 && !listenInterim && (
                  <div className="listen-utterance listen-interim">Listening…</div>
                )}
                {liveUtterances.slice(-4).map((u, i) => (
                  <div key={i} className="listen-utterance">
                    {u.speaker && <b>{u.speaker}: </b>}
                    {u.text}
                  </div>
                ))}
                {listenInterim && <div className="listen-utterance listen-interim">{listenInterim}</div>}
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
              // Browsers allow one SpeechRecognition per page — starting
              // dictation during a mic-mode session would kill transcription.
              disabled={busy || listenSession?.mode === "mic"}
              title={
                listenSession?.mode === "mic"
                  ? "Voice to text is unavailable while Live Listen is using the microphone"
                  : listening ? "Stop listening" : "Voice to text"
              }
              aria-label="Voice to text"
            >
              {listening ? "◉" : "🎤"}
            </button>
          )}
          <button
            type="button"
            className={`btn listen${listenSession ? " live" : ""}`}
            onClick={openListenSetup}
            disabled={busy && !listenSession}
            title={listenSession ? "Live Listen is on — click to stop" : "Live Listen"}
            aria-label="Live Listen"
          >
            🎧
          </button>
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
