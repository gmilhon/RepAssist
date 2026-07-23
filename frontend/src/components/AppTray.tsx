import { useCallback, useEffect, useRef, useState } from "react";
import type { ChatAction } from "../chatActions";

export type Tab = "chat" | "desk" | "store" | "district" | "territory" | "ops" | "cx" | "prod" | "settings";

interface Props {
  open: boolean;
  tab: Tab;
  onNavigate: (tab: Tab) => void;
  onChatAction: (action: ChatAction) => void;
  onClose: () => void;
}

// A row that either navigates to a tab, fires a chat action, or expands a
// submenu of tabs. `children` (submenu) is rendered indented when expanded.
type Row =
  | { kind: "action"; icon: string; label: string; action: ChatAction }
  | { kind: "nav"; icon: string; label: string; tab: Tab }
  | { kind: "group"; icon: string; label: string; items: { icon: string; label: string; tab: Tab }[] };

const ROWS: Row[] = [
  {
    kind: "group", icon: "📊", label: "Performance", items: [
      { icon: "🏪", label: "Store Manager", tab: "store" },
      { icon: "🗺️", label: "District", tab: "district" },
      { icon: "🌎", label: "Territory", tab: "territory" },
    ],
  },
  { kind: "action", icon: "📦", label: "Recent Orders", action: { kind: "lookup", value: "orders" } },
  { kind: "action", icon: "🎫", label: "My Tickets", action: { kind: "lookup", value: "tickets" } },
  { kind: "nav", icon: "🗂️", label: "Resolution Desk", tab: "desk" },
  { kind: "action", icon: "✨", label: "System Enhancements", action: { kind: "lookup", value: "system" } },
  { kind: "action", icon: "🚀", label: "The Opener", action: { kind: "lookup", value: "huddle" } },
  { kind: "nav", icon: "⚙️", label: "Settings", tab: "settings" },
  {
    kind: "group", icon: "🩺", label: "System Performance", items: [
      { icon: "📊", label: "Performance", tab: "ops" },
      { icon: "📈", label: "CX Monitor", tab: "cx" },
      { icon: "🚨", label: "Production", tab: "prod" },
    ],
  },
];

// Fractions of the viewport height that are VISIBLE at each snap point.
const SHEET = 0.92;       // sheet element height
const HALF_VISIBLE = 0.56; // visible at the half snap

