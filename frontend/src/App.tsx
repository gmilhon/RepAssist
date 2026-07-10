import { useEffect, useState } from "react";
import { api } from "./api";
import ChatWidget from "./components/ChatWidget";
import ReviewConsole from "./components/ReviewConsole";
import OperationsDashboard from "./components/OperationsDashboard";
import CXDashboard from "./components/CXDashboard";

type Tab = "chat" | "desk" | "ops" | "cx";

export default function App() {
  const [tab, setTab] = useState<Tab>("chat");
  const [health, setHealth] = useState<Record<string, any> | null>(null);

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth({ status: "down" }));
  }, []);

  const llmMode = health?.llm_mode ?? "…";
  const lsEnabled = health?.langsmith?.enabled ?? false;

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">✓</span>
          <span className="brand-name">Rep Assist</span>
          <span className="brand-sub">Verizon POS · Order &amp; Service Support</span>
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
        </nav>
        <div className="topbar-pills">
          <div className={`llm-pill ${llmMode === "anthropic" ? "live" : "mock"}`}>
            {llmMode === "anthropic" ? `LLM: ${health?.model}` : `LLM: mock (offline)`}
          </div>
          <div className={`llm-pill ${lsEnabled ? "live" : "mock"}`}>
            {lsEnabled ? `LS: ${health?.langsmith?.project}` : "LS: not configured"}
          </div>
        </div>
      </header>

      <main className="content">
        {tab === "chat" && <ChatWidget />}
        {tab === "desk" && <ReviewConsole />}
        {tab === "ops" && <OperationsDashboard />}
        {tab === "cx" && <CXDashboard />}
      </main>
    </div>
  );
}
