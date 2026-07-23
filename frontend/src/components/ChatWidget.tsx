import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { ChatAction, LookupKind, QueueAssistTarget } from "../chatActions";
import type { A2UICoachingEntry, A2UIElement, A2UIEnhancement, A2UIQueue, A2UIQueueEntry, BarcodeProduct, Cart, ChatResponse, CheckoutView, CoachingResult, ConfirmationPayload, ListenSession, ListenUtterance, PlaybookGrade, ResolutionCard, ScanBillResult, SendSummaryResult, SwitchExtras, VisitSummary, Walkthrough } from "../types";
import { VISIT_REASONS } from "../types";
import { A2UIRenderer, Stars } from "./A2UI";
import { CheckoutFlow, type CheckoutHandlers } from "./Checkout";
import Scanner from "./Scanner";
import { SALES_DEMOS, SERVICE_DEMOS, type Demo } from "../demos";

interface VisitRecap {
  sessionId: string;
  customerName: string | null;
  summary: VisitSummary;
}

interface Msg {
  role: "user" | "assistant";
  content?: string;
  card?: ResolutionCard | null;
  a2ui?: A2UIElement[];
  visit?: VisitRecap;
  grade?: PlaybookGrade;
  coaching?: CoachingResult;
  demos?: boolean;   // the "Run a demo" picker card
  walkthrough?: { title: string; steps: Walkthrough; gifUrl?: string | null; gifCaption?: string | null; videoUrl?: string | null };
  scanBill?: ScanBillResult;   // Scan Bill → competitor-switch analysis card
  product?: BarcodeProduct;    // Scan Barcode → product lookup card
}

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

// Shopping demo (played when assisting an Upgrade / New Service visit): the
// customer drives each cart action so the top cart drawer builds and edits
// itself live as the conversation plays. Only the customer's lines carry the
// shopping intent — the rep confirms briefly — so nothing is double-applied.
const SHOPPING_DEMO_SCRIPT: { speaker: "Customer" | "Rep"; text: string; delayMs: number }[] = [
  { speaker: "Rep", text: "Welcome back, Ms. Rivera! What can I set you up with today?", delayMs: 2600 },
  { speaker: "Customer", text: "I'd love to trade in my old iPhone for the new iPhone 17 Pro on Unlimited Ultimate.", delayMs: 3800 },
  { speaker: "Rep", text: "Perfect — and that trade-in credit makes it a great deal.", delayMs: 3000 },
  { speaker: "Customer", text: "Actually, hold on — let me go with the Pixel 10 instead.", delayMs: 3600 },
  { speaker: "Rep", text: "You got it.", delayMs: 2400 },
  { speaker: "Customer", text: "And add the protection plan on that Pixel — I always crack my screen.", delayMs: 3800 },
  { speaker: "Rep", text: "Smart call — that's covered now.", delayMs: 2600 },
  { speaker: "Customer", text: "Can I add a new line for my daughter? She'd like the Galaxy S26.", delayMs: 3800 },
  { speaker: "Rep", text: "Of course.", delayMs: 2200 },
  { speaker: "Customer", text: "Put her on the Unlimited Ultimate plan — she streams a lot.", delayMs: 3600 },
  { speaker: "Rep", text: "Done.", delayMs: 2200 },
  { speaker: "Customer", text: "Oh, and put Netflix on the account for her too.", delayMs: 3400 },
  { speaker: "Rep", text: "Added.", delayMs: 2000 },
  { speaker: "Customer", text: "And grab a case for the Pixel while we're at it.", delayMs: 3400 },
  { speaker: "Rep", text: "Got it — anything else?", delayMs: 2400 },
  { speaker: "Customer", text: "That's everything, thanks.", delayMs: 2800 },
  { speaker: "Rep", text: "Perfect — Pixel 10 upgrade with protection, a new line for your daughter on Ultimate, Netflix, and a case. Let's review it together and place the order.", delayMs: 3200 },
];


// Stretch scripted demo-conversation delays (Live Listen + the manual demo mode)
// so a viewer can follow along. Purely a playback pace — it never delays the
// real system, API, or LLM calls.
const DEMO_LINE_PACE = 1.7;

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

interface ChatWidgetProps {
  onOpenMenu: () => void;
  chatAction: ChatAction | null;
  chatActionNonce: number;
  onChatActionDone: () => void;
}

