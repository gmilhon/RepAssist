import { useEffect, useState } from "react";
import { api } from "./api";
import ChatWidget from "./components/ChatWidget";
import ReviewConsole from "./components/ReviewConsole";
import OperationsDashboard from "./components/OperationsDashboard";

type Tab = "chat" | "desk" | "ops";

export default function App() {
  const [tab, setTab] = useState<Tab>("chat");
  const [health, setHealth] = useState<Record<string, any> | null>(null);

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth({ status: "down" }));
  }, []);

  const llmMode = health?.llm_mode ?? "…";

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
        </nav>
        <div className={`llm-pill ${llmMode === "anthropic" ? "live" : "mock"}`}>
          {llmMode === "anthropic" ? `LLM: ${health?.model}` : `LLM: mock (offline)`}
        </div>
      </header>

      <main className="content">
        {tab === "chat" && <ChatWidget />}
        {tab === "desk" && <ReviewConsole />}
        {tab === "ops" && <OperationsDashboard />}
      </main>
    </div>
  );
}
