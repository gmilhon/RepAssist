import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import ChatWidget from "./components/ChatWidget";
import HealthPanel from "./components/HealthPanel";
import ReviewConsole from "./components/ReviewConsole";
import OperationsDashboard from "./components/OperationsDashboard";
import CXDashboard from "./components/CXDashboard";
import SettingsPage from "./components/SettingsPage";
import type { SystemHealth } from "./types";

type Tab = "chat" | "desk" | "ops" | "cx" | "settings";

const STATUS_COLOR: Record<string, string> = {
  operational: "green",
  degraded: "yellow",
  outage: "red",
};

export default function App() {
  const [tab, setTab] = useState<Tab>("chat");
  const [health, setHealth] = useState<Record<string, any> | null>(null);
  const [sysHealth, setSysHealth] = useState<SystemHealth>({
    status: "operational", description: "", workaround: "", hard_stop: false, updated_at: null,
  });
  const [showHealthPanel, setShowHealthPanel] = useState(false);
  const healthPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth({ status: "down" }));
    loadSysHealth();
    healthPollRef.current = setInterval(loadSysHealth, 60_000);
    return () => { if (healthPollRef.current) clearInterval(healthPollRef.current); };
  }, []);

  function loadSysHealth() {
    api.getSystemHealth().then(setSysHealth).catch(() => {});
  }

  const llmMode = health?.llm_mode ?? "…";
  const lsEnabled = health?.langsmith?.enabled ?? false;
  const shStatus = sysHealth?.status ?? "operational";

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">✓</span>
          <span className="brand-name">Rep Assist</span>
          <span className="brand-sub">Assisted Sales &amp; Service</span>
        </div>
        <nav className="tabs">
          <button className={tab === "chat" ? "tab active" : "tab"} onClick={() => setTab("chat")}>
            Rep Assist
          </button>
          <button className={tab === "desk" ? "tab active" : "tab"} onClick={() => setTab("desk")}>
            Resolution Desk
          </button>
          <button className={tab === "ops" ? "tab active" : "tab"} onClick={() => setTab("ops")}>
            Performance
          </button>
          <button className={tab === "cx" ? "tab active" : "tab"} onClick={() => setTab("cx")}>
            CX Monitor
          </button>
          <button className={tab === "settings" ? "tab active" : "tab"} onClick={() => setTab("settings")}>
            Settings
          </button>
        </nav>
        <div className="topbar-pills">
          <div className={`llm-pill ${llmMode === "anthropic" ? "live" : "mock"}`}>
            {llmMode === "anthropic" ? `LLM: ${health?.model}` : `LLM: mock (offline)`}
          </div>
          <div className={`llm-pill ${lsEnabled ? "live" : "mock"}`}>
            {lsEnabled ? `LS: ${health?.langsmith?.project}` : "LS: not configured"}
          </div>
        </div>
        <button
          className={`health-badge health-badge--${shStatus}`}
          onClick={() => setShowHealthPanel(v => !v)}
          title="System health"
          aria-label="System health"
        >
          <span className={`health-badge-dot health-badge-dot--${shStatus}`} />
          <span className="health-badge-label">{STATUS_COLOR[shStatus] === "green" ? "Operational" : shStatus === "degraded" ? "Degraded" : "Outage"}</span>
        </button>
      </header>

      <main className="content">
        {tab === "chat" && <ChatWidget />}
        {tab === "desk" && <ReviewConsole />}
        {tab === "ops" && <OperationsDashboard />}
        {tab === "cx" && <CXDashboard />}
        {tab === "settings" && <SettingsPage onHealthChange={loadSysHealth} />}
      </main>

      {showHealthPanel && (
        <HealthPanel health={sysHealth} onClose={() => setShowHealthPanel(false)} />
      )}
    </div>
  );
}
