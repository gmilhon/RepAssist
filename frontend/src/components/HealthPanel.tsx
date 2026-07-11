import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { SystemHealth } from "../types";

interface Props {
  health: SystemHealth;
  onClose: () => void;
}

const STATUS_LABEL: Record<string, string> = {
  operational: "All systems operational",
  degraded: "Partial degradation",
  outage: "Service outage",
};

function getBrowserInfo(): string {
  const ua = navigator.userAgent;
  if (ua.includes("Edg/")) return "Edge";
  if (ua.includes("Chrome/") && !ua.includes("Chromium")) return "Chrome";
  if (ua.includes("Firefox/")) return "Firefox";
  if (ua.includes("Safari/") && !ua.includes("Chrome")) return "Safari";
  return "Browser";
}

function getConnectionInfo(): string {
  const conn = (navigator as any).connection;
  if (!conn) return "—";
  const parts: string[] = [];
  if (conn.effectiveType) parts.push(conn.effectiveType);
  if (conn.downlink) parts.push(`${conn.downlink} Mbps`);
  return parts.join(" · ") || "—";
}

function fmtAgo(iso: string | null): string {
  if (!iso) return "";
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function pingTone(ms: number): string {
  if (ms < 400) return "ok";
  if (ms < 1500) return "warn";
  return "danger";
}

interface DiagRowProps {
  label: string;
  value: string;
  tone?: string;
  mono?: boolean;
}

function DiagRow({ label, value, tone, mono }: DiagRowProps) {
  return (
    <div className="hpanel-diag-row">
      <span className="hpanel-diag-label">{label}</span>
      <span className={`hpanel-diag-value${tone ? ` hpanel-diag-value--${tone}` : ""}${mono ? " hpanel-diag-mono" : ""}`}>
        {value}
      </span>
    </div>
  );
}

export default function HealthPanel({ health, onClose }: Props) {
  const [pingMs, setPingMs] = useState<number | null>(null);
  const [pingError, setPingError] = useState(false);
  const [pinging, setPinging] = useState(false);
  const [clientIp, setClientIp] = useState<string>("—");
  const [lsCount, setLsCount] = useState(0);
  const [ssCount, setSsCount] = useState(0);
  const [cleared, setCleared] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setLsCount(localStorage.length);
    setSsCount(sessionStorage.length);
    runPing();
    // Close on Escape
    function onKey(e: KeyboardEvent) { if (e.key === "Escape") onClose(); }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  async function runPing() {
    setPinging(true);
    setPingError(false);
    const t0 = performance.now();
    try {
      const r = await api.ping();
      setPingMs(Math.round(performance.now() - t0));
      setClientIp(r.client_ip);
    } catch {
      setPingError(true);
      setPingMs(null);
    } finally {
      setPinging(false);
    }
  }

  function clearCache() {
    localStorage.clear();
    sessionStorage.clear();
    setLsCount(0);
    setSsCount(0);
    setCleared(true);
    setTimeout(() => setCleared(false), 2000);
  }

  const s = health.status;

  return (
    <>
      <div className="hpanel-backdrop" onClick={onClose} />
      <div className="hpanel" ref={panelRef} role="dialog" aria-label="System health">

        {/* Header */}
        <div className="hpanel-header">
          <div className="hpanel-title">
            <span className={`hpanel-dot hpanel-dot--${s}`} />
            System Health
          </div>
          <button className="hpanel-close" onClick={onClose} aria-label="Close">✕</button>
        </div>

        {/* Status banner */}
        <div className={`hpanel-banner hpanel-banner--${s}`}>
          <span className="hpanel-banner-label">{STATUS_LABEL[s]}</span>
          {health.updated_at && (
            <span className="hpanel-banner-time">Updated {fmtAgo(health.updated_at)}</span>
          )}
        </div>

        {/* Hard stop */}
        {health.hard_stop && (
          <div className="hpanel-hardstop">
            <span className="hpanel-hardstop-icon">⛔</span>
            <span>Hard stop in effect — do not process new orders until this issue is resolved.</span>
          </div>
        )}

        {/* Event details */}
        {(health.description || health.workaround) && (
          <div className="hpanel-section">
            {health.description && (
              <>
                <div className="hpanel-section-head">Event</div>
                <div className="hpanel-section-body">{health.description}</div>
              </>
            )}
            {health.workaround && (
              <>
                <div className="hpanel-section-head" style={{ marginTop: health.description ? 12 : 0 }}>Workaround</div>
                <div className="hpanel-section-body">{health.workaround}</div>
              </>
            )}
          </div>
        )}

        {/* Live diagnostics */}
        <div className="hpanel-section">
          <div className="hpanel-section-head hpanel-section-head--row">
            Live Diagnostics
            <button className="hpanel-action-btn" onClick={runPing} disabled={pinging}>
              {pinging ? "Checking…" : "Re-check"}
            </button>
          </div>
          <div className="hpanel-diag-rows">
            <DiagRow
              label="API round-trip"
              value={pinging ? "…" : pingError ? "Failed" : pingMs !== null ? `${pingMs} ms` : "—"}
              tone={pingError ? "danger" : pingMs !== null ? pingTone(pingMs) : undefined}
            />
            {pingMs !== null && (
              <div className="hpanel-ping-bar">
                <div
                  className={`hpanel-ping-fill hpanel-ping-fill--${pingTone(pingMs)}`}
                  style={{ width: `${Math.min(100, (pingMs / 2000) * 100)}%` }}
                />
              </div>
            )}
            <DiagRow label="Client IP" value={clientIp} mono />
            <DiagRow
              label="API status"
              value={s === "operational" ? "200 OK" : s === "degraded" ? "Degraded" : "Down"}
              tone={s === "operational" ? "ok" : s === "degraded" ? "warn" : "danger"}
            />
            <DiagRow label="Browser" value={getBrowserInfo()} />
            <DiagRow label="Connection" value={getConnectionInfo()} />
          </div>
        </div>

        {/* Cache */}
        <div className="hpanel-section">
          <div className="hpanel-section-head hpanel-section-head--row">
            Browser Cache
            <button className="hpanel-action-btn" onClick={clearCache}>
              {cleared ? "Cleared ✓" : "Clear all"}
            </button>
          </div>
          <div className="hpanel-diag-rows">
            <DiagRow label="localStorage" value={`${lsCount} ${lsCount === 1 ? "key" : "keys"}`} />
            <DiagRow label="sessionStorage" value={`${ssCount} ${ssCount === 1 ? "key" : "keys"}`} />
          </div>
        </div>

      </div>
    </>
  );
}
