import { useEffect, useState } from "react";
import { api } from "../api";
import type { EmailSettings, EmailSubscriber } from "../types";

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

  async function reload() {
    const [subs, settings] = await Promise.all([
      api.listSubscribers(),
      api.emailSettings(),
    ]);
    setSubscribers(subs);
    setSmtp(settings);
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

  const activeCount = subscribers.filter(s => s.active).length;

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
    </div>
  );
}
