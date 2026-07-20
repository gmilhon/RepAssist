// Shared definitions for the chat quick-actions shown in the global nav drawer
// (AppDrawer) and dispatched into ChatWidget. Kept in one place so the drawer
// and the chat stay in sync.

export type LookupKind = "orders" | "tickets" | "system" | "huddle" | "queue";

// A quick-action the drawer asks the chat to perform. ChatWidget maps each kind
// to its existing handler (send / showLookup / showCoaching / check-in / reset).
export type ChatAction =
  | { kind: "prompt"; value: string }
  | { kind: "lookup"; value: LookupKind }
  | { kind: "coaching" }
  | { kind: "checkin" }
  | { kind: "reset" };

export interface DrawerItem {
  icon: string;
  label: string;
  action: ChatAction;
  chevron?: boolean; // reveals a card/panel rather than sending a message
}

// First-step CTAs — tapping one sends a starter prompt; the assistant then asks
// for the specifics it needs (order/account id).
export const FIRST_STEPS: DrawerItem[] = [
  { icon: "⚡", label: "Fix an activation", action: { kind: "prompt", value: "I have a line stuck in activation that I need to fix." } },
  { icon: "🔓", label: "Unblock an order", action: { kind: "prompt", value: "A customer's order is blocked and I need to release it." } },
  { icon: "🏷️", label: "Apply a promo", action: { kind: "prompt", value: "A promo didn't apply to a customer's account." } },
  { icon: "💵", label: "Explain a charge", action: { kind: "prompt", value: "I need help explaining a charge on the customer's bill." } },
  { icon: "🎁", label: "Request a credit", action: { kind: "prompt", value: "The customer is requesting a bill credit." } },
];

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
