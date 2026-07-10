import { useState } from "react";
import { api } from "../api";
import type { SendReportResult } from "../types";

interface Props {
  reportType: "performance" | "cx";
  start?: string;
  end?: string;
}

export default function SendReportButton({ reportType, start, end }: Props) {
  const [state, setState] = useState<"idle" | "loading" | "done" | "error">("idle");
  const [result, setResult] = useState<SendReportResult | null>(null);
  const [showPreview, setShowPreview] = useState(false);

  async function handleSend() {
    setState("loading");
    try {
      const r = await api.sendReport(reportType, start, end);
      setResult(r);
      setState(r.error ? "error" : "done");
    } catch (e) {
      setResult({ sent: 0, previewed: false, recipients: [], error: String(e) });
      setState("error");
    }
  }

  function dismiss() {
    setState("idle");
    setResult(null);
    setShowPreview(false);
  }

  if (state === "idle" || state === "loading") {
    return (
      <button
        className={`btn btn-send-report${state === "loading" ? " loading" : ""}`}
        onClick={handleSend}
        disabled={state === "loading"}
      >
        {state === "loading" ? "Sending…" : "✉ Send Report"}
      </button>
    );
  }

  // Result toast
  const isPreview = result?.previewed || (result?.sent === 0 && result?.preview_html);
  const hasNoSubs = result?.sent === 0 && !result?.preview_html && !result?.error;

  return (
    <div className="send-report-toast">
      <div className={`send-report-inner${state === "error" ? " is-error" : ""}`}>
        <div className="send-report-msg">
          {state === "error" && result?.error ? (
            <><span className="send-report-icon">✗</span> {result.error}</>
          ) : hasNoSubs ? (
            <><span className="send-report-icon">⚠</span> No subscribers — add recipients in <strong>Settings</strong>.</>
          ) : isPreview ? (
            <><span className="send-report-icon">◎</span>
              {result?.warning || "SMTP not configured — preview generated."}
              {result?.recipients?.length ? ` (${result.recipients.length} subscriber${result.recipients.length !== 1 ? "s" : ""} would receive this)` : ""}
            </>
          ) : (
            <><span className="send-report-icon send-report-icon--ok">✓</span>
              Sent to {result?.sent} recipient{result?.sent !== 1 ? "s" : ""}: {result?.recipients?.join(", ")}
            </>
          )}
        </div>
        <div className="send-report-actions">
          {result?.preview_html && (
            <button className="send-report-link" onClick={() => setShowPreview(v => !v)}>
              {showPreview ? "Hide preview" : "Preview email"}
            </button>
          )}
          <button className="send-report-link" onClick={dismiss}>Dismiss</button>
        </div>
      </div>

      {showPreview && result?.preview_html && (
        <div className="send-report-preview-wrap">
          <iframe
            className="send-report-preview-frame"
            srcDoc={result.preview_html}
            title="Email preview"
            sandbox="allow-same-origin"
          />
        </div>
      )}
    </div>
  );
}
