import { useState } from "react";
import type {
  A2UIAccountSummary,
  A2UIOrderConfirmation,
  A2UICoaching,
  A2UICoachingEntry,
  A2UIElement,
  A2UIEnhancement,
  A2UIKnowledgeArticle,
  A2UILiveSuggestion,
  A2UIMorningHuddle,
  A2UIOpenTickets,
  A2UIOrder,
  A2UIQueue,
  A2UIQueueEntry,
  A2UIRecentOrders,
  A2UISystemEnhancements,
  A2UITicket,
} from "../types";

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
  onOpenArticle,
  onAssist,
  onCoach,
  onWalkthrough,
  actionsDisabled = false,
}: {
  elements: A2UIElement[];
  onAction: (prompt: string, entities?: Record<string, string>) => void;
  onOpenArticle?: (articleId: string) => void;
  onAssist?: (entry: A2UIQueueEntry) => void;
  onCoach?: (entry: A2UICoachingEntry) => void;
  onWalkthrough?: (e: A2UIEnhancement) => void;
  actionsDisabled?: boolean;
}) {
  return (
    <>
      {elements.map((el, i) => {
        switch (el.type) {
          case "recent_orders":
            return <RecentOrdersCard key={i} el={el} onAction={onAction} />;
          case "open_tickets":
            return <OpenTicketsCard key={i} el={el} onAction={onAction} />;
          case "system_enhancements":
            return <SystemEnhancementsCard key={i} el={el} onAction={onAction} onWalkthrough={onWalkthrough} />;
          case "morning_huddle":
            return <MorningHuddleCard key={i} el={el} onOpenArticle={onOpenArticle} />;
          case "knowledge_article":
            return <KnowledgeArticleCard key={i} el={el} />;
          case "queue":
            return <QueueCard key={i} el={el} onAssist={onAssist} />;
          case "live_suggestion":
            return <LiveSuggestionCard key={i} el={el} onAction={onAction} disabled={actionsDisabled} />;
          case "coaching":
            return <CoachingListCard key={i} el={el} onCoach={onCoach} disabled={actionsDisabled} />;
          case "account_summary":
            return <AccountSummaryCard key={i} el={el} onAction={onAction} disabled={actionsDisabled} />;
          case "order_confirmation":
            return <OrderConfirmationCard key={i} el={el} />;
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
  onAction: (prompt: string, entities?: Record<string, string>) => void;
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
  onAction: (prompt: string, entities?: Record<string, string>) => void;
}) {
  const meta = [order.order_type, order.device].filter(Boolean).join(" · ");
  const entities: Record<string, string> = {};
  if (order.order_id) entities.order_id = order.order_id;
  if (order.account_id) entities.account_id = order.account_id;
  return (
    <button
      className="a2ui-order"
      onClick={() => onAction(order.prompt, entities)}
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
  onAction: (prompt: string, entities?: Record<string, string>) => void;
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
  onAction: (prompt: string, entities?: Record<string, string>) => void;
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

function SystemEnhancementsCard({
  el,
  onAction,
  onWalkthrough,
}: {
  el: A2UISystemEnhancements;
  onAction: (prompt: string, entities?: Record<string, string>) => void;
  onWalkthrough?: (e: A2UIEnhancement) => void;
}) {
  return (
    <div className="a2ui-card">
      <div className="a2ui-card-head">
        <span className="a2ui-card-eyebrow">✦ What's new</span>
        <h4 className="a2ui-card-title">{el.title}</h4>
        {el.subtitle && <p className="a2ui-card-sub">{el.subtitle}</p>}
      </div>
      <ul className="a2ui-enh-list">
        {el.enhancements.map((e) => (
          <li key={e.title} className="a2ui-enh">
            <span className={`a2ui-enh-tag a2ui-enh-tag--${e.tag.toLowerCase()}`}>{e.tag}</span>
            <div className="a2ui-enh-body">
              <div className="a2ui-enh-title">{e.title}</div>
              <div className="a2ui-enh-detail">{e.detail}</div>
              {(e.walkthrough?.steps.length || e.gif_url || e.video_url) && (
                <div className="a2ui-enh-actions">
                  <button className="a2ui-enh-how" onClick={() => onWalkthrough?.(e)}>
                    📖 Show me how{e.gif_url ? " 🎞" : ""}{e.video_url ? " ▶" : ""} →
                  </button>
                </div>
              )}
            </div>
          </li>
        ))}
      </ul>
      {el.suggestions.length > 0 && (
        <div className="a2ui-ask">
          <span className="a2ui-ask-label">Ask about these:</span>
          <div className="a2ui-ask-chips">
            {el.suggestions.map((q) => (
              <button key={q} className="a2ui-ask-chip" onClick={() => onAction(q)}>
                {q}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function MorningHuddleCard({
  el,
  onOpenArticle,
}: {
  el: A2UIMorningHuddle;
  onOpenArticle?: (articleId: string) => void;
}) {
  const [done, setDone] = useState<Set<number>>(new Set());
  const toggle = (i: number) =>
    setDone((prev) => {
      const n = new Set(prev);
      n.has(i) ? n.delete(i) : n.add(i);
      return n;
    });

  return (
    <div className="a2ui-card">
      <div className="a2ui-card-head">
        <span className="a2ui-card-eyebrow">🚀 Start of shift</span>
        <h4 className="a2ui-card-title">{el.title}</h4>
        {el.subtitle && <p className="a2ui-card-sub">{el.subtitle}</p>}
      </div>

      {el.todos.length > 0 && (
        <div className="a2ui-todo-block">
          <div className="a2ui-section-label">✅ To-Do</div>
          <ul className="a2ui-todo-list">
            {el.todos.map((t, i) => (
              <li key={i} className={`a2ui-todo${done.has(i) ? " is-done" : ""}`}>
                <button className="a2ui-todo-check" onClick={() => toggle(i)} aria-label="Toggle done">
                  {done.has(i) ? "☑" : "☐"}
                </button>
                <div className="a2ui-todo-body">
                  <div className="a2ui-todo-title">{t.title}</div>
                  {t.detail && <div className="a2ui-todo-detail">{t.detail}</div>}
                  {t.article_id && onOpenArticle && (
                    <button className="a2ui-news-link" onClick={() => onOpenArticle(t.article_id!)}>
                      Open guide →
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      {el.items.length > 0 && (
        <>
          <div className="a2ui-section-label">📣 Field news</div>
          <ul className="a2ui-news-list">
            {el.items.map((n, i) => (
              <li key={i} className="a2ui-news">
                <span className={`a2ui-news-cat a2ui-news-cat--${n.tone}`}>{n.category}</span>
                <div className="a2ui-news-body">
                  <div className="a2ui-news-title">{n.title}</div>
                  <div className="a2ui-news-blurb">{n.blurb}</div>
                  {n.article_id && onOpenArticle && (
                    <button className="a2ui-news-link" onClick={() => onOpenArticle(n.article_id!)}>
                      Read article →
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

function QueueCard({
  el,
  onAssist,
}: {
  el: A2UIQueue;
  onAssist?: (entry: A2UIQueueEntry) => void;
}) {
  return (
    <div className="a2ui-card">
      <div className="a2ui-card-head">
        <span className="a2ui-card-eyebrow">🧑‍🤝‍🧑 Store queue</span>
        <h4 className="a2ui-card-title">{el.title}</h4>
        {el.subtitle && <p className="a2ui-card-sub">{el.subtitle}</p>}
      </div>
      {el.entries.length === 0 ? (
        <p className="a2ui-empty">No one's checked in right now.</p>
      ) : (
        <div className="a2ui-orders">
          {el.entries.map((e) => (
            <QueueRow key={e.id} entry={e} onAssist={onAssist} />
          ))}
        </div>
      )}
    </div>
  );
}

function QueueRow({
  entry,
  onAssist,
}: {
  entry: A2UIQueueEntry;
  onAssist?: (entry: A2UIQueueEntry) => void;
}) {
  const inProgress = entry.status === "in_progress";
  const scheduled = entry.status === "scheduled";
  const disabled = inProgress || scheduled;
  const showBothIdentifiers = Boolean(entry.customer_phone && entry.customer_name);
  const pillKind = scheduled ? "scheduled" : inProgress ? "progress" : "waiting";
  const pillLabel = scheduled ? "Upcoming" : inProgress ? "Being helped" : "Waiting";
  return (
    <button
      className="a2ui-order"
      disabled={disabled}
      onClick={() => !disabled && onAssist?.(entry)}
      title={
        scheduled ? `Appointment at ${entry.when_label ?? "later today"}`
        : inProgress ? "Already being helped"
        : `Assist ${entry.customer_name ?? entry.customer_phone}`
      }
    >
      <div className="a2ui-order-top">
        <span className="a2ui-order-id">{entry.customer_name ?? entry.customer_phone ?? "Customer"}</span>
        <span className={`a2ui-queue-pill a2ui-queue-pill--${pillKind}`}>{pillLabel}</span>
      </div>
      <div className="a2ui-order-meta">{entry.reason_label}</div>
      {entry.opportunities && entry.opportunities.length > 0 && (
        <div className="a2ui-opps">
          {entry.opportunities.map((o) => (
            <span key={o} className="a2ui-opp-badge">💡 {o}</span>
          ))}
        </div>
      )}
      <div className="a2ui-order-foot">
        <span className="a2ui-order-cust">
          {showBothIdentifiers ? entry.customer_phone : ""}
          <span className="a2ui-order-time">
            {showBothIdentifiers ? " · " : ""}
            {scheduled
              ? `Today ${entry.when_label ?? ""}`
              : `${entry.wait_label} ${inProgress ? "in" : "waiting"}`}
          </span>
        </span>
        <span className="a2ui-order-cta">
          {scheduled ? "Scheduled" : inProgress ? "In progress" : "Assist →"}
        </span>
      </div>
    </button>
  );
}

export function Stars({ value }: { value: number }) {
  const n = Math.max(0, Math.min(5, Math.round(value)));
  return (
    <span className="stars" aria-label={`${n} out of 5`}>
      {[1, 2, 3, 4, 5].map((i) => (
        <span key={i} className={i <= n ? "star on" : "star"}>★</span>
      ))}
    </span>
  );
}

function CoachingListCard({
  el,
  onCoach,
  disabled = false,
}: {
  el: A2UICoaching;
  onCoach?: (entry: A2UICoachingEntry) => void;
  disabled?: boolean;
}) {
  return (
    <div className="a2ui-card">
      <div className="a2ui-card-head">
        <span className="a2ui-card-eyebrow">🎯 Coaching</span>
        <h4 className="a2ui-card-title">{el.title}</h4>
        {el.subtitle && <p className="a2ui-card-sub">{el.subtitle}</p>}
      </div>
      {el.entries.length === 0 ? (
        <p className="a2ui-empty">No graded visits yet — finish a Live Listen to see coaching.</p>
      ) : (
        <div className="a2ui-orders">
          {el.entries.map((e) => (
            <button
              key={e.session_id}
              className="a2ui-order"
              disabled={disabled}
              onClick={() => onCoach?.(e)}
              title={`Coaching for ${e.customer_name}`}
            >
              <div className="a2ui-order-top">
                <span className="a2ui-order-id">{e.customer_name}</span>
                <Stars value={e.stars} />
              </div>
              <div className="a2ui-order-meta">{e.reason_label}</div>
              <div className="a2ui-order-foot">
                <span className="a2ui-order-cust">
                  <span className="a2ui-order-time">{e.when_label}</span>
                </span>
                <span className="a2ui-order-cta">{e.has_coaching ? "View coaching →" : "Coach me →"}</span>
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function LiveSuggestionCard({
  el,
  onAction,
  disabled = false,
}: {
  el: A2UILiveSuggestion;
  onAction: (prompt: string, entities?: Record<string, string>) => void;
  disabled?: boolean;
}) {
  return (
    <div className="a2ui-card a2ui-suggest">
      <div className="a2ui-card-head">
        <span className="a2ui-card-eyebrow">🎧 Live listen</span>
        <div className="a2ui-suggest-top">
          <h4 className="a2ui-card-title">{el.title}</h4>
          <span className={`a2ui-status a2ui-status--${el.tone}`}>{el.intent.replace("_", " ")}</span>
        </div>
        <p className="a2ui-card-sub">{el.summary}</p>
      </div>
      {el.diagnosis && el.diagnosis.root_cause && (
        <div className="a2ui-suggest-diag">
          <div><b>Diagnosis</b>{el.diagnosis.root_cause}</div>
          {el.diagnosis.can_resolve && el.diagnosis.human_prompt && (
            <div><b>Proposed</b>{el.diagnosis.human_prompt}</div>
          )}
        </div>
      )}
      <div className="a2ui-suggest-foot">
        <span className="a2ui-suggest-meta">
          <span className="tag muted-tag">{el.capability}</span>
          <span className="a2ui-suggest-conf">{Math.round(el.confidence * 100)}% match</span>
        </span>
        <button
          className="btn primary small"
          onClick={() => onAction(el.prompt, el.entities)}
          disabled={disabled}
        >
          Ask Rep Assist
        </button>
      </div>
    </div>
  );
}

function KnowledgeArticleCard({ el }: { el: A2UIKnowledgeArticle }) {
  return (
    <div className="a2ui-card a2ui-article">
      <div className="a2ui-card-head">
        <span className="a2ui-card-eyebrow">📄 {el.source}</span>
        <h4 className="a2ui-card-title">{el.title}</h4>
        <div className="a2ui-article-meta">
          <span className="a2ui-article-cat">{el.category}</span>
          <span className="a2ui-article-id">{el.article_id}</span>
          <span className="a2ui-article-updated">{el.updated_label}</span>
        </div>
        {el.summary && <p className="a2ui-card-sub">{el.summary}</p>}
      </div>
      <div className="a2ui-article-sections">
        {el.sections.map((s, i) => (
          <div key={i} className="a2ui-article-section">
            <div className="a2ui-article-heading">{s.heading}</div>
            <p className="a2ui-article-body">{s.body}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

const DEVICE_ICON: Record<string, string> = { phone: "📱", tablet: "▨", watch: "⌚" };

function AccountSummaryCard({ el, onAction, disabled }: {
  el: A2UIAccountSummary;
  onAction: (prompt: string, entities?: Record<string, string>) => void;
  disabled?: boolean;
}) {
  const elig = el.eligibility;
  const opps: string[] = [];
  if (elig.upgrade_promo) opps.push(elig.upgrade_promo);
  if (elig.fiber_eligible) opps.push("Fiber Home Internet eligible");
  if (elig.fwa_eligible) opps.push("Fixed Wireless eligible");
  return (
    <div className="a2ui-card a2ui-account">
      <div className="a2ui-card-head">
        <span className="a2ui-card-eyebrow">👤 Account{el.account_id ? ` · ${el.account_id}` : ""}</span>
        <h4 className="a2ui-card-title">
          {el.name}
          {el.tenure_months ? <span className="a2ui-account-tenure"> · {el.tenure_months} mo tenure</span> : null}
        </h4>
      </div>
      <div className="a2ui-account-lines">
        {el.lines.map((ln) => (
          <div key={ln.line_id} className="a2ui-account-line">
            <span className="a2ui-account-dev-icon">{DEVICE_ICON[ln.device_type] ?? "📱"}</span>
            <div className="a2ui-account-line-main">
              <div className="a2ui-account-dev">
                {ln.device}
                {ln.upgrade_eligible && <span className="a2ui-account-upgrade">Upgrade eligible</span>}
              </div>
              <div className="a2ui-account-line-sub">{ln.phone} · {ln.plan}</div>
            </div>
          </div>
        ))}
        {el.home_internet && (
          <div className="a2ui-account-line">
            <span className="a2ui-account-dev-icon">🏠</span>
            <div className="a2ui-account-line-main">
              <div className="a2ui-account-dev">{el.home_internet.name}</div>
              <div className="a2ui-account-line-sub">Home internet</div>
            </div>
          </div>
        )}
      </div>
      {opps.length > 0 && (
        <div className="a2ui-account-opps">
          <span className="a2ui-account-opps-label">💡 Opportunities</span>
          {opps.map((o, i) => <span key={i} className="a2ui-account-opp">{o}</span>)}
        </div>
      )}
      <div className="a2ui-account-actions">
        <button className="btn small" disabled={disabled} onClick={() => onAction("I'd like to add a new line for this customer.")}>
          + Add a line
        </button>
        <button className="btn ghost small" disabled={disabled} onClick={() => onAction("Let's upgrade a line for this customer.")}>
          ⇪ Upgrade a line
        </button>
      </div>
    </div>
  );
}

function OrderConfirmationCard({ el }: { el: A2UIOrderConfirmation }) {
  return (
    <div className="a2ui-card a2ui-order">
      <div className="a2ui-order-head">
        <span className="a2ui-order-check">✓</span>
        <div>
          <div className="a2ui-order-title">Order placed</div>
          <div className="a2ui-order-id">{el.order_id}</div>
        </div>
      </div>
      <div className="a2ui-order-items">
        {el.items.map((it) => (
          <div key={it.item_id} className="a2ui-order-item">
            <span className="a2ui-order-item-name">
              {it.device ?? "Device"}{it.line_id ? ` · ${it.line_id}` : ""}
              <span className="a2ui-order-item-plan"> · {it.plan ?? "—"}</span>
            </span>
            <span className="a2ui-order-item-price">${it.monthly.toFixed(2)}/mo</span>
          </div>
        ))}
      </div>
      <div className="a2ui-order-total">
        <span>Monthly total</span>
        <span className="a2ui-order-total-amt">${el.monthly_total.toFixed(2)}/mo</span>
      </div>
      <div className="a2ui-order-pay">💳 Payment taken · {el.payment_method}{el.onetime_total ? ` · $${el.onetime_total.toFixed(2)} today` : ""}</div>
    </div>
  );
}
