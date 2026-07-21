import type { ChatAction, DrawerItem } from "../chatActions";
import { BRIEFINGS, FRONT_DESK, LOOKUPS } from "../chatActions";

export type Tab = "chat" | "desk" | "ops" | "cx" | "prod" | "settings";

// Primary navigation — the views that used to live as topbar tabs, now grouped.
const NAV_GROUPS: { heading: string; items: { tab: Tab; icon: string; label: string }[] }[] = [
  {
    heading: "Workspace",
    items: [
      { tab: "chat", icon: "💬", label: "Rep Assist" },
      { tab: "desk", icon: "🗂️", label: "Resolution Desk" },
    ],
  },
  {
    heading: "Analytics",
    items: [
      { tab: "ops", icon: "📊", label: "Performance" },
      { tab: "cx", icon: "📈", label: "CX Monitor" },
      { tab: "prod", icon: "🚨", label: "Production" },
    ],
  },
  {
    heading: "Admin",
    items: [{ tab: "settings", icon: "⚙️", label: "Settings" }],
  },
];

// Chat quick-start groups (shown below navigation).
const QUICK_GROUPS: { heading: string; items: DrawerItem[] }[] = [
  { heading: "Front desk", items: FRONT_DESK },
  { heading: "Look up", items: LOOKUPS },
  { heading: "Briefings", items: BRIEFINGS },
];

interface Props {
  open: boolean;
  tab: Tab;
  onNavigate: (tab: Tab) => void;
  onChatAction: (action: ChatAction) => void;
  onClose: () => void;
}

export default function AppDrawer({ open, tab, onNavigate, onChatAction, onClose }: Props) {
  return (
    <>
      {open && <div className="app-drawer-backdrop" onClick={onClose} />}
      <aside className={`app-drawer${open ? " open" : ""}`} aria-hidden={!open}>
        <div className="app-drawer-head">
          <div className="app-drawer-brand">
            <span className="brand-mark">✓</span>
            <span className="app-drawer-title">Rep Assist</span>
          </div>
          <button className="app-drawer-close" onClick={onClose} aria-label="Close menu" title="Close menu">✕</button>
        </div>

        <nav className="app-drawer-scroll">
          {NAV_GROUPS.map((g) => (
            <div key={g.heading} className="drawer-group">
              <div className="drawer-subhead">{g.heading}</div>
              {g.items.map((it) => (
                <button
                  key={it.tab}
                  className={`drawer-nav-item${tab === it.tab ? " active" : ""}`}
                  onClick={() => onNavigate(it.tab)}
                >
                  <span className="drawer-nav-icon">{it.icon}</span>
                  <span className="drawer-nav-label">{it.label}</span>
                </button>
              ))}
            </div>
          ))}

          <div className="drawer-divider" />
          <div className="drawer-quick-label">Quick start</div>

          {QUICK_GROUPS.map((g) => (
            <div key={g.heading} className="drawer-group">
              <div className="drawer-subhead">{g.heading}</div>
              <div className="cta-tiles">
                {g.items.map((it) => (
                  <button
                    key={it.label}
                    className={`cta-tile${it.chevron ? " cta-tile--lookup" : ""}`}
                    onClick={() => onChatAction(it.action)}
                  >
                    <span className="cta-tile-icon">{it.icon}</span>
                    <span className="cta-tile-label">{it.label}</span>
                    {it.chevron && <span className="cta-tile-chevron">›</span>}
                  </button>
                ))}
              </div>
            </div>
          ))}

          <button className="reset" onClick={() => onChatAction({ kind: "reset" })}>↺ New conversation</button>
        </nav>
      </aside>
    </>
  );
}
