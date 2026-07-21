import { useEffect, useRef, useState } from "react";
import type {
  A2UIOrderConfirmation,
  A2UIPayment,
  A2UISignature,
  A2UIViewTogether,
  CheckoutReceipt,
  CheckoutView,
  SendToPhoneResult,
} from "../types";

/**
 * Guided POS checkout UI — the View Together → payment → signature → confirmation
 * wizard. The SAME components render inline on the rep's screen (`variant:"rep"`)
 * and full-screen on the customer's phone (`variant:"customer"`, /checkout/{id}),
 * driven by the shared `/api/shop/checkout/*` endpoints.
 *
 * Payment is simulated (a tender is selected, nothing is charged) and the
 * signature is captured as a demo artifact — see app/checkout.py.
 */
export interface CheckoutHandlers {
  variant: "rep" | "customer";
  busy?: boolean;
  onAdvance: () => void;
  onPay: (method: string, fulfillment: string) => void;
  onSign: (signature: string | null, receiptChannel: string | null) => void;
  onSendToPhone: (channel: "sms" | "qr") => Promise<SendToPhoneResult | null>;
}

export function CheckoutFlow({ view, handlers }: { view: CheckoutView; handlers: CheckoutHandlers }) {
  const el = view.element;
  switch (el.type) {
    case "view_together":
      return <ViewTogetherCard el={el} handlers={handlers} sentChannel={view.checkout.sent_channel} />;
    case "payment":
      return <PaymentCard el={el} handlers={handlers} />;
    case "signature":
      return <SignatureCard el={el} handlers={handlers} />;
    case "order_confirmation":
      return <OrderConfirmationCard el={el} receipt={view.receipt} />;
    default:
      return null;
  }
}

const money = (n: number) => `$${n.toFixed(2)}`;

// ── View Together — the bill review ─────────────────────────────────────────
function ViewTogetherCard({
  el,
  handlers,
  sentChannel,
}: {
  el: A2UIViewTogether;
  handlers: CheckoutHandlers;
  sentChannel: string | null;
}) {
  const [sendResult, setSendResult] = useState<SendToPhoneResult | null>(null);
  const [sending, setSending] = useState<null | "sms" | "qr">(null);
  const existing = el.current_monthly != null;

  async function send(channel: "sms" | "qr") {
    setSending(channel);
    const r = await handlers.onSendToPhone(channel);
    setSendResult(r);
    setSending(null);
  }

  return (
    <div className="a2ui-card co-card">
      <div className="co-head">
        <span className="co-eyebrow">🧾 View Together</span>
        <h4 className="co-title">Let's review it together{el.customer_name ? ` · ${el.customer_name}` : ""}</h4>
        <p className="co-sub">Here's the new monthly bill and what's collected today.</p>
      </div>

      <div className="co-compare">
        {existing && (
          <div className="co-compare-col">
            <span>Current</span>
            <b>{money(el.current_monthly!)}<small>/mo</small></b>
          </div>
        )}
        <div className="co-compare-col co-compare-col--add">
          <span>New charges</span>
          <b>+{money(el.recurring_monthly)}<small>/mo</small></b>
        </div>
        <div className="co-compare-col co-compare-col--total">
          <span>{existing ? "New total" : "Monthly"}</span>
          <b>{money(el.blended_monthly)}<small>/mo</small></b>
        </div>
      </div>

      <div className="co-section-label">Monthly — starts on next month's bill</div>
      <div className="co-lines">
        {el.recurring_lines.map((l, i) => (
          <div key={i} className="co-line">
            <span className="co-line-label">
              {l.label}
              {l.sub && <small> · {l.sub}</small>}
            </span>
            <span className="co-line-amt">{money(l.amount)}/mo</span>
          </div>
        ))}
      </div>

      <div className="co-section-label">Due today — one-time</div>
      <div className="co-lines">
        {el.onetime_lines.map((l, i) => (
          <div key={i} className="co-line">
            <span className="co-line-label">{l.label}</span>
            <span className="co-line-amt">{money(l.amount)}</span>
          </div>
        ))}
      </div>
      <div className="co-duetoday">
        <span>Due today</span>
        <span className="co-duetoday-amt">{money(el.due_today)}</span>
      </div>

      {sendResult && <PhoneHandoff result={sendResult} />}

      <div className="co-actions">
        <button className="btn primary" disabled={handlers.busy} onClick={handlers.onAdvance}>
          Looks good — continue to payment
        </button>
        {handlers.variant === "rep" && (
          <div className="co-phone-btns">
            <span className="co-phone-label">📱 Send to customer's phone:</span>
            <button className="btn ghost small" disabled={sending !== null} onClick={() => send("sms")}>
              {sending === "sms" ? "…" : "Text link"}
            </button>
            <button className="btn ghost small" disabled={sending !== null} onClick={() => send("qr")}>
              {sending === "qr" ? "…" : "Show QR"}
            </button>
          </div>
        )}
      </div>
      {sentChannel && handlers.variant === "rep" && !sendResult && (
        <div className="co-sent-note">Handed off to the customer's phone — they can review &amp; sign there, or keep going here.</div>
      )}
    </div>
  );
}

