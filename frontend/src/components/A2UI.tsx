import type { A2UIElement, A2UIOpenTickets, A2UIOrder, A2UIRecentOrders, A2UITicket } from "../types";

/**
 * A2UI (agent-to-UI) renderer.
 *
 * Maps each structured UI element (emitted by an MCP tool) to a React component.
 * Add a case here as new element `type`s are introduced — the transport, chat
 * wiring, and styling stay unchanged.
 */
export function A2UIRenderer({
  elements,
  onAction,
}: {
  elements: A2UIElement[];
  onAction: (prompt: string) => void;
}) {
  return (
    <>
      {elements.map((el, i) => {
        switch (el.type) {
          case "recent_orders":
            return <RecentOrdersCard key={i} el={el} onAction={onAction} />;
          case "open_tickets":
            return <OpenTicketsCard key={i} el={el} onAction={onAction} />;
          default:
            return null; // unknown element types are ignored, not fatal
        }
      })}
    </>
  );
}

function RecentOrdersCard({
  el,
  onAction,
}: {
  el: A2UIRecentOrders;
  onAction: (prompt: string) => void;
}) {
  return (
    <div className="a2ui-card">
      <div className="a2ui-card-head">
        <span className="a2ui-card-eyebrow">✦ Suggested</span>
        <h4 className="a2ui-card-title">{el.title}</h4>
        {el.subtitle && <p className="a2ui-card-sub">{el.subtitle}</p>}
      </div>
      <div className="a2ui-orders">
        {el.orders.map((o) => (
          <OrderRow key={o.order_id} order={o} onAction={onAction} />
        ))}
      </div>
    </div>
  );
}

function OrderRow({
  order,
  onAction,
}: {
  order: A2UIOrder;
  onAction: (prompt: string) => void;
}) {
  const meta = [order.order_type, order.device].filter(Boolean).join(" · ");
  return (
    <button
      className="a2ui-order"
      onClick={() => onAction(order.prompt)}
      title={`Start working on ${order.order_id}`}
    >
      <div className="a2ui-order-top">
        <span className="a2ui-order-id">{order.order_id}</span>
        <span className={`a2ui-status a2ui-status--${order.status_tone}`}>{order.status}</span>
      </div>
      {meta && <div className="a2ui-order-meta">{meta}</div>}
      <div className="a2ui-order-foot">
        <span className="a2ui-order-cust">
          {order.customer ?? order.account_id ?? "—"}
          <span className="a2ui-order-time"> · {order.opened_label}</span>
        </span>
        <span className="a2ui-order-cta">Open →</span>
      </div>
    </button>
  );
}

function OpenTicketsCard({
  el,
  onAction,
}: {
  el: A2UIOpenTickets;
  onAction: (prompt: string) => void;
}) {
  return (
    <div className="a2ui-card">
      <div className="a2ui-card-head">
        <span className="a2ui-card-eyebrow">✦ Suggested</span>
        <h4 className="a2ui-card-title">{el.title}</h4>
        {el.subtitle && <p className="a2ui-card-sub">{el.subtitle}</p>}
      </div>
      <div className="a2ui-orders">
        {el.tickets.map((t) => (
          <TicketRow key={t.ticket_id} ticket={t} onAction={onAction} />
        ))}
      </div>
    </div>
  );
}

function TicketRow({
  ticket,
  onAction,
}: {
  ticket: A2UITicket;
  onAction: (prompt: string) => void;
}) {
  return (
    <button
      className="a2ui-order"
      onClick={() => onAction(ticket.prompt)}
      title={`Work ticket ${ticket.ticket_id}`}
    >
      <div className="a2ui-order-top">
        <span className="a2ui-order-id">{ticket.ticket_id}</span>
        <span className={`a2ui-pri a2ui-pri--${ticket.priority}`}>{ticket.priority}</span>
      </div>
      <div className="a2ui-ticket-sum">{ticket.summary}</div>
      <div className="a2ui-order-foot">
        <span className="a2ui-order-cust">
          <span className={`a2ui-dot a2ui-dot--${ticket.status_tone}`} />
          {ticket.status_label}
          <span className="a2ui-order-time">&nbsp;· {ticket.age_label}</span>
        </span>
        <span className="a2ui-order-cta">Open →</span>
      </div>
    </button>
  );
}
