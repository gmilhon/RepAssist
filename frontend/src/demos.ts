// Curated end-to-end demo scenarios surfaced by the "Run a demo" card. Each can
// be experienced two ways — Chat (the rep drives the assistant by typing) or
// Live Listen (a simulated spoken conversation the assistant listens in on) —
// and runs the full journey: check-in → assist → conversation → completion
// (checkout for sales, resolution for service) → visit summary + Playbook grade.
//
// Scenarios reuse real demo accounts/orders (mock_services/data.py) so the
// resolvers and account context behave correctly.

export interface DemoStep {
  speaker: "Customer" | "Rep";
  text: string;
  delayMs: number;
}

export interface Demo {
  id: string;
  kind: "sales" | "service";
  icon: string;
  title: string;
  persona: string; // short "who + situation" line
  blurb: string;
  checkIn: {
    customer_name: string;
    customer_phone: string;
    reason: string; // VisitReason value
    account_id?: string;
    order_id?: string;
  };
  // Spoken customer↔rep conversation: played in Live Listen mode, and recorded
  // as the gradeable transcript in Chat mode.
  conversation: DemoStep[];
  // Rep→assistant chat messages for Chat mode (build the cart / raise the issue).
  chatTurns: string[];
  // Service, Live Listen mode only: the definitive resolution turn the rep sends
  // after the conversation surfaces the issue (Chat mode resolves via chatTurns).
  resolveTurn?: string;
}

const D = (speaker: "Customer" | "Rep", text: string, delayMs = 3200): DemoStep => ({ speaker, text, delayMs });