export default function AppTray({ open, tab, onNavigate, onChatAction, onClose }: Props) {
  const [ty, setTy] = useState(9999);          // translateY in px (large = off-screen)
  const [dragging, setDragging] = useState(false);
  const [snap, setSnap] = useState<"half" | "full">("half");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const drag = useRef({ startY: 0, startTy: 0, lastY: 0, lastT: 0, vel: 0 });

  const metrics = useCallback(() => {
    const vh = window.innerHeight;
    const sheetH = SHEET * vh;
    const halfBase = sheetH - HALF_VISIBLE * vh; // translate down to reveal `half`
    return { sheetH, halfBase, fullBase: 0, offBase: sheetH };
  }, []);

  // Open/close: settle to the half snap when opening, push off-screen when closing.
  useEffect(() => {
    const { halfBase, offBase } = metrics();
    if (open) { setSnap("half"); setTy(halfBase); }
    else { setTy(offBase); setExpanded(new Set()); }
  }, [open, metrics]);

  // Keep snap positions correct across viewport resizes/rotations.
  useEffect(() => {
    function onResize() {
      if (dragging) return;
      const { fullBase, halfBase, offBase } = metrics();
      setTy(!open ? offBase : snap === "full" ? fullBase : halfBase);
    }
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [open, snap, dragging, metrics]);

  function onPointerDown(e: React.PointerEvent) {
    (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
    drag.current = { startY: e.clientY, startTy: ty, lastY: e.clientY, lastT: performance.now(), vel: 0 };
    setDragging(true);
  }
  function onPointerMove(e: React.PointerEvent) {
    if (!dragging) return;
    const { offBase } = metrics();
    const next = Math.min(Math.max(drag.current.startTy + (e.clientY - drag.current.startY), 0), offBase);
    const now = performance.now();
    const dt = now - drag.current.lastT;
    if (dt > 0) drag.current.vel = (e.clientY - drag.current.lastY) / dt; // px/ms, +down
    drag.current.lastY = e.clientY; drag.current.lastT = now;
    setTy(next);
  }
  function onPointerUp() {
    if (!dragging) return;
    setDragging(false);
    const { fullBase, halfBase, offBase } = metrics();
    const v = drag.current.vel;
    let target: "full" | "half" | "close";
    if (v > 0.6) target = snap === "full" ? "half" : "close";        // fast flick down
    else if (v < -0.6) target = "full";                               // fast flick up
    else {
      const midFH = (fullBase + halfBase) / 2;
      const midHO = (halfBase + offBase) / 2;
      target = ty < midFH ? "full" : ty < midHO ? "half" : "close";
    }
    if (target === "close") { onClose(); return; }
    setSnap(target);
    setTy(target === "full" ? fullBase : halfBase);
  }

  function fire(action: ChatAction) { onChatAction(action); onClose(); }
  function go(t: Tab) { onNavigate(t); onClose(); }
  function toggleGroup(label: string) {
    setExpanded((prev) => {
      const n = new Set(prev);
      n.has(label) ? n.delete(label) : n.add(label);
      return n;
    });
    // A group at the half snap benefits from more room — pop to full on expand.
    if (!expanded.has(label) && snap === "half") {
      const { fullBase } = metrics();
      setSnap("full"); setTy(fullBase);
    }
  }

  return (
    <>
      <div
        className={`tray-backdrop${open ? " open" : ""}`}
        onClick={onClose}
        aria-hidden={!open}
      />
      <div
        className={`tray-sheet${open ? " open" : ""}${dragging ? " dragging" : ""}`}
        style={{ transform: `translateY(${ty}px)` }}
        role="dialog"
        aria-modal="true"
        aria-label="Menu"
        aria-hidden={!open}
      >
        <div
          className="tray-grip"
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerUp}
        >
          <span className="tray-grip-bar" />
        </div>

        <div className="tray-scroll">
          <button className="tray-newchat" onClick={() => fire({ kind: "reset" })}>
            <span className="tray-newchat-icon">✏️</span>
            <span className="tray-newchat-label">New chat</span>
          </button>

          <div className="tray-scanrow">
            <button className="tray-scan" onClick={() => fire({ kind: "scan_barcode" })}>
              <span className="tray-scan-icon">🔎</span>
              <span className="tray-scan-label">Scan Barcode</span>
              <span className="tray-scan-sub">Look up a product</span>
            </button>
            <button className="tray-scan" onClick={() => fire({ kind: "scan_bill" })}>
              <span className="tray-scan-icon">🧾</span>
              <span className="tray-scan-label">Scan Bill</span>
              <span className="tray-scan-sub">Analyze &amp; switch</span>
            </button>
            <button className="tray-scan" onClick={() => fire({ kind: "checkin" })}>
              <span className="tray-scan-icon">📝</span>
              <span className="tray-scan-label">Check In</span>
              <span className="tray-scan-sub">Queue a customer</span>
            </button>
          </div>

          <nav className="tray-list">
            {ROWS.map((row) => {
              if (row.kind === "action") {
                return (
                  <button key={row.label} className="tray-item" onClick={() => fire(row.action)}>
                    <span className="tray-item-icon">{row.icon}</span>
                    <span className="tray-item-label">{row.label}</span>
                  </button>
                );
              }
              if (row.kind === "nav") {
                return (
                  <button
                    key={row.label}
                    className={`tray-item${tab === row.tab ? " active" : ""}`}
                    onClick={() => go(row.tab)}
                  >
                    <span className="tray-item-icon">{row.icon}</span>
                    <span className="tray-item-label">{row.label}</span>
                  </button>
                );
              }
              const isOpen = expanded.has(row.label);
              const activeChild = row.items.some((c) => c.tab === tab);
              return (
                <div key={row.label} className="tray-group">
                  <button
                    className={`tray-item${activeChild && !isOpen ? " active" : ""}`}
                    onClick={() => toggleGroup(row.label)}
                    aria-expanded={isOpen}
                  >
                    <span className="tray-item-icon">{row.icon}</span>
                    <span className="tray-item-label">{row.label}</span>
                    <span className={`tray-item-chevron${isOpen ? " open" : ""}`}>›</span>
                  </button>
                  {isOpen && (
                    <div className="tray-subitems">
                      {row.items.map((c) => (
                        <button
                          key={c.tab}
                          className={`tray-subitem${tab === c.tab ? " active" : ""}`}
                          onClick={() => go(c.tab)}
                        >
                          <span className="tray-item-icon">{c.icon}</span>
                          <span className="tray-item-label">{c.label}</span>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </nav>
        </div>
      </div>
    </>
  );
}
