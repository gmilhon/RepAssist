import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { SystemHealth } from "../types";

interface Props {
  health: SystemHealth;
  runtime?: Record<string, any> | null;  // /health payload: llm_mode, model, langsmith
  onClose: () => void;
}

const STATUS_LABEL: Record<string, string> = {
  operational: "All systems operational",
  degraded: "Partial degradation",
  outage: "Service outage",
};

const REGIONS = [
  { key: "east",    label: "US East",    sub: "AWS us-east-1"   },
  { key: "central", label: "US Central", sub: "GCP us-central1" },
  { key: "west",    label: "US West",    sub: "AWS us-west-2"   },
] as const;

type RegionKey = "east" | "central" | "west";

interface RegionResult { ms: number | null; error: boolean; }

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

export default function HealthPanel({ health, runtime, onClose }: Props) {
  const [pingMs, setPingMs] = useState<number | null>(null);
  const [pingError, setPingError] = useState(false);
  const [pinging, setPinging] = useState(false);
  const [clientIp, setClientIp] = useState<string>("—");

  const [regionResults, setRegionResults] = useState<Record<RegionKey, RegionResult>>({
    east:    { ms: null, error: false },
    central: { ms: null, error: false },
    west:    { ms: null, error: false },
  });
  const [connectedRegion, setConnectedRegion] = useState<string>("us-central");
  const [pingingRegions, setPingingRegions] = useState(false);

  const [lsCount, setLsCount] = useState(0);
  const [ssCount, setSsCount] = useState(0);
  const [cleared, setCleared] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setLsCount(localStorage.length);
    setSsCount(sessionStorage.length);
    runPing();
    runRegionPings();
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
      if (r.region) setConnectedRegion(r.region);
    } catch {
      setPingError(true);
      setPingMs(null);
    } finally {
      setPinging(false);
    }
  }

  async function runRegionPings() {
    setPingingRegions(true);
    const next: Record<RegionKey, RegionResult> = {
      east:    { ms: null, error: false },
      central: { ms: null, error: false },
      west:    { ms: null, error: false },
    };
    await Promise.all(
      (["east", "central", "west"] as RegionKey[]).map(async (region) => {
        const t0 = performance.now();
        try {
          const r = await api.pingRegion(region);
          next[region] = { ms: Math.round(performance.now() - t0), error: false };
          if (region === "central" && r.region) setConnectedRegion(r.region);
        } catch {
          next[region] = { ms: null, error: true };
        }
      })
    );
    setRegionResults(next);
    setPingingRegions(false);
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

  // max ms across regions for normalising the bars
  const maxRegionMs = Math.max(
    ...Object.values(regionResults).map(r => r.ms ?? 0),
    1
  );

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

        {/* Model & tracing (moved here from the topbar pills) */}
        {runtime && (
          <div className="hpanel-section">
            <div className="hpanel-section-head">Model &amp; Tracing</div>
            <div className="hpanel-diag-rows">
              <DiagRow
                label="LLM"
                value={runtime.llm_mode === "anthropic" ? (runtime.model ?? "anthropic") : "mock (offline)"}
                tone={runtime.llm_mode === "anthropic" ? "ok" : "warn"}
                mono
              />
              <DiagRow
                label="LangSmith"
                value={runtime.langsmith?.enabled ? (runtime.langsmith.project ?? "enabled") : "not configured"}
                tone={runtime.langsmith?.enabled ? "ok" : undefined}
                mono
              />
            </div>
          </div>
        )}

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

        {/* ── Server Regions ─────────────────────────────────────────── */}
        <div className="hpanel-section">
          <div className="hpanel-section-head hpanel-section-head--row">
            Server Regions
            <button className="hpanel-action-btn" onClick={runRegionPings} disabled={pingingRegions}>
              {pingingRegions ? "Checking…" : "Re-check"}
            </button>
          </div>
          <div className="hpanel-regions">
            {REGIONS.map(({ key, label, sub }) => {
              const r = regionResults[key];
              const isConnected = connectedRegion === `us-${key}`;
              const tone = r.error ? "danger" : r.ms !== null ? pingTone(r.ms) : undefined;
              const barPct = r.ms !== null ? Math.round((r.ms / maxRegionMs) * 100) : 0;
              return (
                <div key={key} className={`hpanel-region${isConnected ? " hpanel-region--connected" : ""}`}>
                  <div className="hpanel-region-indicator">
                    <span className={`hpanel-region-dot${isConnected ? " hpanel-region-dot--on" : ""}`} />
                    {isConnected && <span className="hpanel-region-connected-label">Connected</span>}
                  </div>
                  <div className="hpanel-region-name">{label}</div>
                  <div className="hpanel-region-sub">{sub}</div>
                  <div className={`hpanel-region-ms${tone ? ` hpanel-region-ms--${tone}` : ""}`}>
                    {pingingRegions ? "…" : r.error ? "Failed" : r.ms !== null ? `${r.ms} ms` : "—"}
                  </div>
                  <div className="hpanel-region-bar-bg">
                    {r.ms !== null && (
                      <div
                        className={`hpanel-region-bar-fill${tone ? ` hpanel-region-bar-fill--${tone}` : ""}`}
                        style={{ width: `${barPct}%` }}
                      />
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

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
