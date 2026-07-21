// Shared definitions for the chat quick-actions shown in the global nav drawer
// (AppDrawer) and dispatched into ChatWidget. Kept in one place so the drawer
// and the chat stay in sync.

export type LookupKind = "orders" | "tickets" | "system" | "huddle" | "queue";

// A quick-action the drawer asks the chat to perform. ChatWidget maps each kind
// to its existing handler (send / showLookup / showCoaching / check-in / reset /
// assist a queued customer / run a demo).
export type ChatAction =
  | { kind: "prompt"; value: string }
  | { kind: "lookup"; value: LookupKind }
  | { kind: "coaching" }
  | { kind: "checkin" }
  | { kind: "assist"; entry: QueueAssistTarget }
  | { kind: "demos" }
  | { kind: "reset" };

// The minimal customer identity the chat needs to start assisting a queued
// customer picked from the Live Queue tray.
export interface QueueAssistTarget {
  id: string;
  customer_name: string | null;
  customer_phone: string | null;
  reason: string;
  reason_label: string;
  account_id: string | null;
  order_id?: string | null;
}

export interface DrawerItem {
  icon: string;
  label: string;
  action: ChatAction;
  chevron?: boolean; // reveals a card/panel rather than sending a message
}

export const FRONT_DESK: DrawerItem[] = [
  { icon: "📝", label: "Check In", action: { kind: "checkin" } },
  { icon: "🧑‍🤝‍🧑", label: "View queue", action: { kind: "lookup", value: "queue" }, chevron: true },
  { icon: "🎯", label: "Coaching", action: { kind: "coaching" }, chevron: true },
];

export const LOOKUPS: DrawerItem[] = [
  { icon: "📦", label: "Recent orders", action: { kind: "lookup", value: "orders" }, chevron: true },
  { icon: "🎫", label: "My open tickets", action: { kind: "lookup", value: "tickets" }, chevron: true },
];

// Briefings — MCP-backed informational cards.
export const BRIEFINGS: DrawerItem[] = [
  { icon: "✨", label: "System enhancements", action: { kind: "lookup", value: "system" }, chevron: true },
  { icon: "🚀", label: "The Opener", action: { kind: "lookup", value: "huddle" }, chevron: true },
];