export default function ChatWidget({ onOpenMenu, chatAction, chatActionNonce, onChatActionDone }: ChatWidgetProps) {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [threadId, setThreadId] = useState<string | null>(null);
  const [pending, setPending] = useState<ConfirmationPayload | null>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [listening, setListening] = useState(false);
  // Shopping cart (built through the chat; shown in the top cart drawer).
  const [cart, setCart] = useState<Cart | null>(null);
  const [cartOpen, setCartOpen] = useState(false);
  // Guided POS checkout (View Together → payment → signature), rendered inline.
  const [checkout, setCheckout] = useState<CheckoutView | null>(null);
  const [checkoutBusy, setCheckoutBusy] = useState(false);
  const [accountId, setAccountId] = useState<string | null>(null);
  const checkoutRef = useRef<CheckoutView | null>(null);
  // Auto-collapse timer: the cart drawer flashes open when it changes, then
  // collapses so the chat keeps focus (the compact cart bar stays visible).
  const cartFlashRef = useRef<number | null>(null);
  // A synchronously-updated thread id so the demo runner (which holds a stale
  // render closure across awaited turns) always sends on the live thread.
  const threadIdRef = useRef<string | null>(null);
  // Auto-driven demo state.
  const [demoRunning, setDemoRunning] = useState<Demo | null>(null);
  const demoAbortRef = useRef(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const lastActionNonce = useRef(0);
  const recognitionRef = useRef<any>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Auto-grow the composer textarea with its content (up to a cap), and shrink
  // back to a single line once it's cleared (e.g. after send).
  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 140)}px`;
  }, [input]);

  function onComposerKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    // Enter submits; Shift+Enter (and IME composition) inserts a newline.
    if (e.key === "Enter" && !e.shiftKey && !(e.nativeEvent as any).isComposing) {
      e.preventDefault();
      if (!busy && !demoRunning && input.trim()) send(input);
    }
  }

  // Barcode / bill scanner modal (camera). null when closed.
  const [scanner, setScanner] = useState<null | "barcode" | "bill">(null);

  // Check-in form state
  const [checkInOpen, setCheckInOpen] = useState(false);
  const [ciReason, setCiReason] = useState(VISIT_REASONS[0].value);
  const [ciName, setCiName] = useState("");
  const [ciPhone, setCiPhone] = useState("");
  const [ciAccount, setCiAccount] = useState("");
  const [ciOrder, setCiOrder] = useState("");
  const [ciError, setCiError] = useState<string | null>(null);
  // Visit-summary send state, keyed by listen session id.
  const [summarySends, setSummarySends] = useState<Record<string, { sending: boolean; result: SendSummaryResult | null }>>({});

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

  // Scan Barcode → resolve a UPC to a catalog product and show a product card.
  async function handleBarcode(upc: string) {
    setScanner(null);
    setBusy(true);
    try {
      const res = await api.productByUpc(upc);
      if (res.product) {
        setMessages((m) => [...m, { role: "assistant", product: res.product! }]);
      } else {
        setMessages((m) => [...m, { role: "assistant", content: `No catalog match for UPC ${upc}. Try describing the product instead.` }]);
      }
    } catch (e) {
      setMessages((m) => [...m, { role: "assistant", content: `Couldn't look up that barcode (${e}).` }]);
    } finally {
      setBusy(false);
      scrollDown();
    }
  }

  // Scan Bill → OCR a competitor bill and show the switch-analysis card.
  async function handleBillCapture(base64: string, mediaType: string) {
    setScanner(null);
    setBusy(true);
    try {
      const res = await api.scanBill(base64, mediaType, threadIdRef.current);
      setMessages((m) => [...m, { role: "assistant", scanBill: res }]);
    } catch (e) {
      setMessages((m) => [...m, { role: "assistant", content: `Couldn't analyze that bill (${e}).` }]);
    } finally {
      setBusy(false);
      scrollDown();
    }
  }

  // Coaching tile → card of recent graded visits.
  async function showCoaching() {
    try {
      const res = await api.coachingRecent();
      setMessages((m) => [...m, { role: "assistant", a2ui: res.elements }]);
      scrollDown();
    } catch {
      /* ignore */
    }
  }

  // Show a feature walkthrough — steps, then a demo GIF, then a video if one
  // was uploaded — all in one card in the thread.
  function onWalkthrough(e: A2UIEnhancement) {
    const steps = e.walkthrough ?? { intro: "", steps: [] };
    setMessages((m) => [...m, {
      role: "assistant",
      walkthrough: { title: e.title, steps, gifUrl: e.gif_url, gifCaption: e.gif_caption, videoUrl: e.video_url },
    }]);
    scrollDown();
  }

  // Select a graded visit → GenAI coaching recommendation card.
  async function onCoach(entry: A2UICoachingEntry) {
    if (busy) return;
    setBusy(true);
    try {
      const res = await api.coachingRecommend(entry.session_id);
      setMessages((m) => [...m, { role: "assistant", coaching: res }]);
      scrollDown();
    } catch (e) {
      setMessages((m) => [...m, { role: "assistant", content: `Couldn't load coaching (${String(e)}).` }]);
    } finally {
      setBusy(false);
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
        account_id: ciAccount.trim() || undefined,
        order_id: ciOrder.trim() || undefined,
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
      setCiAccount("");
      setCiOrder("");
      setCiReason(VISIT_REASONS[0].value);
      scrollDown();
    } catch (e) {
      setCiError(String(e));
    } finally {
      setBusy(false);
    }
  }

  // Claim a queued customer + drop into a normal chat turn with their
  // name/phone/reason/account already known. Shared by the queue A2UI card, the
  // Live Queue tray (App → chatAction "assist"), and the demo runner.
  async function assistCustomer(t: QueueAssistTarget) {
    try {
      await api.assistQueueEntry(t.id, "rep.demo", threadId);
    } catch {
      /* best-effort — still let the rep start the conversation */
    }
    const entities: Record<string, string> = { visit_reason: t.reason };
    if (t.customer_name) entities.customer_name = t.customer_name;
    if (t.customer_phone) entities.customer_phone = t.customer_phone;
    if (t.account_id) { entities.account_id = t.account_id; setAccountId(t.account_id); }
    if (t.order_id) entities.order_id = t.order_id;
    // Surface the customer's account summary card up front so the rep can see
    // their lines/devices/plans and any opportunities before assisting.
    try {
      const acct = await api.shopAccount(t.account_id);
      if (acct.elements?.length) {
        setMessages((m) => [...m, { role: "assistant", a2ui: acct.elements }]);
      }
    } catch {
      /* account summary is best-effort */
    }
    const who = t.customer_name ?? t.customer_phone ?? "the customer";
    send(`I'm now assisting ${who} — they're here for: ${t.reason_label}.`, entities);
  }

  // Queue A2UI card "Assist" → same flow, built from the card's richer entry.
  function assistFromQueue(entry: A2UIQueueEntry) {
    assistCustomer({
      id: entry.id, customer_name: entry.customer_name, customer_phone: entry.customer_phone,
      reason: entry.reason, reason_label: entry.reason_label, account_id: entry.account_id ?? null,
    });
  }

  // ── Demos ──────────────────────────────────────────────────────────────────
  // A synthetic (blank) signature image for auto-run checkouts — hashed to a
  // demo ref server-side, never real PII.
  const DEMO_SIGNATURE =
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==";

  const wait = (ms: number) => new Promise<void>((r) => window.setTimeout(r, ms));

  function showDemos() {
    setMessages((m) => [...m, { role: "assistant", demos: true }]);
    scrollDown();
  }

  // Send a rep turn and, if the assistant proposes a mutating action, approve it
  // (demos run the happy path end-to-end).
  async function runnerSend(text: string, entities?: Record<string, string>) {
    const res = await send(text, entities);
    if (res?.status === "needs_confirmation" && res.confirmation) {
      await wait(1400);
      const isShop = res.confirmation.action.service === "shop";
      setMessages((m) => [...m, { role: "user", content: isShop ? "Place the order." : "Yes, apply the fix." }]);
      try { applyResponse(await api.confirm(res.thread_id, true)); } catch { /* ignore */ }
    }
    return res;
  }

  // Wait for the Live Listen watcher to finish processing the last batch so the
  // cart is fully built before we check out.
  async function settleAnalyze() {
    for (let i = 0; i < 18; i++) {
      if (pendingBufferRef.current.length === 0 && !analyzeInFlightRef.current) {
        await wait(700);
        if (pendingBufferRef.current.length === 0 && !analyzeInFlightRef.current) return;
      }
      await wait(800);
    }
  }

  // Auto-run the POS checkout end-to-end (View Together → payment → signature).
  async function autoCheckout(acctId: string | null) {
    const tid = threadIdRef.current;
    if (!tid) return;
    const start = await api.checkoutStart(tid, acctId);
    handleCheckoutView(start);
    const cid = start.checkout.id;
    await wait(2800);
    if (demoAbortRef.current) return;
    handleCheckoutView(await api.checkoutAdvance(cid));
    await wait(2200);
    if (demoAbortRef.current) return;
    handleCheckoutView(await api.checkoutPay(cid, "card_on_file", "pickup"));
    await wait(2200);
    if (demoAbortRef.current) return;
    handleCheckoutView(await api.checkoutSign(cid, DEMO_SIGNATURE, "sms"));
  }

  // The end-to-end demo runner: check in → assist → conversation → completion
  // (checkout for sales, resolution for service) → visit summary + Playbook grade.
  async function runDemo(demo: Demo, mode: "chat" | "listen") {
    if (demoRunning || busy) return;
    reset();
    await wait(60);
    demoAbortRef.current = false;
    setDemoRunning(demo);
    const reasonLabel = VISIT_REASONS.find((r) => r.value === demo.checkIn.reason)?.label ?? demo.checkIn.reason;
    try {
      setMessages((m) => [...m, {
        role: "assistant",
        content: `🎬 Demo — ${demo.title} · ${mode === "chat" ? "Chat" : "Live Listen"}\nChecking ${demo.checkIn.customer_name} into the store (${reasonLabel})…`,
      }]);
      scrollDown();

      // 1. Check the customer into the store.
      const ci = await api.checkIn(demo.checkIn);
      if (demoAbortRef.current) return;

      // 2. Start a Live Listen session so the visit gets a graded, summarized
      //    recap at the end. The "LIVE" strip only shows in Live Listen mode —
      //    Chat mode runs the session silently (just to grade the transcript).
      const res = await api.listenStart(ci.entry.id, threadIdRef.current, "demo");
      activateListenSession(res, mode === "listen");
      try {
        const acct = await api.shopAccount(demo.checkIn.account_id ?? null);
        if (acct.elements?.length) setMessages((m) => [...m, { role: "assistant", a2ui: acct.elements }]);
      } catch { /* account card best-effort */ }
      await wait(900);

      // 3. Play the scenario.
      if (mode === "listen") {
        await playScriptAsync(demo.conversation); // watcher builds cart / surfaces suggestions
        await settleAnalyze();
      } else {
        // Chat: silently record the conversation for grading (no watcher, no
        // strip), then drive the assistant with explicit rep turns.
        const utterances = demo.conversation.map((s) => ({ speaker: s.speaker, text: s.text }));
        try { await api.listenAnalyze(res.session.id, utterances, true); } catch { /* transcript best-effort */ }
        for (const turn of demo.chatTurns) {
          if (demoAbortRef.current) return;
          await wait(2400);   // pause so the previous reply is readable before the rep "types" the next
          await runnerSend(turn);
          await wait(2600);   // let the reply + any cart change settle
        }
      }
      if (demoAbortRef.current) return;

      // 4. Complete the visit.
      if (demo.kind === "sales") {
        await wait(900);
        await autoCheckout(demo.checkIn.account_id ?? null);
      } else if (mode === "listen" && demo.resolveTurn) {
        await runnerSend(demo.resolveTurn);
      }
      if (demoAbortRef.current) return;

      // 5. End the visit → Playbook grade + visit summary. (Chat mode had no
      //    visible Live Listen strip, so use a neutral header.)
      await wait(1600);
      await stopListen(mode === "chat" ? "📋 Demo complete — visit graded against the Playbook." : undefined);
    } catch (e) {
      setMessages((m) => [...m, { role: "assistant", content: `⚠️ Demo error: ${e}` }]);
    } finally {
      setDemoRunning(null);
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
    threadIdRef.current = res.thread_id;
    if (res.status === "needs_confirmation") {
      setPending(res.confirmation);
    } else {
      setPending(null);
      setMessages((m) => [
        ...m,
        { role: "assistant", content: res.assistant_message ?? "", card: res.card, a2ui: res.a2ui ?? undefined },
      ]);
    }
    // Shopping: reflect the updated cart in the top drawer, flashing it open so
    // the rep sees the change, then auto-collapsing to keep the chat in focus.
    if (res.cart) {
      setCart(res.cart);
      if (res.cart.items.length > 0) flashCart();
    }
    scrollDown();
  }

  // Reveal the cart drawer briefly on a change, then collapse it so the chat
  // stays readable. The compact cart bar remains visible when collapsed, and a
  // manual toggle (below) cancels the pending auto-collapse.
  function flashCart() {
    setCartOpen(true);
    if (cartFlashRef.current) window.clearTimeout(cartFlashRef.current);
    cartFlashRef.current = window.setTimeout(() => {
      cartFlashRef.current = null;
      setCartOpen(false);
    }, 2800);
  }

  // ── Guided POS checkout ────────────────────────────────────────────────────
  // The cart's "Review & place order" opens the wizard (View Together → payment
  // → signature). It's a server-side session so it can also be driven from the
  // customer's phone; we poll while it's open so the rep screen follows along.
  function handleCheckoutView(view: CheckoutView) {
    if (view.checkout.step === "complete") {
      const conf = view.element.type === "order_confirmation" ? view.element : view.order ?? null;
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          content: `✅ Order ${view.checkout.order_id ?? ""} placed — signed & paid.`.trim(),
          a2ui: conf ? [conf] : undefined,
        },
      ]);
      checkoutRef.current = null;
      setCheckout(null);
      // The order clears the cart server-side; reflect that in the drawer.
      setCart((prev) => (prev ? { ...prev, items: [], monthly_total: 0, onetime_total: 0, recommendations: [] } : prev));
      setCartOpen(false);
    } else {
      checkoutRef.current = view;
      setCheckout(view);
    }
    scrollDown();
  }

  async function startCheckout() {
    if (!threadId || checkoutBusy || checkout) return;
    setCheckoutBusy(true);
    try {
      handleCheckoutView(await api.checkoutStart(threadId, accountId));
    } catch (e) {
      setMessages((m) => [...m, { role: "assistant", content: `⚠️ Couldn't start checkout (${e}).` }]);
    } finally {
      setCheckoutBusy(false);
    }
  }

  const checkoutHandlers: CheckoutHandlers = {
    variant: "rep",
    busy: checkoutBusy,
    onAdvance: async () => {
      const c = checkoutRef.current;
      if (!c) return;
      setCheckoutBusy(true);
      try { handleCheckoutView(await api.checkoutAdvance(c.checkout.id)); }
      finally { setCheckoutBusy(false); }
    },
    onPay: async (method, fulfillment) => {
      const c = checkoutRef.current;
      if (!c) return;
      setCheckoutBusy(true);
      try { handleCheckoutView(await api.checkoutPay(c.checkout.id, method, fulfillment)); }
      finally { setCheckoutBusy(false); }
    },
    onSign: async (signature, receiptChannel) => {
      const c = checkoutRef.current;
      if (!c) return;
      setCheckoutBusy(true);
      try { handleCheckoutView(await api.checkoutSign(c.checkout.id, signature, receiptChannel)); }
      finally { setCheckoutBusy(false); }
    },
    onSendToPhone: async (channel) => {
      const c = checkoutRef.current;
      if (!c) return null;
      try {
        const result = await api.checkoutSendToPhone(c.checkout.id, channel, window.location.origin);
        // Reflect the handoff (sent_channel) without leaving the current step.
        const fresh = await api.checkoutGet(c.checkout.id);
        if (checkoutRef.current?.checkout.id === c.checkout.id && fresh.checkout.step !== "complete") {
          checkoutRef.current = fresh;
          setCheckout(fresh);
        }
        return result;
      } catch {
        return null;
      }
    },
  };

  // Follow the customer's phone: poll while a checkout is open and un-signed.
  useEffect(() => {
    if (!checkout || checkout.checkout.step === "complete") return;
    const id = checkout.checkout.id;
    const timer = window.setInterval(async () => {
      try {
        const v = await api.checkoutGet(id);
        const cur = checkoutRef.current;
        if (!cur || cur.checkout.id !== id) return;
        if (v.checkout.step !== cur.checkout.step || v.checkout.sent_channel !== cur.checkout.sent_channel) {
          handleCheckoutView(v);
        }
      } catch {
        /* keep polling */
      }
    }, 2500);
    return () => window.clearInterval(timer);
  }, [checkout?.checkout.id, checkout?.checkout.step]); // eslint-disable-line react-hooks/exhaustive-deps

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

  // Wire up an active Live Listen session (state + refs + elapsed timer) from a
  // listenStart response. Shared by the setup panel and the demo runner.
  // `showStrip=false` runs the session silently under the hood (chat-mode demos
  // use a session only to grade the transcript — the "LIVE" dock stays hidden).
  function activateListenSession(res: { thread_id: string; entities: Record<string, string>; session: ListenSession }, showStrip = true) {
    if (listening) recognitionRef.current?.stop(); // composer dictation yields to Live Listen
    setThreadId(res.thread_id);
    threadIdRef.current = res.thread_id;
    listenEntitiesRef.current = res.entities;
    listenSessionRef.current = res.session;
    if (showStrip) setListenSession(res.session);
    setListenSetupOpen(false);
    setLiveUtterances([]);
    setListenInterim("");
    pendingBufferRef.current = [];
    lastAnalyzeRef.current = 0;
    listenActiveRef.current = true;
    listenStartedAtRef.current = Date.now();
    setListenElapsed(0);
    if (elapsedTimerRef.current) window.clearInterval(elapsedTimerRef.current);
    if (showStrip) {
      elapsedTimerRef.current = window.setInterval(() => {
        setListenElapsed(Math.floor((Date.now() - listenStartedAtRef.current) / 1000));
      }, 1000);
    }
  }

  async function startListen() {
    const entry = listenQueue.find((e) => e.id === listenEntryId);
    if (!entry || busy) return;
    setBusy(true);
    try {
      const res = await api.listenStart(entry.id, threadIdRef.current, listenMode);
      activateListenSession(res);
      const label = res.session.customer_name ?? res.session.customer_phone ?? "the customer";
      const reasonLabel = VISIT_REASONS.find((r) => r.value === res.session.reason)?.label ?? res.session.reason;
      const oppLine = res.opportunities.length
        ? ` 💡 Opportunities to position: ${res.opportunities.join(", ")}.`
        : "";
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          content: `🎧 Live Listen started — assisting ${label} (${reasonLabel}). I'll flag anything I can help with.${oppLine}`,
        },
      ]);
      if (listenMode === "demo") playDemoScript(res.session.reason);
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

  function playDemoScript(reason?: string) {
    // A shopping visit (upgrade / new service) plays the cart-building script,
    // so the top cart drawer builds itself live; other visits play the
    // issue-triage script.
    const script = reason === "upgrade" || reason === "new_service" ? SHOPPING_DEMO_SCRIPT : DEMO_SCRIPT;
    void playScriptAsync(script);
  }

  // Play a scripted conversation into the live transcript, resolving once the
  // last line is spoken (or the session is torn down). Each line's delay is
  // stretched by DEMO_LINE_PACE so a viewer can follow the conversation — this
  // only paces the scripted playback, never the real system/API calls.
  function playScriptAsync(script: { speaker: "Customer" | "Rep"; text: string; delayMs: number }[]): Promise<void> {
    return new Promise((resolve) => {
      let i = 0;
      const step = () => {
        if (!listenActiveRef.current || i >= script.length) { resolve(); return; }
        const line = script[i++];
        demoTimerRef.current = window.setTimeout(() => {
          if (!listenActiveRef.current) { resolve(); return; }
          pushUtterance({ speaker: line.speaker, text: line.text });
          step();
        }, Math.round(line.delayMs * DEMO_LINE_PACE));
      };
      step();
    });
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
      if (res.entities.account_id) setAccountId(res.entities.account_id);
      if (res.suggestions.length) {
        setMessages((m) => [
          ...m,
          ...res.suggestions.map((s): Msg => ({ role: "assistant", a2ui: [{ type: "live_suggestion", ...s }] })),
        ]);
        scrollDown();
      }
      // Live Listen heard a cart change — flash the drawer + note it inline.
      if (res.cart) {
        setCart(res.cart.cart);
        if (res.cart.cart.items.length > 0) flashCart();
        if (res.cart.notes.length) {
          setMessages((m) => [...m, { role: "assistant", content: `🛒 Cart updated from the conversation — ${res.cart!.notes.join(", ")}.` }]);
          scrollDown();
        }
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

  async function stopListen(headerOverride?: string) {
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
      const recapMsg: Msg = {
        role: "assistant",
        content: headerOverride
          ?? `🎧 Live Listen ended — ${res.recap.utterances} utterances, ${res.recap.suggestions} suggestions, ${res.recap.duration_label}.`,
      };
      // Attach the Playbook grade (stars) and the generated visit summary so
      // the score card, summary card, and "Send visit summary" button render
      // inline in the thread.
      if (res.recap.grade) recapMsg.grade = res.recap.grade;
      if (res.recap.summary) {
        recapMsg.visit = {
          sessionId: session.id,
          customerName: session.customer_name,
          summary: res.recap.summary,
        };
      }
      setMessages((m) => [...m, recapMsg]);
      scrollDown();
    } catch (e) {
      console.warn("Live Listen stop failed", e);
    }
  }

  // Rep-triggered: email the visit summary to Live Listen subscribers.
  async function sendVisitSummary(sessionId: string) {
    setSummarySends((s) => ({ ...s, [sessionId]: { sending: true, result: null } }));
    try {
      const result = await api.listenSendSummary(sessionId);
      setSummarySends((s) => ({ ...s, [sessionId]: { sending: false, result } }));
    } catch (e) {
      setSummarySends((s) => ({
        ...s,
        [sessionId]: { sending: false, result: { summary: {} as VisitSummary, sent: 0, recipients: [], error: String(e) } },
      }));
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

  async function send(text: string, entities?: Record<string, string>): Promise<ChatResponse | null> {
    if (!text.trim() || busy) return null;
    setMessages((m) => [...m, { role: "user", content: text }]);
    setInput("");
    setBusy(true);
    scrollDown();
    try {
      const res = await api.chat(text, threadIdRef.current, "rep.demo", entities);
      applyResponse(res);
      return res;
    } catch (e) {
      setMessages((m) => [...m, { role: "assistant", content: `⚠️ ${e}` }]);
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function decide(approved: boolean) {
    if (!threadId || !pending) return;
    setBusy(true);
    const isOrder = pending.action.service === "shop";
    const label = approved
      ? (isOrder ? "Place the order." : "Yes, apply the fix")
      : (isOrder ? "Not yet." : "No, don't make changes");
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
    setCart(null);
    setCartOpen(false);
    if (cartFlashRef.current) { window.clearTimeout(cartFlashRef.current); cartFlashRef.current = null; }
    checkoutRef.current = null;
    setCheckout(null);
    setCheckoutBusy(false);
    setAccountId(null);
    threadIdRef.current = null;
    demoAbortRef.current = true;   // abort any in-flight demo
    setDemoRunning(null);
  }

  // Execute a quick-action dispatched from the global drawer (App owns the
  // drawer; ChatWidget owns the handlers). The nonce ref-guard makes this fire
  // exactly once per dispatch — not on StrictMode's double-invoke or a remount.
  useEffect(() => {
    if (chatActionNonce === lastActionNonce.current) return;
    lastActionNonce.current = chatActionNonce;
    if (!chatAction) return;
    switch (chatAction.kind) {
      case "prompt": send(chatAction.value); break;
      case "lookup": showLookup(chatAction.value); break;
      case "coaching": showCoaching(); break;
      case "checkin": setCiError(null); setCheckInOpen(true); break;
      case "assist": assistCustomer(chatAction.entry); break;
      case "demos": showDemos(); break;
      case "scan_barcode": setScanner("barcode"); break;
      case "scan_bill": setScanner("bill"); break;
      case "reset": reset(); break;
    }
    onChatActionDone();
  }, [chatActionNonce]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="chat-shell">
      <div className="chat-main">
        {cart && cart.items.length > 0 && (
          <CartDrawer
            cart={cart}
            open={cartOpen}
            onToggle={() => {
              // A manual toggle wins — cancel any pending auto-collapse.
              if (cartFlashRef.current) { window.clearTimeout(cartFlashRef.current); cartFlashRef.current = null; }
              setCartOpen((o) => !o);
            }}
            onCheckout={startCheckout}
            onRecommend={(prompt) => send(prompt)}
            busy={busy || checkoutBusy || checkout !== null}
          />
        )}
        <div className="messages" ref={scrollRef}>
          {messages.length === 0 && (
            <div className="empty">
              <span className="empty-wave">👋</span>
              <h2>{timeGreeting()}! I'm here to help.</h2>
              <p className="muted">
                Stuck on an activation, a blocked order, a promo, or a billing question?
                Just describe it in your own words — or tap <strong>+</strong> for the tray:
                scan a barcode or a bill, check a customer in, and more.
              </p>
              <div className="empty-demo">
                <button className="empty-demo-cta" disabled={busy || !!demoRunning} onClick={showDemos}>
                  <span className="empty-demo-icon">🎬</span>
                  <span className="empty-demo-main">
                    <span className="empty-demo-title">Run a demo</span>
                    <span className="empty-demo-sub">Watch a full sales or service visit play out — chat or Live Listen</span>
                  </span>
                  <span className="empty-demo-go">›</span>
                </button>
              </div>

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
                <A2UIRenderer elements={m.a2ui} onAction={a2uiAction} onOpenArticle={openArticle} onAssist={assistFromQueue} onCoach={onCoach} onWalkthrough={onWalkthrough} actionsDisabled={busy} />
              )}
              {m.grade && <PlaybookScoreCard grade={m.grade} />}
              {m.visit && (
                <VisitSummaryCard
                  visit={m.visit}
                  send={summarySends[m.visit.sessionId]}
                  onSend={() => sendVisitSummary(m.visit!.sessionId)}
                />
              )}
              {m.coaching && <CoachingCard result={m.coaching} />}
              {m.demos && <DemoCard onRun={runDemo} disabled={busy || !!demoRunning} />}
              {m.walkthrough && <WalkthroughCard walkthrough={m.walkthrough} />}
              {m.product && <BarcodeProductCard product={m.product} onAdd={(p) => send(p)} disabled={busy} />}
              {m.scanBill && <BillAnalysisCard initial={m.scanBill} onBuild={(p) => send(p)} disabled={busy} />}
            </div>
          ))}

          {checkout && (
            <div className="bubble assistant">
              <CheckoutFlow view={checkout} handlers={checkoutHandlers} />
            </div>
          )}

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
                <div className="checkin-row">
                  <div className="checkin-field">
                    <label htmlFor="ci-account">Account # <span className="checkin-opt">(optional)</span></label>
                    <input
                      id="ci-account"
                      value={ciAccount}
                      placeholder="AC-3002"
                      onChange={(e) => setCiAccount(e.target.value)}
                    />
                  </div>
                  <div className="checkin-field">
                    <label htmlFor="ci-order">Order # <span className="checkin-opt">(optional)</span></label>
                    <input
                      id="ci-order"
                      value={ciOrder}
                      placeholder="ACT-1002"
                      onChange={(e) => setCiOrder(e.target.value)}
                    />
                  </div>
                </div>
                <p className="checkin-hint">Name or phone number — at least one is required. Account/order let the assistant skip re-asking.</p>
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

          {pending && (() => {
            const isOrder = pending.action.service === "shop";
            return (
              <div className="bubble assistant">
                <div className="confirm-card">
                  <div className="confirm-head">{isOrder ? "🛒 Confirm the order" : "⚠️ Confirm before I make a change"}</div>
                  <div className="confirm-prompt">{pending.prompt}</div>
                  <div className="confirm-meta">
                    <code>{pending.action.service}/{pending.action.operation}</code>
                  </div>
                  <div className="confirm-actions">
                    <button className="btn primary" disabled={busy} onClick={() => decide(true)}>
                      {isOrder ? "Place order & take payment" : "Approve & apply"}
                    </button>
                    <button className="btn ghost" disabled={busy} onClick={() => decide(false)}>
                      {isOrder ? "Not yet" : "Decline"}
                    </button>
                  </div>
                </div>
              </div>
            );
          })()}

          {busy && <div className="bubble assistant"><div className="typing"><span /><span /><span /></div></div>}
        </div>

        {/* Live-transcript window + composer pinned together above the input. */}
        <div className="composer-dock">
        {demoRunning && (
          <div className="demo-banner">
            <span className="demo-banner-dot" />
            <span className="demo-banner-text">Demo running · <b>{demoRunning.title}</b> — sit back and watch.</span>
            <button
              type="button"
              className="btn ghost small"
              onClick={() => { demoAbortRef.current = true; setDemoRunning(null); stopListen(); }}
            >
              Stop demo
            </button>
          </div>
        )}
        {/* Fixed live-transcript window, full width, pinned above the input. */}
        {listenSession && (
          <div className="listen-dock">
            <div className="listen-strip-head">
              <span className="listen-live-dot" />
              <span className="listen-strip-label">LIVE</span>
              <span className="listen-strip-cust">
                {listenSession.customer_name ?? listenSession.customer_phone ?? "Customer"}
              </span>
              <span className="listen-elapsed">{formatElapsed(listenElapsed)}</span>
              <button type="button" className="btn ghost small" onClick={() => stopListen()}>
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

        <form
          className="composer"
          onSubmit={(e) => {
            e.preventDefault();
            send(input);
          }}
        >
          <div className="composer-box">
            <textarea
              ref={inputRef}
              className="composer-input"
              rows={1}
              value={input}
              disabled={busy || !!demoRunning}
              placeholder={demoRunning ? "Demo running…" : listening ? "Listening…" : "Describe the order or service issue…"}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={onComposerKeyDown}
            />
            <div className="composer-actions">
              <button
                type="button"
                className="composer-plus"
                onClick={onOpenMenu}
                title="Menu"
                aria-label="Open menu"
              >
                +
              </button>
              <div className="composer-actions-right">
                {speechSupported && (
                  <button
                    type="button"
                    className={`composer-round mic${listening ? " listening" : ""}`}
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
                  className={`composer-round listen${listenSession ? " live" : ""}`}
                  onClick={openListenSetup}
                  disabled={busy && !listenSession}
                  title={listenSession ? "Live Listen is on — click to stop" : "Live Listen"}
                  aria-label="Live Listen"
                >
                  🎧
                </button>
                <button
                  className="composer-send"
                  disabled={busy || !!demoRunning || !input.trim()}
                  type="submit"
                  aria-label="Send"
                  title="Send"
                >
                  ↑
                </button>
              </div>
            </div>
          </div>
        </form>
        </div>
      </div>

      {scanner && (
        <Scanner
          mode={scanner}
          onClose={() => setScanner(null)}
          onBarcode={handleBarcode}
          onCapture={handleBillCapture}
        />
      )}
    </div>
  );
}

const CART_KIND_LABEL: Record<string, string> = {
  new_line: "New line",
  upgrade: "Upgrade",
  home_internet: "Home internet",
  perk: "Perk",
  accessory: "Accessory",
};

// The shopping cart, built through the chat — a collapsible drawer pinned to the
// top of the conversation that opens/closes and live-updates as the rep chats.
function CartDrawer({ cart, open, onToggle, onCheckout, onRecommend, busy }: {
  cart: Cart; open: boolean; onToggle: () => void; onCheckout: () => void;
  onRecommend: (prompt: string) => void; busy: boolean;
}) {
  const n = cart.items.length;
  const recs = cart.recommendations ?? [];
  return (
    <div className={`cart-drawer${open ? " open" : ""}`}>
      <button className="cart-bar" onClick={onToggle} aria-expanded={open} title={open ? "Collapse cart" : "Expand cart"}>
        <span className="cart-bar-icon">🛒</span>
        <span className="cart-bar-title">Cart</span>
        <span className="cart-bar-count">{n} item{n !== 1 ? "s" : ""}</span>
        <span className="cart-bar-total">${cart.monthly_total.toFixed(2)}/mo</span>
        <span className="cart-bar-chevron">{open ? "▾" : "▸"}</span>
      </button>
      {open && (
        <div className="cart-body">
          {cart.items.map((it) => {
            const isAddon = it.kind === "perk" || it.kind === "accessory";
            const title = isAddon ? (it.name ?? "Item") : (it.device ?? "Device TBD");
            return (
              <div key={it.item_id} className="cart-item">
                <span className={`cart-item-kind cart-item-kind--${it.kind}`}>{CART_KIND_LABEL[it.kind] ?? it.kind}</span>
                <div className="cart-item-main">
                  <div className="cart-item-device">
                    {title}
                    {it.line_id ? <span className="cart-item-line"> · {it.line_id}</span> : null}
                  </div>
                  <div className="cart-item-sub">
                    {it.kind === "perk" ? "Add-on · $10/mo"
                      : it.kind === "accessory" ? (it.blurb ?? "One-time")
                      : (
                        <>
                          {it.plan ?? "Plan TBD"}
                          {it.protection ? <span className="cart-item-prot"> · 🛡 {it.protection.name}</span> : null}
                          {it.promo ? <span className="cart-item-promo"> · {it.promo}</span> : null}
                          {it.trade_in ? <span className="cart-item-promo"> · trade-in −${it.trade_in.credit.toFixed(0)}</span> : null}
                        </>
                      )}
                  </div>
                </div>
                <span className="cart-item-price">
                  {it.kind === "accessory"
                    ? <>${it.onetime.toFixed(2)}</>
                    : <>${it.monthly.toFixed(2)}<span className="cart-item-per">/mo</span></>}
                </span>
              </div>
            );
          })}
          <div className="cart-footer">
            <span className="cart-footer-label">Monthly total</span>
            <span className="cart-footer-total">${cart.monthly_total.toFixed(2)}/mo</span>
          </div>
          {cart.onetime_total > 0 && (
            <div className="cart-footer cart-footer--sub">
              <span className="cart-footer-label">One-time items</span>
              <span className="cart-footer-sub">${cart.onetime_total.toFixed(2)}</span>
            </div>
          )}
          {recs.length > 0 && (
            <div className="cart-recs">
              {recs.map((r, i) => (
                <button
                  key={i}
                  className={`cart-rec cart-rec--${r.kind}`}
                  disabled={busy}
                  onClick={() => onRecommend(r.prompt)}
                  title={r.detail}
                >
                  <span className="cart-rec-icon">{r.kind === "protection" ? "🛡" : "🎁"}</span>
                  <span className="cart-rec-main">
                    <b>{r.label}</b>
                    <small>{r.detail}</small>
                  </span>
                  <span className="cart-rec-add">+ Add</span>
                </button>
              ))}
            </div>
          )}
          <div className="cart-actions">
            <button className="btn primary cart-checkout" disabled={busy} onClick={onCheckout}>
              Review &amp; place order
            </button>
          </div>
          <div className="cart-hint">Keep chatting to add, change, or remove items, then place the order.</div>
        </div>
      )}
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

function VisitSummaryCard({
  visit,
  send,
  onSend,
}: {
  visit: VisitRecap;
  send?: { sending: boolean; result: SendSummaryResult | null };
  onSend: () => void;
}) {
  const { summary, customerName } = visit;
  const result = send?.result;
  const sending = send?.sending ?? false;
  const sent = !!result && !result.error && (result.sent > 0 || result.previewed);

  let status = "";
  if (result?.error) status = `Couldn't send: ${result.error}`;
  else if (result?.sent) status = `Sent to ${result.sent} subscriber${result.sent === 1 ? "" : "s"}.`;
  else if (result?.warning) status = result.warning;

  return (
    <div className="visit-card">
      <div className="visit-head">
        <span className="visit-eyebrow">✉️ Visit summary</span>
        {customerName && <span className="visit-cust">{customerName}</span>}
      </div>
      <div className="visit-greeting">{summary.greeting}</div>
      <p className="visit-summary">{summary.summary}</p>
      {summary.steps_taken.length > 0 && (
        <ul className="visit-steps">
          {summary.steps_taken.map((s, i) => (
            <li key={i}>{s}</li>
          ))}
        </ul>
      )}
      {summary.closing && <p className="visit-closing">{summary.closing}</p>}
      <div className="visit-foot">
        <button className="btn primary small" onClick={onSend} disabled={sending || sent}>
          {sending ? "Sending…" : sent ? "Sent ✓" : "Send visit summary"}
        </button>
        {status && <span className="visit-status">{status}</span>}
      </div>
    </div>
  );
}

function PlaybookScoreCard({ grade }: { grade: PlaybookGrade }) {
  return (
    <div className="score-card">
      <div className="score-head">
        <span className="score-eyebrow">📋 Playbook score</span>
        <Stars value={grade.stars} />
      </div>
      <p className="score-headline">{grade.headline}</p>
      {grade.strengths.length > 0 && (
        <div className="score-block">
          <div className="score-label score-label--good">Did well</div>
          <ul className="score-list">
            {grade.strengths.map((s, i) => <li key={i}>{s}</li>)}
          </ul>
        </div>
      )}
      {grade.gaps.length > 0 && (
        <div className="score-block">
          <div className="score-label score-label--gap">To improve</div>
          <ul className="score-list">
            {grade.gaps.map((g, i) => <li key={i}>{g}</li>)}
          </ul>
        </div>
      )}
      <details className="score-details">
        <summary>Guideline breakdown</summary>
        <ul className="score-guidelines">
          {grade.per_guideline.map((p) => (
            <li key={p.guideline_id} className={p.met ? "met" : "unmet"}>
              <span className="score-check">{p.met ? "✓" : "✗"}</span>
              <span>
                <b>{p.guideline}</b>
                <span className="score-note"> — {p.note}</span>
              </span>
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
}

function CoachingCard({ result }: { result: CoachingResult }) {
  const { coaching, customer_name, stars, grade } = result;
  return (
    <div className="coach-card">
      <div className="coach-head">
        <span className="coach-eyebrow">🎯 Coaching · {customer_name}</span>
        <Stars value={stars} />
      </div>
      {grade?.headline && <p className="coach-headline">{grade.headline}</p>}
      <p className="coach-summary">{coaching.summary}</p>
      {coaching.what_went_well.length > 0 && (
        <div className="score-block">
          <div className="score-label score-label--good">What went well</div>
          <ul className="score-list">
            {coaching.what_went_well.map((s, i) => <li key={i}>{s}</li>)}
          </ul>
        </div>
      )}
      {coaching.improvements.length > 0 && (
        <div className="score-block">
          <div className="score-label score-label--gap">How to improve</div>
          <ul className="coach-improvements">
            {coaching.improvements.map((imp, i) => (
              <li key={i}>
                <b>{imp.guideline}</b> — {imp.suggestion}
              </li>
            ))}
          </ul>
        </div>
      )}
      {coaching.suggested_script && (
        <div className="coach-script">
          <div className="score-label">Try saying</div>
          <p className="coach-script-text">“{coaching.suggested_script}”</p>
        </div>
      )}
    </div>
  );
}

function WalkthroughCard({
  walkthrough,
}: {
  walkthrough: { title: string; steps: Walkthrough; gifUrl?: string | null; gifCaption?: string | null; videoUrl?: string | null };
}) {
  const { title, steps, gifUrl, gifCaption, videoUrl } = walkthrough;
  return (
    <div className="wt-card">
      <div className="wt-head">
        <span className="wt-eyebrow">📺 How to · {title}</span>
      </div>
      {steps.intro && <p className="wt-intro">{steps.intro}</p>}
      {steps.steps.length > 0 && (
        <ol className="wt-steps">
          {steps.steps.map((s, i) => (
            <li key={i} className="wt-step">
              <span className="wt-step-num">{i + 1}</span>
              <div className="wt-step-body">
                <div className="wt-step-title">{s.title}</div>
                <div className="wt-step-detail">{s.detail}</div>
                {s.tip && <div className="wt-step-tip">💡 {s.tip}</div>}
              </div>
            </li>
          ))}
        </ol>
      )}
      {gifUrl && (
        <div className="wt-media">
          <div className="wt-media-label">🎞 Quick demo</div>
          <img className="wt-gif" src={gifUrl} alt={`${title} demo`} />
          {gifCaption && <div className="wt-media-cap">{gifCaption}</div>}
        </div>
      )}
      {videoUrl && (
        <div className="wt-media">
          <div className="wt-media-label">▶ Training video</div>
          <video className="wt-video" src={videoUrl} controls preload="metadata" />
        </div>
      )}
    </div>
  );
}

// The "Run a demo" picker: sales personas + service scenarios, each launchable
// in Chat or Live Listen. The runner (runDemo) takes it from here.
function DemoCard({ onRun, disabled }: { onRun: (demo: Demo, mode: "chat" | "listen") => void; disabled: boolean }) {
  const groups: { label: string; icon: string; demos: Demo[] }[] = [
    { label: "Sales", icon: "🛍", demos: SALES_DEMOS },
    { label: "Service", icon: "🛠", demos: SERVICE_DEMOS },
  ];
  return (
    <div className="a2ui-card demo-card">
      <div className="a2ui-card-head">
        <span className="a2ui-card-eyebrow">🎬 Demos</span>
        <h4 className="a2ui-card-title">Run an end-to-end visit</h4>
        <p className="a2ui-card-sub">
          Pick a scenario, then <b>Chat</b> or <b>Live Listen</b>. Each plays out check-in → assist →
          completion → visit summary &amp; Playbook grade.
        </p>
      </div>
      {groups.map((g) => (
        <div key={g.label} className="demo-group">
          <div className="demo-group-label">{g.icon} {g.label}</div>
          <div className="demo-list">
            {g.demos.map((d) => (
              <div key={d.id} className="demo-item">
                <span className="demo-item-icon">{d.icon}</span>
                <div className="demo-item-main">
                  <div className="demo-item-title">{d.title}</div>
                  <div className="demo-item-persona">{d.persona}</div>
                  <div className="demo-item-blurb">{d.blurb}</div>
                  <div className="demo-item-actions">
                    <button className="btn small" disabled={disabled} onClick={() => onRun(d, "chat")}>💬 Chat</button>
                    <button className="btn ghost small" disabled={disabled} onClick={() => onRun(d, "listen")}>🎧 Live Listen</button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Scan Barcode result — a catalog product matched from a UPC ──────────────
function BarcodeProductCard({ product, onAdd, disabled }: {
  product: BarcodeProduct; onAdd: (prompt: string) => void; disabled: boolean;
}) {
  const isDevice = product.kind === "device";
  return (
    <div className="scan-card">
      <div className="scan-card-head">
        <span className="scan-card-eyebrow">🔎 Scanned product</span>
        <span className="scan-card-upc">UPC {product.upc}</span>
      </div>
      <div className="prodcard-body">
        <div className="prodcard-icon">{isDevice ? "📱" : "🎧"}</div>
        <div className="prodcard-main">
          <div className="prodcard-name">{product.name}</div>
          <div className="prodcard-sub">
            {product.brand ? `${product.brand} · ` : ""}
            {product.kind === "device" ? "Device" : "Accessory"}
            {product.blurb ? ` · ${product.blurb}` : ""}
          </div>
        </div>
        <div className="prodcard-price">
          {isDevice && product.monthly != null
            ? <>${product.monthly.toFixed(2)}<span className="prodcard-per">/mo</span></>
            : <>${product.price.toFixed(2)}</>}
          {isDevice && <div className="prodcard-retail">${product.price.toFixed(0)} retail</div>}
        </div>
      </div>
      <div className="scan-card-actions">
        <button className="btn primary small" disabled={disabled} onClick={() => onAdd(`Add ${product.name} to the cart`)}>
          Add to cart
        </button>
        <button className="btn ghost small" disabled={disabled} onClick={() => onAdd(`Tell me about the ${product.name}`)}>
          Ask about it
        </button>
      </div>
    </div>
  );
}

// Common 3rd-party services a customer might pay for directly, offered as
// quick-add chips so the rep can fold them into the switch quote as $10 perks.
const STREAMING_PRESETS: { name: string; monthly: number }[] = [
  { name: "Netflix", monthly: 22.99 },
  { name: "Disney+ Bundle", monthly: 19.99 },
  { name: "Max", monthly: 16.99 },
  { name: "YouTube TV", monthly: 82.99 },
  { name: "Apple One", monthly: 19.95 },
  { name: "Peacock", monthly: 13.99 },
  { name: "Spotify", monthly: 11.99 },
];

// ── Scan Bill result — competitor bill + our matched switch quote ───────────
function BillAnalysisCard({ initial, onBuild, disabled }: {
  initial: ScanBillResult; onBuild: (prompt: string) => void; disabled: boolean;
}) {
  const bill = initial.bill;
  const [quote, setQuote] = useState(initial.quote);
  const [streaming, setStreaming] = useState<Record<string, number>>({});
  const [homeOn, setHomeOn] = useState(false);
  const [homePrice, setHomePrice] = useState(70);
  const [busy, setBusy] = useState(false);

  const onBill = new Set(bill.streaming.map((s) => s.name.toLowerCase()));
  const presets = STREAMING_PRESETS.filter((p) => !onBill.has(p.name.toLowerCase()));

  async function recompute(nextStreaming: Record<string, number>, nextHomeOn: boolean, nextHomePrice: number) {
    const extras: SwitchExtras = {
      streaming: Object.entries(nextStreaming).map(([name, monthly]) => ({ name, monthly })),
      home_internet: !bill.home_internet && nextHomeOn ? { name: "Current provider", monthly: nextHomePrice } : null,
    };
    setBusy(true);
    try {
      const res = await api.switchQuote(bill, extras);
      setQuote(res.quote);
    } catch { /* keep the previous quote on error */ }
    finally { setBusy(false); }
  }

  function toggleStreaming(p: { name: string; monthly: number }) {
    setStreaming((prev) => {
      const next = { ...prev };
      if (next[p.name] != null) delete next[p.name]; else next[p.name] = p.monthly;
      recompute(next, homeOn, homePrice);
      return next;
    });
  }
  function toggleHome() {
    const next = !homeOn;
    setHomeOn(next);
    recompute(streaming, next, homePrice);
  }

  const win = quote.monthly_savings > 0;
  const buildPrompt = `Set up ${quote.our_plan.line_count} lines on ${quote.our_plan.name}`
    + quote.perks.map((p) => `, add the ${p.name} perk`).join("")
    + (quote.home_internet ? `, add ${quote.home_internet.name}` : "");

  return (
    <div className="scan-card billcard">
      <div className="scan-card-head">
        <span className="scan-card-eyebrow">🧾 Competitor bill — switch analysis</span>
        {bill.confidence < 0.5 && <span className="billcard-lowconf" title="Low OCR confidence">estimated</span>}
      </div>

      {/* Savings headline */}
      <div className={`billcard-hero${win ? " win" : ""}`}>
        <div className="billcard-hero-figs">
          <div className="billcard-hero-save">
            {win ? "−" : "+"}${Math.abs(quote.monthly_savings).toFixed(2)}<span className="billcard-hero-per">/mo</span>
          </div>
          <div className="billcard-hero-annual">
            {win ? `~$${Math.round(quote.annual_savings).toLocaleString()}/yr saved` : `~$${Math.round(Math.abs(quote.annual_savings)).toLocaleString()}/yr more`}
          </div>
        </div>
        <div className="billcard-hero-compare">
          <div><span className="billcard-compare-lbl">Pays today</span><span className="billcard-compare-val">${quote.their_total_monthly.toFixed(2)}/mo</span></div>
          <div className="billcard-compare-arrow">→</div>
          <div><span className="billcard-compare-lbl">With us</span><span className="billcard-compare-val strong">${quote.our_total_monthly.toFixed(2)}/mo</span></div>
        </div>
      </div>

      {/* Their current bill */}
      <div className="billcard-section">
        <div className="billcard-section-title">Their bill · {bill.carrier}</div>
        <div className="billcard-theirs">
          <div className="billcard-row"><span>{bill.plan_name} · {bill.line_count} line{bill.line_count !== 1 ? "s" : ""}</span><span>${bill.wireless_monthly.toFixed(2)}</span></div>
          {bill.streaming.map((s) => (
            <div className="billcard-row" key={s.name}><span>{s.name}</span><span>${s.monthly.toFixed(2)}</span></div>
          ))}
          {bill.home_internet && (
            <div className="billcard-row"><span>{bill.home_internet.name}</span><span>${bill.home_internet.monthly.toFixed(2)}</span></div>
          )}
          <div className="billcard-row billcard-row--total"><span>Total</span><span>${bill.total_monthly.toFixed(2)}/mo</span></div>
        </div>
      </div>

      {/* Our matched quote */}
      <div className="billcard-section">
        <div className="billcard-section-title">Our matching quote{busy && <span className="billcard-recalc"> · recalculating…</span>}</div>
        <div className="billcard-ours">
          {quote.line_items.map((li, idx) => (
            <div className="billcard-row" key={idx}>
              <span className="billcard-li-main">{li.label}<span className="billcard-li-sub">{li.sub}</span></span>
              <span>${li.amount.toFixed(2)}</span>
            </div>
          ))}
          <div className="billcard-row billcard-row--total"><span>Total</span><span>${quote.our_total_monthly.toFixed(2)}/mo</span></div>
        </div>
      </div>

      {/* Prompt for additional 3rd-party services */}
      {(presets.length > 0 || !bill.home_internet) && (
        <div className="billcard-section billcard-extras">
          <div className="billcard-section-title">Paying anyone else directly?</div>
          <div className="billcard-extras-hint">Add what they pay 3rd parties — bundling it as a perk usually saves more.</div>
          {presets.length > 0 && (
            <div className="billcard-chips">
              {presets.map((p) => (
                <button
                  key={p.name}
                  className={`billcard-chip${streaming[p.name] != null ? " on" : ""}`}
                  disabled={disabled || busy}
                  onClick={() => toggleStreaming(p)}
                >
                  {streaming[p.name] != null ? "✓ " : "+ "}{p.name}
                  <span className="billcard-chip-price">${p.monthly.toFixed(2)}</span>
                </button>
              ))}
            </div>
          )}
          {!bill.home_internet && (
            <label className={`billcard-home${homeOn ? " on" : ""}`}>
              <input type="checkbox" checked={homeOn} disabled={disabled || busy} onChange={toggleHome} />
              <span>Has home internet elsewhere</span>
              {homeOn && (
                <span className="billcard-home-price">
                  $<input
                    type="number" className="billcard-home-input" value={homePrice} min={0}
                    onChange={(e) => { const v = Number(e.target.value) || 0; setHomePrice(v); }}
                    onBlur={() => recompute(streaming, homeOn, homePrice)}
                  />/mo
                </span>
              )}
            </label>
          )}
        </div>
      )}

      <div className="billcard-summary">{quote.summary}</div>
      <div className="scan-card-actions">
        <button className="btn primary small" disabled={disabled} onClick={() => onBuild(buildPrompt)}>
          Build this quote in the cart
        </button>
      </div>
    </div>
  );
}
