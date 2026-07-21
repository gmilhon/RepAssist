import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { CheckoutView } from "../types";
import { CheckoutFlow, type CheckoutHandlers } from "./Checkout";

/**
 * The customer-facing checkout page, opened on the customer's own phone via the
 * QR / SMS link (`/checkout/{id}`). It drives the SAME server session as the
 * rep's screen, so the two stay in sync: the customer can review the View
 * Together, pick a payment method, and sign here, and the rep's screen follows
 * (both poll `GET /api/shop/checkout/{id}`).
 */
export default function CustomerCheckout({ id }: { id: string }) {
  const [view, setView] = useState<CheckoutView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const viewRef = useRef<CheckoutView | null>(null);

  const set = useCallback((v: CheckoutView) => {
    viewRef.current = v;
    setView(v);
  }, []);

  // Initial load.
  useEffect(() => {
    api.checkoutGet(id).then(set).catch((e) => setError(String(e)));
  }, [id, set]);

  // Follow the rep: poll until the order is complete.
  useEffect(() => {
    if (!view || view.checkout.step === "complete") return;
    const timer = window.setInterval(async () => {
      try {
        const v = await api.checkoutGet(id);
        const cur = viewRef.current;
        if (cur && (v.checkout.step !== cur.checkout.step || v.checkout.sent_channel !== cur.checkout.sent_channel)) {
          set(v);
        }
      } catch {
        /* keep polling */
      }
    }, 2500);
    return () => window.clearInterval(timer);
  }, [id, view?.checkout.step, set]); // eslint-disable-line react-hooks/exhaustive-deps

  const handlers: CheckoutHandlers = {
    variant: "customer",
    busy,
    onAdvance: async () => { setBusy(true); try { set(await api.checkoutAdvance(id)); } finally { setBusy(false); } },
    onPay: async (m, f) => { setBusy(true); try { set(await api.checkoutPay(id, m, f)); } finally { setBusy(false); } },
    onSign: async (s, r) => { setBusy(true); try { set(await api.checkoutSign(id, s, r)); } finally { setBusy(false); } },
    onSendToPhone: async () => null, // hidden on the customer view
  };

  const done = view?.checkout.step === "complete";

  return (
    <div className="cx-checkout">
      <header className="cx-checkout-top">
        <span className="brand-mark">R</span>
        <div className="cx-checkout-brandtext">
          <div className="cx-checkout-brand">Rep Assist</div>
          <div className="cx-checkout-sub">Review &amp; sign on your device</div>
        </div>
      </header>
      <main className="cx-checkout-body">
        {error && <div className="cx-checkout-msg">This checkout link is no longer available. Please ask your rep to resend it.</div>}
        {!error && !view && <div className="cx-checkout-msg">Loading your order…</div>}
        {view && <CheckoutFlow view={view} handlers={handlers} />}
        {done && (
          <div className="cx-checkout-done">🎉 You're all set — thanks! You can hand the device back to your rep.</div>
        )}
      </main>
      <footer className="cx-checkout-foot">Secured demo checkout · no real payment is processed</footer>
    </div>
  );
}