export const DEMOS: Demo[] = [
  // ─────────────────────────── SALES ───────────────────────────
  {
    id: "sales-family-upgrade",
    kind: "sales",
    icon: "👨‍👩‍👧",
    title: "Family upgrade + trade-in",
    persona: "J. Rivera · loyal customer, 41-mo tenure",
    blurb: "Trades in an old iPhone for a Pixel 10 with protection, adds a line for their daughter, a streaming perk, and a case.",
    checkIn: { customer_name: "J. Rivera", customer_phone: "(555) 010-3031", reason: "upgrade", account_id: "AC-3003" },
    conversation: [
      D("Rep", "Welcome back, Ms. Rivera! What can I set you up with today?", 2600),
      D("Customer", "I'd love to trade in my old iPhone for the new iPhone 17 Pro on Unlimited Ultimate.", 3800),
      D("Rep", "Perfect — that trade-in credit makes it a great deal.", 2800),
      D("Customer", "Actually, hold on — let me go with the Pixel 10 instead.", 3400),
      D("Customer", "And add the protection plan on that Pixel — I always crack my screen.", 3600),
      D("Rep", "Smart call — that's covered now.", 2400),
      D("Customer", "Can I add a new line for my daughter? She'd like the Galaxy S26 on Unlimited Ultimate.", 4000),
      D("Customer", "Oh, and put Netflix on the account, and grab a case for the Pixel.", 3800),
      D("Rep", "Done — let's review it together and get you on your way.", 2600),
    ],
    chatTurns: [
      "Upgrade line 1 to a Pixel 10 with device protection, and trade in the old iPhone 15 Pro.",
      "Add a new line for her daughter with a Galaxy S26 on Unlimited Ultimate, add Netflix, and grab a protective case.",
    ],
  },
  {
    id: "sales-first-timer",
    kind: "sales",
    icon: "✨",
    title: "First-time customer",
    persona: "Sam Carter · brand-new to the carrier",
    blurb: "Sets up their very first line — an iPhone 17 on Unlimited Plus — with protection and a YouTube TV perk.",
    checkIn: { customer_name: "Sam Carter", customer_phone: "(555) 013-7788", reason: "new_service" },
    conversation: [
      D("Rep", "Welcome in! First time with us?", 2400),
      D("Customer", "Yeah — I'd like to start a brand-new line with an iPhone 17 on the Unlimited Plus plan.", 4000),
      D("Customer", "I'm pretty hard on phones, so add the protection plan too.", 3400),
      D("Rep", "Great choice — you're fully covered.", 2400),
      D("Customer", "Do you have any streaming deals? Add YouTube TV, and I'll take a fast charger.", 3800),
      D("Rep", "You got it — let's review everything together.", 2600),
    ],
    chatTurns: [
      "Set up a brand-new line with an iPhone 17 on Unlimited Plus, and add device protection.",
      "Add the YouTube TV perk and a fast charger.",
    ],
  },
  {
    id: "sales-watch-line",
    kind: "sales",
    icon: "⌚",
    title: "Add a watch line",
    persona: "K. Patel · existing customer adding a wearable",
    blurb: "Adds an Apple Watch on a Number Share line with wearable protection and a fast charger.",
    checkIn: { customer_name: "K. Patel", customer_phone: "(555) 010-5011", reason: "upgrade", account_id: "AC-5001" },
    conversation: [
      D("Rep", "Hi Mr. Patel — what are we adding today?", 2400),
      D("Customer", "I want to add an Apple Watch Series 10 on a Number Share line.", 3800),
      D("Customer", "Add the wearable protection on it, and a fast charger too.", 3600),
      D("Rep", "Perfect — let's review it together.", 2400),
    ],
    chatTurns: [
      "Add a new Apple Watch Series 10 line on Number Share with wearable protection.",
      "Add a fast charger accessory too.",
    ],
  },

  // ─────────────────────────── SERVICE ───────────────────────────
  {
    id: "service-activation",
    kind: "service",
    icon: "📶",
    title: "Stuck activation",
    persona: "Marcus Webb · new phone won't activate",
    blurb: "A new phone is stuck in activation (order ACT-1001). The assistant diagnoses it and re-provisions the line.",
    checkIn: { customer_name: "Marcus Webb", customer_phone: "(555) 010-1001", reason: "support", account_id: "AC-3001", order_id: "ACT-1001" },
    conversation: [
      D("Rep", "Hi Marcus — what's going on today?", 2400),
      D("Customer", "I picked up a new phone but it still says No Service — it's order ACT-1001 and it never finished activating.", 4200),
      D("Rep", "Sorry about that — let me pull up ACT-1001 and take a look.", 3000),
      D("Customer", "Thanks. The email said it went through, but it's been stuck since last night.", 3600),
      D("Rep", "I see it — the activation didn't complete on our side. Let me fix that.", 3000),
    ],
    chatTurns: [
      "My customer's new phone is stuck in activation — order ACT-1001 never finished provisioning. Can you fix it?",
    ],
    resolveTurn: "Let's fix the stuck activation on order ACT-1001.",
  },
  {
    id: "service-billing",
    kind: "service",
    icon: "💵",
    title: "Surprise first bill",
    persona: "Dana Cole · first bill higher than quoted",
    blurb: "The customer's first bill looks high. The assistant explains the proration from One Source of Truth.",
    checkIn: { customer_name: "Dana Cole", customer_phone: "(555) 010-3041", reason: "support", account_id: "AC-3004" },
    conversation: [
      D("Rep", "Hi Dana — how can I help?", 2400),
      D("Customer", "My first bill came in a lot higher than I was quoted when I signed up.", 3800),
      D("Rep", "A higher first bill usually comes from partial-month charges — let me pull it up.", 3200),
      D("Customer", "The total seemed way off from what they wrote down for me in the store.", 3600),
    ],
    chatTurns: [
      "The customer's first bill is higher than they were quoted — can you explain the prorated charges on their first invoice?",
    ],
    resolveTurn: "Explain why the first bill is higher than quoted — walk me through the prorated charges.",
  },
  {
    id: "service-missing-promo",
    kind: "service",
    icon: "🏷️",
    title: "Missing promo credit",
    persona: "J. Rivera · promised discount never applied",
    blurb: "A monthly promo credit never showed up on account AC-3003. The assistant re-applies it.",
    checkIn: { customer_name: "J. Rivera", customer_phone: "(555) 010-3031", reason: "support", account_id: "AC-3003" },
    conversation: [
      D("Rep", "Hi again — what can I help you with?", 2400),
      D("Customer", "I don't think I ever got the discount they promised — it's account AC-3003 and the monthly promo credit never applied.", 4400),
      D("Rep", "Let me check that promo on AC-3003 for you.", 2800),
      D("Customer", "They said a monthly discount would show up on the account, and it never did.", 3600),
    ],
    chatTurns: [
      "The customer's promo credit never applied on account AC-3003 — the monthly discount they were promised is missing. Can you re-apply it?",
    ],
    resolveTurn: "Re-apply the missing promo credit on account AC-3003.",
  },
];

export const SALES_DEMOS = DEMOS.filter((d) => d.kind === "sales");
export const SERVICE_DEMOS = DEMOS.filter((d) => d.kind === "service");
