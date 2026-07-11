import { useEffect, useState } from "react";
import { api } from "../api";
import type { EmailSettings, EmailSubscriber, HuddleItem, OSTArticleRef } from "../types";

const HUDDLE_CATEGORIES = ["To-Do", "Promo", "Device", "Policy", "Network", "News"];

export default function SettingsPage() {
  const [subscribers, setSubscribers] = useState<EmailSubscriber[]>([]);
  const [smtp, setSmtp] = useState<EmailSettings | null>(null);
  const [loading, setLoading] = useState(true);

  // Add form state
  const [addEmail, setAddEmail] = useState("");
  const [addName, setAddName] = useState("");
  const [addPerf, setAddPerf] = useState(true);
  const [addCX, setAddCX] = useState(true);
  const [addError, setAddError] = useState("");
  const [adding, setAdding] = useState(false);

  // Morning Huddle state
  const [huddle, setHuddle] = useState<HuddleItem[]>([]);
  const [articles, setArticles] = useState<OSTArticleRef[]>([]);
  const [hCategory, setHCategory] = useState("Promo");
  const [hTitle, setHTitle] = useState("");
  const [hBlurb, setHBlurb] = useState("");
  const [hArticle, setHArticle] = useState("");
  const [hError, setHError] = useState("");
  const [hAdding, setHAdding] = useState(false);

  async function reload() {
    const [subs, settings, hItems, arts] = await Promise.all([
      api.listSubscribers(),
      api.emailSettings(),
      api.listHuddleItems(),
      api.listHuddleArticles(),
    ]);
    setSubscribers(subs);
    setSmtp(settings);
    setHuddle(hItems);
    setArticles(arts);
    setLoading(false);
  }

  useEffect(() => { reload(); }, []);

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    if (!addEmail.trim()) return;
    setAdding(true);
    setAddError("");
    try {
      await api.addSubscriber(addEmail.trim(), addName.trim(), addPerf, addCX);
      setAddEmail("");
      setAddName("");
      setAddPerf(true);
      setAddCX(true);
      await reload();
    } catch (err: any) {
      setAddError(err.message ?? "Failed to add subscriber");
    } finally {
      setAdding(false);
    }
  }

  async function handleToggle(sub: EmailSubscriber, field: "subscribed_performance" | "subscribed_cx" | "active") {
    await api.updateSubscriber(sub.email, { [field]: !sub[field] });
    await reload();
  }

  async function handleRemove(email: string) {
    await api.removeSubscriber(email);
    await reload();
  }

  async function handleAddHuddle(e: React.FormEvent) {
    e.preventDefault();
    if (!hTitle.trim()) return;
    setHAdding(true);
    setHError("");
    try {
      await api.addHuddleItem({
        category: hCategory,
        title: hTitle.trim(),
        blurb: hBlurb.trim(),
        article_id: hArticle || null,
      });
      setHTitle("");
      setHBlurb("");
      setHArticle("");
      await reload();
    } catch (err: any) {
      setHError(err.message ?? "Failed to add item");
    } finally {
      setHAdding(false);
    }
  }

  async function handleToggleHuddle(item: HuddleItem) {
    await api.updateHuddleItem(item.id, { active: !item.active });
    await reload();
  }

  async function handleRemoveHuddle(id: number) {
    await api.removeHuddleItem(id);
    await reload();
  }

  const activeCount = subscribers.filter(s => s.active).length;
  const articleTitle = (id: string | null) =>
    id ? (articles.find(a => a.article_id === id)?.title ?? id) : null;

  return (
    <div className="settings-page">
      <div className="settings-header">
        <h2 className="settings-title">Settings</h2>
      </div>

      {/* ── Email Reports ────────────────────────────────────────────── */}
      <div className="settings-section">
        <div className="settings-section-head">
          <h3 className="settings-section-title">Email Reports</h3>
          <p className="settings-section-sub">
            Subscribers receive HTML reports when you click <strong>Send Report</strong> on the
            Performance or CX Monitor tabs. Reports can also be sent without SMTP configured —
            the button will show an in-browser preview instead.
          </p>
        </div>

        {/* SMTP status */}
        {smtp && (
          <div className={`settings-smtp-badge ${smtp.smtp_enabled ? "is-live" : "is-off"}`}>
            <span className="settings-smtp-dot" />
            {smtp.smtp_enabled
              ? <>SMTP connected · <strong>{smtp.smtp_host}</strong>:{smtp.smtp_port} · {smtp.smtp_user}</>
              : <>SMTP not configured — reports will show an in-browser preview.
                  Add <code>SMTP_HOST</code>, <code>SMTP_USER</code>, <code>SMTP_PASSWORD</code> to{" "}
                  <code>backend/.env</code> to enable real email delivery.</>}
          </div>
        )}

        {/* Subscriber table */}
        {loading ? (
          <div className="settings-loading">Loading subscribers…</div>
        ) : (
          <>
            <div className="settings-sub-header">
              <span className="settings-sub-count">
                {activeCount} active subscriber{activeCount !== 1 ? "s" : ""}
              </span>
            </div>

            {subscribers.length === 0 ? (
              <div className="settings-empty">No subscribers yet. Add one below.</div>
            ) : (
              <div className="settings-table-wrap">
                <table className="settings-table">
                  <thead>
                    <tr>
                      <th>Email</th>
                      <th>Name</th>
                      <th title="Performance dashboard reports">Performance</th>
                      <th title="CX Monitor reports">CX Monitor</th>
                      <th>Active</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {subscribers.map(sub => (
                      <tr key={sub.email} className={sub.active ? "" : "settings-row-inactive"}>
                        <td className="settings-email">{sub.email}</td>
                        <td className="settings-name">{sub.name ?? <span className="settings-none">—</span>}</td>
                        <td>
                          <button
                            className={`settings-toggle ${sub.subscribed_performance ? "on" : "off"}`}
                            onClick={() => handleToggle(sub, "subscribed_performance")}
                            title={sub.subscribed_performance ? "Unsubscribe from Performance reports" : "Subscribe to Performance reports"}
                          >
                            {sub.subscribed_performance ? "On" : "Off"}
                          </button>
                        </td>
                        <td>
                          <button
                            className={`settings-toggle ${sub.subscribed_cx ? "on" : "off"}`}
                            onClick={() => handleToggle(sub, "subscribed_cx")}
                            title={sub.subscribed_cx ? "Unsubscribe from CX reports" : "Subscribe to CX reports"}
                          >
                            {sub.subscribed_cx ? "On" : "Off"}
                          </button>
                        </td>
                        <td>
                          <button
                            className={`settings-toggle ${sub.active ? "on" : "off"}`}
                            onClick={() => handleToggle(sub, "active")}
                          >
                            {sub.active ? "Active" : "Paused"}
                          </button>
                        </td>
                        <td>
                          <button
                            className="settings-remove"
                            onClick={() => handleRemove(sub.email)}
                            title="Remove subscriber"
                          >
                            ✕
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* Add subscriber form */}
            <form className="settings-add-form" onSubmit={handleAdd}>
              <h4 className="settings-add-title">Add subscriber</h4>
              <div className="settings-add-row">
                <input
                  type="email"
                  className="settings-input"
                  placeholder="email@example.com"
                  value={addEmail}
                  onChange={e => setAddEmail(e.target.value)}
                  required
                />
                <input
                  type="text"
                  className="settings-input settings-input--name"
                  placeholder="Name (optional)"
                  value={addName}
                  onChange={e => setAddName(e.target.value)}
                />
                <label className="settings-check">
                  <input type="checkbox" checked={addPerf} onChange={e => setAddPerf(e.target.checked)} />
                  Performance
                </label>
                <label className="settings-check">
                  <input type="checkbox" checked={addCX} onChange={e => setAddCX(e.target.checked)} />
                  CX Monitor
                </label>
                <button type="submit" className="btn" disabled={adding}>
                  {adding ? "Adding…" : "Add"}
                </button>
              </div>
              {addError && <div className="settings-add-error">{addError}</div>}
            </form>
          </>
        )}
      </div>

      {/* ── The Opener ───────────────────────────────────────────────── */}
      <div className="settings-section">
        <div className="settings-section-head">
          <h3 className="settings-section-title">The Opener</h3>
          <p className="settings-section-sub">
            Curate the start-of-shift brief reps see in the chat under <strong>Briefings</strong> —
            To-Do items and field news. Items can link to a One Source of Truth article.
          </p>
        </div>

        {loading ? (
          <div className="settings-loading">Loading huddle…</div>
        ) : (
          <>
            <div className="settings-sub-header">
              <span className="settings-sub-count">
                {huddle.filter(h => h.active).length} active item{huddle.filter(h => h.active).length !== 1 ? "s" : ""}
              </span>
            </div>

            {huddle.length === 0 ? (
              <div className="settings-empty">No huddle items yet. Add one below.</div>
            ) : (
              <div className="settings-table-wrap">
                <table className="settings-table">
                  <thead>
                    <tr>
                      <th>Category</th>
                      <th>Title</th>
                      <th>Article</th>
                      <th>Active</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {huddle.map(item => (
                      <tr key={item.id} className={item.active ? "" : "settings-row-inactive"}>
                        <td><span className={`a2ui-news-cat a2ui-news-cat--${toneOf(item.category)}`}>{item.category}</span></td>
                        <td className="settings-email">{item.title}</td>
                        <td className="settings-name">
                          {item.article_id
                            ? <span title={articleTitle(item.article_id) ?? ""}>🔗 {item.article_id}</span>
                            : <span className="settings-none">—</span>}
                        </td>
                        <td>
                          <button
                            className={`settings-toggle ${item.active ? "on" : "off"}`}
                            onClick={() => handleToggleHuddle(item)}
                          >
                            {item.active ? "Active" : "Hidden"}
                          </button>
                        </td>
                        <td>
                          <button className="settings-remove" onClick={() => handleRemoveHuddle(item.id)} title="Remove item">✕</button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* Add huddle item form */}
            <form className="settings-add-form" onSubmit={handleAddHuddle}>
              <h4 className="settings-add-title">Add huddle item</h4>
              <div className="settings-add-row">
                <select className="settings-input settings-input--name" value={hCategory} onChange={e => setHCategory(e.target.value)}>
                  {HUDDLE_CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
                </select>
                <input
                  type="text"
                  className="settings-input"
                  placeholder="Headline"
                  value={hTitle}
                  onChange={e => setHTitle(e.target.value)}
                  required
                />
              </div>
              <div className="settings-add-row" style={{ marginTop: 8 }}>
                <input
                  type="text"
                  className="settings-input"
                  placeholder="Short blurb"
                  value={hBlurb}
                  onChange={e => setHBlurb(e.target.value)}
                />
                <select className="settings-input settings-input--name" value={hArticle} onChange={e => setHArticle(e.target.value)}>
                  <option value="">No article</option>
                  {articles.map(a => <option key={a.article_id} value={a.article_id}>{a.article_id} · {a.title}</option>)}
                </select>
                <button type="submit" className="btn" disabled={hAdding}>
                  {hAdding ? "Adding…" : "Add"}
                </button>
              </div>
              {hError && <div className="settings-add-error">{hError}</div>}
            </form>
          </>
        )}
      </div>
    </div>
  );
}

// category → the tone class used by the a2ui news-cat pill
function toneOf(category: string): string {
  return { "To-Do": "warn", Promo: "danger", Device: "info", Policy: "warn", Network: "ok", News: "info" }[category] ?? "info";
}