function PhoneHandoff({ result }: { result: SendToPhoneResult }) {
  const isQr = result.channel === "qr" && result.qr_svg_data_uri;
  return (
    <div className="co-handoff">
      {isQr ? (
        <>
          <img className="co-qr" src={result.qr_svg_data_uri} alt="Scan to continue on your phone" />
          <div className="co-handoff-text">
            <b>Scan to continue on the customer's phone</b>
            <span className="co-handoff-link">{result.link}</span>
          </div>
        </>
      ) : (
        <div className="co-handoff-text">
          <b>📱 Text {result.to ? `ready for ${result.to}` : "link"}</b>
          <span className="co-handoff-preview">{result.body}</span>
          {!result.to && <span className="co-handoff-warn">No number on file — show the QR instead.</span>}
        </div>
      )}
    </div>
  );
}

// ── Payment — simulated tender + fulfillment ────────────────────────────────
function PaymentCard({ el, handlers }: { el: A2UIPayment; handlers: CheckoutHandlers }) {
  const [method, setMethod] = useState(el.tenders[0]?.id ?? "card_on_file");
  const [fulfillment, setFulfillment] = useState(el.fulfillment ?? "pickup");

  return (
    <div className="a2ui-card co-card">
      <div className="co-head">
        <span className="co-eyebrow">💳 Payment</span>
        <h4 className="co-title">Confirm payment</h4>
        <p className="co-sub">Simulated — no card is charged in this demo.</p>
      </div>

      <div className="co-pay-summary">
        <div><span>Due today</span><b>{money(el.due_today)}</b></div>
        <div><span>Then monthly</span><b>{money(el.blended_monthly)}/mo</b></div>
      </div>

      <div className="co-section-label">Payment method</div>
      <div className="co-tenders">
        {el.tenders.map((t) => (
          <button
            key={t.id}
            type="button"
            className={`co-tender${method === t.id ? " selected" : ""}`}
            onClick={() => setMethod(t.id)}
          >
            <span className="co-tender-radio">{method === t.id ? "◉" : "○"}</span>
            <span className="co-tender-main">
              <b>{t.label}</b>
              {t.sub && <small>{t.sub}</small>}
            </span>
          </button>
        ))}
      </div>

      <div className="co-section-label">Fulfillment</div>
      <div className="co-fulfil">
        <button type="button" className={`co-chip${fulfillment === "pickup" ? " selected" : ""}`} onClick={() => setFulfillment("pickup")}>
          🏬 In-store pickup
        </button>
        <button type="button" className={`co-chip${fulfillment === "ship" ? " selected" : ""}`} onClick={() => setFulfillment("ship")}>
          📦 Ship to home
        </button>
      </div>

      <div className="co-actions">
        <button className="btn primary" disabled={handlers.busy} onClick={() => handlers.onPay(method, fulfillment)}>
          Charge {money(el.due_today)} &amp; continue
        </button>
      </div>
    </div>
  );
}

// ── Signature — canvas capture ──────────────────────────────────────────────
function SignatureCard({ el, handlers }: { el: A2UISignature; handlers: CheckoutHandlers }) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const drawing = useRef(false);
  const [hasInk, setHasInk] = useState(false);
  const [receipt, setReceipt] = useState<"sms" | "email" | "none">("sms");

  useEffect(() => {
    const c = canvasRef.current;
    if (!c) return;
    const ratio = window.devicePixelRatio || 1;
    const rect = c.getBoundingClientRect();
    c.width = rect.width * ratio;
    c.height = rect.height * ratio;
    const ctx = c.getContext("2d");
    if (ctx) {
      ctx.scale(ratio, ratio);
      ctx.lineWidth = 2.2;
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      ctx.strokeStyle = "#0b0b0b";
    }
  }, []);

  function point(e: React.MouseEvent | React.TouchEvent) {
    const c = canvasRef.current!;
    const r = c.getBoundingClientRect();
    const t = "touches" in e ? e.touches[0] : (e as React.MouseEvent);
    return { x: t.clientX - r.left, y: t.clientY - r.top };
  }
  function start(e: React.MouseEvent | React.TouchEvent) {
    e.preventDefault();
    drawing.current = true;
    const ctx = canvasRef.current!.getContext("2d")!;
    const p = point(e);
    ctx.beginPath();
    ctx.moveTo(p.x, p.y);
  }
  function move(e: React.MouseEvent | React.TouchEvent) {
    if (!drawing.current) return;
    e.preventDefault();
    const ctx = canvasRef.current!.getContext("2d")!;
    const p = point(e);
    ctx.lineTo(p.x, p.y);
    ctx.stroke();
    if (!hasInk) setHasInk(true);
  }
  function end() {
    drawing.current = false;
  }
  function clear() {
    const c = canvasRef.current!;
    c.getContext("2d")!.clearRect(0, 0, c.width, c.height);
    setHasInk(false);
  }
  function complete() {
    const data = hasInk ? canvasRef.current!.toDataURL("image/png") : null;
    handlers.onSign(data, receipt === "none" ? null : receipt);
  }

  return (
    <div className="a2ui-card co-card">
      <div className="co-head">
        <span className="co-eyebrow">✍️ Signature</span>
        <h4 className="co-title">Sign to complete</h4>
        <p className="co-sub">
          Your signature authorizes today's {money(el.due_today)} charge and {money(el.blended_monthly)}/mo going forward.
        </p>
      </div>

      <div className="co-sign-pad">
        <canvas
          ref={canvasRef}
          className="co-sign-canvas"
          onMouseDown={start}
          onMouseMove={move}
          onMouseUp={end}
          onMouseLeave={end}
          onTouchStart={start}
          onTouchMove={move}
          onTouchEnd={end}
        />
        <div className="co-sign-line">✕&nbsp;&nbsp;{el.customer_name ?? "Customer signature"}</div>
      </div>

      <div className="co-sign-tools">
        <button type="button" className="btn ghost small" onClick={clear}>Clear</button>
        <div className="co-receipt">
          <span className="co-receipt-label">Receipt:</span>
          {(["sms", "email", "none"] as const).map((r) => (
            <button key={r} type="button" className={`co-chip small${receipt === r ? " selected" : ""}`} onClick={() => setReceipt(r)}>
              {r === "sms" ? "Text" : r === "email" ? "Email" : "None"}
            </button>
          ))}
        </div>
      </div>

      <div className="co-actions">
        <button className="btn primary" disabled={handlers.busy || !hasInk} onClick={complete}>
          Sign &amp; place order
        </button>
      </div>
      <div className="co-hint">Sign above with a finger, stylus, or mouse.</div>
    </div>
  );
}

