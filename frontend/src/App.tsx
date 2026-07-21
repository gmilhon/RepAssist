import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { ChatAction } from "./chatActions";
import AppDrawer from "./components/AppDrawer";
import type { Tab } from "./components/AppDrawer";
import ChatWidget from "./components/ChatWidget";
import HealthPanel from "./components/HealthPanel";
import LiveQueuePanel from "./components/LiveQueuePanel";
import ReviewConsole from "./components/ReviewConsole";
import OperationsDashboard from "./components/OperationsDashboard";
import StoreManagerDashboard from "./components/StoreManagerDashboard";
import RollupDashboard from "./components/RollupDashboard";
import CXDashboard from "./components/CXDashboard";
import ProductionDashboard from "./components/ProductionDashboard";
import SettingsPage from "./components/SettingsPage";
import type { LiveQueueEntry, LiveQueueSnapshot, SystemHealth } from "./types";

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

// Current-view label shown in the topbar (the tab buttons moved into the drawer).
const VIEW_TITLES: Record<Tab, string> = {
  chat: "Rep Assist",
  desk: "Resolution Desk",
  store: "Store Manager",
  district: "District Rollup",
  territory: "Territory Rollup",
  ops: "Performance",
  cx: "CX Monitor",
  prod: "Production",
  settings: "Settings",
};

interface HealthToast {
  id: number;
  health: SystemHealth;
}

export default function App() {
  const [tab, setTab] = useState<Tab>("chat");
  const [menuOpen, setMenuOpen] = useState(false);
  // A quick-action dispatched from the drawer into ChatWidget. The nonce forces
  // the chat's effect to re-run even when the same action is picked twice.
  const [chatAction, setChatAction] = useState<ChatAction | null>(null);
  const [chatActionNonce, setChatActionNonce] = useState(0);
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

  function navigate(next: Tab) {
    setTab(next);
    setMenuOpen(false);
  }

  // Drawer → chat quick-action: make sure we're on the chat view, then hand the
  // action to ChatWidget (which owns the handlers) via a nonce-bumped prop.
  function dispatchChatAction(action: ChatAction) {
    setTab("chat");
    setChatAction(action);
    setChatActionNonce(n => n + 1);
    setMenuOpen(false);
  }

  // Live Queue tray → assist a waiting customer: close the tray, switch to chat,
  // and hand the customer's identity to ChatWidget to start the assist.
  function assistFromLiveQueue(entry: LiveQueueEntry) {
    setShowLiveQueue(false);
    dispatchChatAction({
      kind: "assist",
      entry: {
        id: entry.id,
        customer_name: entry.customer_name,
        customer_phone: entry.customer_phone,
        reason: entry.reason,
        reason_label: entry.reason_label,
        account_id: entry.account_id,
        order_id: entry.order_id,
      },
    });
  }

  const shStatus = sysHealth?.status ?? "operational";
  const qc = liveQueue?.counts;

  return (
    <div className="app">
      <header className="topbar">
        <button
          className="topbar-menu"
          onClick={() => setMenuOpen(true)}
          aria-label="Open menu"
          aria-expanded={menuOpen}
          title="Menu"
        >
          ☰
        </button>
        <div className="brand">
          <span className="brand-mark">✓</span>
          <span className="brand-name">Rep Assist</span>
          <span className="brand-sub">Assisted Sales &amp; Service</span>
        </div>
        {/* Wayfinding label for secondary views; the chat "home" is the brand itself. */}
        {tab !== "chat" && <span className="topbar-view">{VIEW_TITLES[tab]}</span>}

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
        {tab === "chat" && (
          <ChatWidget
            onOpenMenu={() => setMenuOpen(true)}
            chatAction={chatAction}
            chatActionNonce={chatActionNonce}
            onChatActionDone={() => setChatAction(null)}
          />
        )}
        {tab === "desk" && <ReviewConsole />}
        {tab === "store" && <StoreManagerDashboard />}
        {tab === "district" && <RollupDashboard level="district" />}
        {tab === "territory" && <RollupDashboard level="territory" />}
        {tab === "ops" && <OperationsDashboard />}
        {tab === "cx" && <CXDashboard />}
        {tab === "prod" && <ProductionDashboard />}
        {tab === "settings" && <SettingsPage onHealthChange={loadSysHealth} />}
      </main>

      <AppDrawer
        open={menuOpen}
        tab={tab}
        onNavigate={navigate}
        onChatAction={dispatchChatAction}
        onClose={() => setMenuOpen(false)}
      />

      {showHealthPanel && (
        <HealthPanel health={sysHealth} runtime={health} onClose={() => setShowHealthPanel(false)} />
      )}

      {showLiveQueue && (
        <LiveQueuePanel
          snapshot={liveQueue}
          onClose={() => setShowLiveQueue(false)}
          onRefresh={refreshLiveQueue}
          refreshing={lqRefreshing}
          onAssist={assistFromLiveQueue}
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
