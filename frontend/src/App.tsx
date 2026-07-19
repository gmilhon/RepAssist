import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import ChatWidget from "./components/ChatWidget";
import HealthPanel from "./components/HealthPanel";
import LiveQueuePanel from "./components/LiveQueuePanel";
import ReviewConsole from "./components/ReviewConsole";
import OperationsDashboard from "./components/OperationsDashboard";
import CXDashboard from "./components/CXDashboard";
import ProductionDashboard from "./components/ProductionDashboard";
import SettingsPage from "./components/SettingsPage";
import type { LiveQueueSnapshot, SystemHealth } from "./types";

type Tab = "chat" | "desk" | "ops" | "cx" | "prod" | "settings";

const STATUS_COLOR: Record<string, string> = {
  operational: "green",
  degraded: "yellow",
  outage: "red",
};

const STATUS_LABEL: Record<string, string> = {
  operational: "All systems operational",
  degraded: "Partial degradation",
  outage: "Service outage",
};

interface HealthToast {
  id: number;
  health: SystemHealth;
}

export default function App() {
  const [tab, setTab] = useState<Tab>("chat");
  const [health, setHealth] = useState<Record<string, any> | null>(null);
  const [sysHealth, setSysHealth] = useState<SystemHealth>({
    status: "operational", description: "", workaround: "", hard_stop: false, updated_at: null,
  });
  const [showHealthPanel, setShowHealthPanel] = useState(false);
  const [healthToasts, setHealthToasts] = useState<HealthToast[]>([]);
  const [liveQueue, setLiveQueue] = useState<LiveQueueSnapshot | null>(null);
  const [showLiveQueue, setShowLiveQueue] = useState(false);
  const [lqRefreshing, setLqRefreshing] = useState(false);
  const healthPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const queuePollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const toastIdRef = useRef(0);

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth({ status: "down" }));
    loadSysHealth();
    loadLiveQueue();
    healthPollRef.current = setInterval(loadSysHealth, 60_000);
    queuePollRef.current = setInterval(loadLiveQueue, 20_000);

    const es = new EventSource(api.healthEventsUrl());
    es.addEventListener("health_update", (e: MessageEvent) => {
      try {
        const updated: SystemHealth = JSON.parse(e.data);
        setSysHealth(updated);
        const id = ++toastIdRef.current;
        setHealthToasts(prev => [...prev, { id, health: updated }]);
        setTimeout(() => setHealthToasts(prev => prev.filter(t => t.id !== id)), 8000);
      } catch { /* ignore malformed */ }
    });

    return () => {
      if (healthPollRef.current) clearInterval(healthPollRef.current);
      if (queuePollRef.current) clearInterval(queuePollRef.current);
      es.close();
    };
  }, []);

  function loadSysHealth() {
    api.getSystemHealth().then(setSysHealth).catch(() => {});
  }

  function loadLiveQueue() {
    api.liveQueue().then(setLiveQueue).catch(() => {});
  }

  function refreshLiveQueue() {
    setLqRefreshing(true);
    api.liveQueue().then(setLiveQueue).catch(() => {}).finally(() => setLqRefreshing(false));
  }

  function dismissToast(id: number) {
    setHealthToasts(prev => prev.filter(t => t.id !== id));
  }

  const shStatus = sysHealth?.status ?? "operational";
  const qc = liveQueue?.counts;

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
          <button className={tab === "prod" ? "tab active" : "tab"} onClick={() => setTab("prod")}>
            Production
          </button>
          <button className={tab === "settings" ? "tab active" : "tab"} onClick={() => setTab("settings")}>
            Settings
          </button>
        </nav>

        <div className="topbar-right">
          <button
            className={`queue-badge${showLiveQueue ? " queue-badge--active" : ""}`}
            onClick={() => setShowLiveQueue(v => !v)}
            title="Live queue"
            aria-label="Live queue"
          >
            <span className="queue-badge-icon">🧑‍🤝‍🧑</span>
            <span className="queue-badge-name">Live Queue</span>
            <span className="queue-badge-segs">
              <span className="queue-badge-seg"><b>{qc?.waiting ?? "–"}</b> wait</span>
              <span className="queue-badge-seg"><b>{qc?.assisting ?? "–"}</b> active</span>
              <span className="queue-badge-seg"><b>{qc?.ispu ?? "–"}</b> ISPU</span>
            </span>
          </button>

          <button
            className={`health-badge health-badge--${shStatus}`}
            onClick={() => setShowHealthPanel(v => !v)}
            title="System health"
            aria-label="System health"
          >
            <span className={`health-badge-dot health-badge-dot--${shStatus}`} />
            <span className="health-badge-label">{STATUS_COLOR[shStatus] === "green" ? "Operational" : shStatus === "degraded" ? "Degraded" : "Outage"}</span>
          </button>
        </div>
      </header>

      <main className="content">
        {tab === "chat" && <ChatWidget />}
        {tab === "desk" && <ReviewConsole />}
        {tab === "ops" && <OperationsDashboard />}
        {tab === "cx" && <CXDashboard />}
        {tab === "prod" && <ProductionDashboard />}
        {tab === "settings" && <SettingsPage onHealthChange={loadSysHealth} />}
      </main>

      {showHealthPanel && (
        <HealthPanel health={sysHealth} runtime={health} onClose={() => setShowHealthPanel(false)} />
      )}

      {showLiveQueue && (
        <LiveQueuePanel
          snapshot={liveQueue}
          onClose={() => setShowLiveQueue(false)}
          onRefresh={refreshLiveQueue}
          refreshing={lqRefreshing}
        />
      )}

      {healthToasts.length > 0 && (
        <div className="health-toast-stack">
          {healthToasts.map(t => (
            <div key={t.id} className={`health-toast health-toast--${t.health.status}`}>
              <span className={`health-toast-dot health-toast-dot--${t.health.status}`} />
              <div className="health-toast-body">
                <span className="health-toast-title">{STATUS_LABEL[t.health.status]}</span>
                {t.health.description && (
                  <span className="health-toast-desc">{t.health.description}</span>
                )}
              </div>
              <button className="health-toast-close" onClick={() => dismissToast(t.id)} aria-label="Dismiss">✕</button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