// ── Order confirmation (also used by A2UIRenderer for the graph fallback) ────
export function OrderConfirmationCard({ el, receipt }: { el: A2UIOrderConfirmation; receipt?: CheckoutReceipt }) {
  const devices = el.items.filter((i) => i.kind === "new_line" || i.kind === "upgrade");
  const perks = el.items.filter((i) => i.kind === "perk");
  const accessories = el.items.filter((i) => i.kind === "accessory");
  const dueToday = el.due_today ?? el.onetime_total;
  return (
    <div className="a2ui-card a2ui-order co-card">
      <div className="a2ui-order-head">
        <span className="a2ui-order-check">✓</span>
        <div>
          <div className="a2ui-order-title">Order placed</div>
          <div className="a2ui-order-id">{el.order_id}</div>
        </div>
      </div>

      <div className="a2ui-order-items">
        {devices.map((it) => (
          <div key={it.item_id} className="a2ui-order-item">
            <span className="a2ui-order-item-name">
              {it.device ?? "Device"}{it.line_id ? ` · ${it.line_id}` : ""}
              <span className="a2ui-order-item-plan"> · {it.plan ?? "—"}</span>
              {it.protection && <span className="co-inline-tag"> + {it.protection.name}</span>}
              {it.trade_in && <span className="co-inline-tag co-inline-tag--credit"> trade-in −${it.trade_in.credit.toFixed(0)}</span>}
            </span>
            <span className="a2ui-order-item-price">{money(it.monthly)}/mo</span>
          </div>
        ))}
        {perks.map((it) => (
          <div key={it.item_id} className="a2ui-order-item">
            <span className="a2ui-order-item-name">🎁 {it.name}</span>
            <span className="a2ui-order-item-price">{money(it.monthly)}/mo</span>
          </div>
        ))}
        {accessories.map((it) => (
          <div key={it.item_id} className="a2ui-order-item">
            <span className="a2ui-order-item-name">🛍 {it.name}</span>
            <span className="a2ui-order-item-price">{money(it.onetime)}</span>
          </div>
        ))}
      </div>

      <div className="a2ui-order-total">
        <span>Monthly total</span>
        <span className="a2ui-order-total-amt">{money(el.monthly_total)}/mo</span>
      </div>
      {el.current_monthly != null && el.blended_monthly != null && (
        <div className="co-line co-line--muted">
          <span className="co-line-label">New account total</span>
          <span className="co-line-amt">{money(el.blended_monthly)}/mo</span>
        </div>
      )}

      <div className="a2ui-order-pay">
        💳 {el.payment_method} · {money(dueToday)} paid today{el.signature_ref ? " · signed ✓" : ""}
      </div>
      <div className="co-conf-foot">
        <span className="co-badge">{el.fulfillment === "ship" ? "📦 Shipping to home" : "🏬 In-store pickup"}</span>
        {receipt?.previewed ? (
          <span className="co-badge">✉️ {receipt.message}</span>
        ) : el.receipt_channel ? (
          <span className="co-badge">✉️ Receipt via {el.receipt_channel === "sms" ? "text" : el.receipt_channel}</span>
        ) : null}
      </div>
    </div>
  );
}
