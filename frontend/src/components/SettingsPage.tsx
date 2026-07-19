import { useEffect, useState } from "react";
import { api } from "../api";
import type { EmailSettings, EmailSubscriber, HuddleItem, OSTArticleRef, PlaybookGuideline, SystemHealth, TrainingEnhancement, VideoStoryboard } from "../types";

const HUDDLE_CATEGORIES = ["To-Do", "Promo", "Device", "Policy", "Network", "News"];
const PLAYBOOK_CATEGORIES = ["Customer Needs", "Sales Positioning"];

type SettingsSection = "health" | "email" | "playbook" | "training" | "opener";
const SETTINGS_SECTIONS: { key: SettingsSection; label: string; icon: string }[] = [
  { key: "health", label: "System Health", icon: "🩺" },
  { key: "email", label: "Email Reports", icon: "✉️" },
  { key: "playbook", label: "Playbook", icon: "📋" },
  { key: "training", label: "Training & Enablement", icon: "🎬" },
  { key: "opener", label: "The Opener", icon: "🚀" },
];

export default function SettingsPage({ onHealthChange }: { onHealthChange?: () => void }) {
  const [subscribers, setSubscribers] = useState<EmailSubscriber[]>([]);
  const [smtp, setSmtp] = useState<EmailSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [section, setSection] = useState<SettingsSection>("health");

  // Add form state
  const [addEmail, setAddEmail] = useState("");
  const [addName, setAddName] = useState("");
  const [addPerf, setAddPerf] = useState(true);
  const [addCX, setAddCX] = useState(true);
  const [addVisit, setAddVisit] = useState(true);
  const [addError, setAddError] = useState("");
  const [adding, setAdding] = useState(false);

  // System health state
  const [shStatus, setShStatus] = useState<SystemHealth["status"]>("operational");
  const [shDesc, setShDesc] = useState("");
  const [shWorkaround, setShWorkaround] = useState("");
  const [shHardStop, setShHardStop] = useState(false);
  const [shNotify, setShNotify] = useState(false);
  const [shSaving, setShSaving] = useState(false);
  const [shSaved, setShSaved] = useState(false);

  // Morning Huddle state
  const [huddle, setHuddle] = useState<HuddleItem[]>([]);
  const [articles, setArticles] = useState<OSTArticleRef[]>([]);
  const [hCategory, setHCategory] = useState("Promo");
  const [hTitle, setHTitle] = useState("");
  const [hBlurb, setHBlurb] = useState("");
  const [hArticle, setHArticle] = useState("");
  const [hError, setHError] = useState("");
  const [hAdding, setHAdding] = useState(false);

  // Playbook state
  const [guidelines, setGuidelines] = useState<PlaybookGuideline[]>([]);
  const [pgCategory, setPgCategory] = useState("Customer Needs");
  const [pgText, setPgText] = useState("");
  const [pgError, setPgError] = useState("");
  const [pgAdding, setPgAdding] = useState(false);

  // Training / Go-To-Channel state
  const [enhancements, setEnhancements] = useState<TrainingEnhancement[]>([]);
  const [storyboards, setStoryboards] = useState<Record<string, { generating: boolean; result: VideoStoryboard | null }>>({});
  const [copiedTitle, setCopiedTitle] = useState<string | null>(null);
  const [videoUploads, setVideoUploads] = useState<Record<string, { uploading: boolean; error: string }>>({});

  async function reload() {
    const [subs, settings, hItems, arts, sh, gls, enh] = await Promise.all([
      api.listSubscribers(),
      api.emailSettings(),
      api.listHuddleItems(),
      api.listHuddleArticles(),
      api.getSystemHealth(),
      api.listPlaybookGuidelines(),
      api.trainingEnhancements(),
    ]);
    setSubscribers(subs);
    setSmtp(settings);
    setHuddle(hItems);
    setArticles(arts);
    setShStatus(sh.status);
    setShDesc(sh.description);
    setShWorkaround(sh.workaround);
    setShHardStop(sh.hard_stop);
    setGuidelines(gls);
    setEnhancements(enh);
    setLoading(false);
  }

  async function makeStoryboard(e: TrainingEnhancement) {
    setStoryboards((s) => ({ ...s, [e.title]: { generating: true, result: s[e.title]?.result ?? null } }));
    try {
      const result = await api.generateStoryboard({
        title: e.title, detail: e.detail, answer: e.answer, walkthrough: e.walkthrough,
      });
      setStoryboards((s) => ({ ...s, [e.title]: { generating: false, result } }));
    } catch {
      setStoryboards((s) => ({ ...s, [e.title]: { generating: false, result: null } }));
    }
  }

  function storyboardText(sb: VideoStoryboard): string {
    const lines = [
      `TRAINING VIDEO STORYBOARD`,
      `Title: ${sb.title}`,
      `Audience: ${sb.audience}`,
      `Est. runtime: ${sb.total_duration_label}`,
      ``,
      ...sb.scenes.flatMap((sc) => [
        `Scene ${sc.scene} (${sc.duration_seconds}s)`,
        `  Visual: ${sc.visual}`,
        `  On-screen: ${sc.on_screen_text}`,
        `  Narration: ${sc.narration}`,
        ``,
      ]),
      `Call to action: ${sb.call_to_action}`,
    ];
    return lines.join("\n");
  }

  async function copyStoryboard(e: TrainingEnhancement, sb: VideoStoryboard) {
    try {
      await navigator.clipboard.writeText(storyboardText(sb));
      setCopiedTitle(e.title);
      setTimeout(() => setCopiedTitle((t) => (t === e.title ? null : t)), 2000);
    } catch { /* clipboard unavailable */ }
  }

  async function uploadVideo(e: TrainingEnhancement, file: File) {
    setVideoUploads((v) => ({ ...v, [e.title]: { uploading: true, error: "" } }));
    try {
      await api.uploadEnhancementVideo(e.title, file);
      await reload();
      setVideoUploads((v) => ({ ...v, [e.title]: { uploading: false, error: "" } }));
    } catch (err: any) {
      setVideoUploads((v) => ({ ...v, [e.title]: { uploading: false, error: err.message ?? "Upload failed" } }));
    }
  }

  async function removeVideo(e: TrainingEnhancement) {
    if (!e.video_url) return;
    const id = Number(e.video_url.split("/").pop());
    if (!Number.isFinite(id)) return;
    await api.deleteEnhancementVideo(id);
    await reload();
  }

  async function toggleHidden(e: TrainingEnhancement) {
    const next = !e.hidden;
    // Optimistic: flip locally, then persist (revert on failure).
    setEnhancements((list) => list.map((x) => (x.title === e.title ? { ...x, hidden: next } : x)));
    try {
      await api.setEnhancementHidden(e.title, next);
    } catch {
      setEnhancements((list) => list.map((x) => (x.title === e.title ? { ...x, hidden: !next } : x)));
    }
  }

  async function handleAddGuideline(e: React.FormEvent) {
    e.preventDefault();
    if (!pgText.trim()) return;
    setPgAdding(true);
    setPgError("");
    try {
      await api.addPlaybookGuideline(pgCategory, pgText.trim());
      setPgText("");
      await reload();
    } catch (err: any) {
      setPgError(err.message ?? "Failed to add guideline");
    } finally {
      setPgAdding(false);
    }
  }

  async function toggleGuideline(g: PlaybookGuideline) {
    await api.updatePlaybookGuideline(g.id, { active: !g.active });
    await reload();
  }

  async function removeGuideline(id: number) {
    await api.removePlaybookGuideline(id);
    await reload();
  }

  useEffect(() => { reload(); }, []);

  async function handleSaveHealth(e: React.FormEvent) {
    e.preventDefault();
    setShSaving(true);
    try {
      await api.setSystemHealth({ status: shStatus, description: shDesc, workaround: shWorkaround, hard_stop: shHardStop, notify: shNotify });
      setShNotify(false);
      setShSaved(true);
      onHealthChange?.();
      setTimeout(() => setShSaved(false), 2000);
    } finally {
      setShSaving(false);
    }
  }

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    if (!addEmail.trim()) return;
    setAdding(true);
    setAddError("");
    try {
      await api.addSubscriber(addEmail.trim(), addName.trim(), addPerf, addCX, addVisit);
      setAddEmail("");
      setAddName("");
      setAddPerf(true);
      setAddCX(true);
      setAddVisit(true);
      await reload();
    } catch (err: any) {
      setAddError(err.message ?? "Failed to add subscriber");
    } finally {
      setAdding(false);
    }
  }

  async function handleToggle(sub: EmailSubscriber, field: "subscribed_performance" | "subscribed_cx" | "subscribed_alerts" | "subscribed_visit_summary" | "active") {
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

      <div className="settings-layout">
        <nav className="settings-subnav">
          {SETTINGS_SECTIONS.map((s) => (
            <button
              key={s.key}
              className={`settings-subnav-item ${section === s.key ? "active" : ""}`}
              onClick={() => setSection(s.key)}
            >
              <span className="settings-subnav-icon">{s.icon}</span>
              <span>{s.label}</span>
            </button>
          ))}
        </nav>

        <div className="settings-panel">

      {/* ── System Health ────────────────────────────────────────────── */}
      {section === "health" && (
      <div className="settings-section">
        <div className="settings-section-head">
          <h3 className="settings-section-title">System Health</h3>
          <p className="settings-section-sub">
            Set the service status reps see in the health indicator. Use <strong>Degraded</strong> or{" "}
            <strong>Outage</strong> during incidents to surface a description and workaround.
            Enable <strong>Hard Stop</strong> to warn reps not to process new orders.
          </p>
        </div>

        <form className="settings-add-form sh-form" onSubmit={handleSaveHealth}>
          <div className="sh-status-row">
            {(["operational", "degraded", "outage"] as const).map(s => (
              <label key={s} className={`sh-status-option sh-status-option--${s}${shStatus === s ? " selected" : ""}`}>
                <input type="radio" name="sh-status" value={s} checked={shStatus === s} onChange={() => setShStatus(s)} />
                <span className={`sh-dot sh-dot--${s}`} />
                {s.charAt(0).toUpperCase() + s.slice(1)}
              </label>
            ))}
          </div>

          <label className="sh-label">Event description
            <textarea
              className="sh-textarea"
              placeholder="Describe the issue visible to reps (leave blank if operational)…"
              value={shDesc}
              onChange={e => setShDesc(e.target.value)}
              rows={2}
            />
          </label>

          <label className="sh-label">Workaround
            <textarea
              className="sh-textarea"
              placeholder="Steps reps can take while the issue is active…"
              value={shWorkaround}
              onChange={e => setShWorkaround(e.target.value)}
              rows={2}
            />
          </label>

          <div className="sh-checks-col">
            <label className="sh-hardstop-check">
              <input type="checkbox" checked={shHardStop} onChange={e => setShHardStop(e.target.checked)} />
              <span className="sh-hardstop-label">Hard stop — warn reps not to process new orders</span>
            </label>
            <label className="sh-hardstop-check">
              <input type="checkbox" checked={shNotify} onChange={e => setShNotify(e.target.checked)} />
              <span className="sh-hardstop-label">Notify active users when saved</span>
            </label>
          </div>
          <div className="sh-footer-row">
            <button type="submit" className="btn" disabled={shSaving}>
              {shSaved ? "Saved ✓" : shSaving ? "Saving…" : "Save"}
            </button>
          </div>
        </form>
      </div>

      )}

      {/* ── Email Reports ────────────────────────────────────────────── */}
      {section === "email" && (
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
                      <th title="Critical production-issue alerts">Alerts</th>
                      <th title="Live Listen visit-summary emails">Live Listen</th>
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
                            className={`settings-toggle ${sub.subscribed_alerts ? "on" : "off"}`}
                            onClick={() => handleToggle(sub, "subscribed_alerts")}
                            title={sub.subscribed_alerts ? "Unsubscribe from production alerts" : "Subscribe to production alerts"}
                          >
                            {sub.subscribed_alerts ? "On" : "Off"}
                          </button>
                        </td>
                        <td>
                          <button
                            className={`settings-toggle ${sub.subscribed_visit_summary ? "on" : "off"}`}
                            onClick={() => handleToggle(sub, "subscribed_visit_summary")}
                            title={sub.subscribed_visit_summary ? "Unsubscribe from Live Listen visit summaries" : "Subscribe to Live Listen visit summaries"}
                          >
                            {sub.subscribed_visit_summary ? "On" : "Off"}
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
                <label className="settings-check">
                  <input type="checkbox" checked={addVisit} onChange={e => setAddVisit(e.target.checked)} />
                  Live Listen
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

      )}

      {/* ── Playbook ─────────────────────────────────────────────────── */}
      {section === "playbook" && (
      <div className="settings-section">
        <div className="settings-section-head">
          <h3 className="settings-section-title">Playbook</h3>
          <p className="settings-section-sub">
            The standard every Live Listen visit is graded against. Guidelines cover meeting the
            customer's needs and positioning sales opportunities. Toggle or edit them to change how
            reps are scored and coached.
          </p>
        </div>
        {loading ? (
          <div className="settings-empty">Loading…</div>
        ) : (
          <>
            {PLAYBOOK_CATEGORIES.map((cat) => {
              const rows = guidelines.filter((g) => g.category === cat);
              return (
                <div key={cat} className="playbook-group">
                  <div className="playbook-group-title">{cat}</div>
                  {rows.length === 0 ? (
                    <div className="settings-empty">No guidelines in this group yet.</div>
                  ) : (
                    <ul className="playbook-list">
                      {rows.map((g) => (
                        <li key={g.id} className={`playbook-row ${g.active ? "" : "playbook-row--off"}`}>
                          <span className="playbook-text">{g.text}</span>
                          <span className="playbook-actions">
                            <button
                              className={`settings-toggle ${g.active ? "on" : "off"}`}
                              onClick={() => toggleGuideline(g)}
                              title={g.active ? "Disable (won't be graded)" : "Enable"}
                            >
                              {g.active ? "On" : "Off"}
                            </button>
                            <button className="settings-remove" onClick={() => removeGuideline(g.id)} title="Remove guideline">✕</button>
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              );
            })}

            <form className="settings-add-form" onSubmit={handleAddGuideline}>
              <h4 className="settings-add-title">Add guideline</h4>
              <div className="settings-add-row">
                <select className="settings-input settings-input--name" value={pgCategory} onChange={e => setPgCategory(e.target.value)}>
                  {PLAYBOOK_CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
                <input
                  type="text"
                  className="settings-input"
                  placeholder="e.g. Confirm the customer's next step before they leave"
                  value={pgText}
                  onChange={e => setPgText(e.target.value)}
                  required
                />
                <button type="submit" className="btn" disabled={pgAdding}>
                  {pgAdding ? "Adding…" : "Add"}
                </button>
              </div>
              {pgError && <div className="settings-add-error">{pgError}</div>}
            </form>
          </>
        )}
      </div>

      )}

      {/* ── Training & Enablement ────────────────────────────────────── */}
      {section === "training" && (
      <div className="settings-section">
        <div className="settings-section-head">
          <h3 className="settings-section-title">Training &amp; Enablement</h3>
          <p className="settings-section-sub">
            Each shipped enhancement gets a rep-facing walkthrough (auto-generated at deploy and shown
            in the chat under <strong>Briefings → System enhancements</strong>). Toggle any enhancement
            to <strong>Hidden</strong> to keep it out of that rep-facing card, or generate a narration
            script + storyboard for the Go-To-Channel team to feed into an AI video tool.
          </p>
        </div>
        {loading ? (
          <div className="settings-empty">Loading…</div>
        ) : enhancements.length === 0 ? (
          <div className="settings-empty">No enhancements published yet.</div>
        ) : (
          <div className="train-list">
            {enhancements.map((e) => {
              const sb = storyboards[e.title];
              return (
                <div key={e.title} className={`train-item${e.hidden ? " train-item--hidden" : ""}`}>
                  <div className="train-item-head">
                    <div>
                      <span className={`a2ui-enh-tag a2ui-enh-tag--${e.tag.toLowerCase()}`}>{e.tag}</span>
                      <span className="train-item-title">{e.title}</span>
                      {e.hidden && <span className="train-item-hidden-badge">Hidden from reps</span>}
                    </div>
                    <div className="train-item-actions">
                      <button
                        className={`settings-toggle ${e.hidden ? "off" : "on"}`}
                        onClick={() => toggleHidden(e)}
                        title={e.hidden ? "Hidden — reps don't see this in “What's new”" : "Shown to reps in “What's new”"}
                      >
                        {e.hidden ? "Hidden" : "Shown"}
                      </button>
                      <button className="btn small" disabled={sb?.generating} onClick={() => makeStoryboard(e)}>
                        {sb?.generating ? "Generating…" : sb?.result ? "Regenerate storyboard" : "🎬 Generate storyboard"}
                      </button>
                    </div>
                  </div>
                  <div className="train-item-detail">{e.detail}</div>
                  <div className="train-item-steps">
                    {e.walkthrough.steps.length} walkthrough step{e.walkthrough.steps.length === 1 ? "" : "s"}
                  </div>

                  {/* Training video: upload or view/remove */}
                  <div className="train-video">
                    {e.video_url ? (
                      <>
                        <video className="train-video-player" src={e.video_url} controls preload="metadata" />
                        <div className="train-video-actions">
                          <span className="train-video-badge">▶ Video uploaded — reps can watch it from the “What's new” card</span>
                          <button className="settings-remove" onClick={() => removeVideo(e)} title="Remove video">✕ Remove</button>
                        </div>
                      </>
                    ) : (
                      <label className="train-upload">
                        <input
                          type="file"
                          accept="video/*"
                          disabled={videoUploads[e.title]?.uploading}
                          onChange={(ev) => {
                            const f = ev.target.files?.[0];
                            if (f) uploadVideo(e, f);
                            ev.target.value = "";
                          }}
                        />
                        <span className="train-upload-btn">
                          {videoUploads[e.title]?.uploading ? "Uploading…" : "⬆ Upload training video"}
                        </span>
                      </label>
                    )}
                    {videoUploads[e.title]?.error && (
                      <div className="settings-add-error">{videoUploads[e.title].error}</div>
                    )}
                  </div>
                  {sb?.result && (
                    <div className="storyboard">
                      <div className="storyboard-head">
                        <div>
                          <div className="storyboard-title">{sb.result.title}</div>
                          <div className="storyboard-meta">{sb.result.audience} · {sb.result.total_duration_label} · {sb.result.scenes.length} scenes</div>
                        </div>
                        <button className="btn ghost small" onClick={() => copyStoryboard(e, sb.result!)}>
                          {copiedTitle === e.title ? "Copied ✓" : "Copy script"}
                        </button>
                      </div>
                      <ol className="storyboard-scenes">
                        {sb.result.scenes.map((sc) => (
                          <li key={sc.scene} className="storyboard-scene">
                            <div className="storyboard-scene-head">
                              <span className="storyboard-scene-n">Scene {sc.scene}</span>
                              <span className="storyboard-scene-dur">{sc.duration_seconds}s</span>
                            </div>
                            <div className="storyboard-row"><span className="storyboard-k">Visual</span><span>{sc.visual}</span></div>
                            <div className="storyboard-row"><span className="storyboard-k">On-screen</span><span>{sc.on_screen_text}</span></div>
                            <div className="storyboard-row"><span className="storyboard-k">Narration</span><span className="storyboard-narr">{sc.narration}</span></div>
                          </li>
                        ))}
                      </ol>
                      <div className="storyboard-cta">🎬 {sb.result.call_to_action}</div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      )}

      {/* ── The Opener ───────────────────────────────────────────────── */}
      {section === "opener" && (
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
      )}

        </div>
      </div>
    </div>
  );
}

// category → the tone class used by the a2ui news-cat pill
function toneOf(category: string): string {
  return { "To-Do": "warn", Promo: "danger", Device: "info", Policy: "warn", Network: "ok", News: "info" }[category] ?? "info";
}
