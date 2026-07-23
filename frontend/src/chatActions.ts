// Shared definitions for the chat quick-actions shown in the global tray
// (AppTray) and dispatched into ChatWidget. Kept in one place so the tray
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
  | { kind: "scan_barcode" }   // open camera → read a UPC → look the product up
  | { kind: "scan_bill" }      // open camera → OCR a competitor bill → switch analysis
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

