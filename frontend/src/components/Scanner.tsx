import { useEffect, useRef, useState } from "react";

interface Props {
  mode: "barcode" | "bill";
  onClose: () => void;
  onBarcode: (upc: string) => void;              // barcode mode: a UPC was read
  onCapture: (base64: string, mediaType: string) => void; // bill mode: a photo was captured
}

// A camera-backed scanner modal. Barcode mode uses the browser BarcodeDetector
// to read a UPC; Bill mode captures a still frame. Both degrade to manual entry
// / file upload when the camera or BarcodeDetector isn't available (e.g. no
// permission, desktop without a rear camera, or an unsupported browser).
export default function Scanner({ mode, onClose, onBarcode, onCapture }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const rafRef = useRef<number | null>(null);
  const doneRef = useRef(false);
  const [status, setStatus] = useState<"starting" | "live" | "nocamera">("starting");
  const [manual, setManual] = useState("");
  const hasDetector = typeof (window as any).BarcodeDetector !== "undefined";

  useEffect(() => {
    let cancelled = false;
    async function start() {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: { ideal: "environment" } }, audio: false,
        });
        if (cancelled) { stream.getTracks().forEach((t) => t.stop()); return; }
        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          await videoRef.current.play().catch(() => {});
        }
        setStatus("live");
        if (mode === "barcode" && hasDetector) runBarcodeLoop();
      } catch {
        setStatus("nocamera");
      }
    }
    start();
    return () => {
      cancelled = true;
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      streamRef.current?.getTracks().forEach((t) => t.stop());
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function finish(fn: () => void) {
    if (doneRef.current) return;
    doneRef.current = true;
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    streamRef.current?.getTracks().forEach((t) => t.stop());
    fn();
  }

  async function runBarcodeLoop() {
    const detector = new (window as any).BarcodeDetector({
      formats: ["upc_a", "upc_e", "ean_13", "ean_8", "code_128", "code_39"],
    });
    const tick = async () => {
      if (doneRef.current || !videoRef.current) return;
      try {
        const codes = await detector.detect(videoRef.current);
        if (codes && codes.length && codes[0].rawValue) {
          finish(() => onBarcode(String(codes[0].rawValue)));
          return;
        }
      } catch { /* frame not ready — keep polling */ }
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
  }

  function captureFrame() {
    const video = videoRef.current;
    if (!video || !video.videoWidth) return;
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext("2d")?.drawImage(video, 0, 0);
    const dataUrl = canvas.toDataURL("image/jpeg", 0.85);
    const base64 = dataUrl.split(",")[1] ?? "";
    finish(() => onCapture(base64, "image/jpeg"));
  }

  function onFile(file: File) {
    const reader = new FileReader();
    reader.onload = () => {
      const dataUrl = String(reader.result || "");
      const base64 = dataUrl.split(",")[1] ?? "";
      const mediaType = (dataUrl.match(/^data:([^;]+);/)?.[1]) || file.type || "image/jpeg";
      finish(() => onCapture(base64, mediaType));
    };
    reader.readAsDataURL(file);
  }

  const title = mode === "barcode" ? "Scan Barcode" : "Scan Bill";
  const hint = mode === "barcode"
    ? "Point the camera at a product's UPC barcode."
    : "Fill the frame with the customer's competitor bill, then capture.";

  return (
    <div className="scanner" role="dialog" aria-modal="true" aria-label={title}>
      <div className="scanner-head">
        <span className="scanner-title">{mode === "barcode" ? "🔎" : "🧾"} {title}</span>
        <button className="scanner-close" onClick={() => finish(onClose)} aria-label="Close scanner">✕</button>
      </div>

      <div className="scanner-stage">
        {status !== "nocamera" && (
          <video ref={videoRef} className="scanner-video" playsInline muted />
        )}
        {status === "live" && (
          <div className={`scanner-reticle scanner-reticle--${mode}`}>
            <span className="scanner-frame" />
            {mode === "barcode" && <span className="scanner-laser" />}
          </div>
        )}
        {status === "starting" && <div className="scanner-msg">Starting camera…</div>}
        {status === "nocamera" && (
          <div className="scanner-msg scanner-msg--nocam">
            <div className="scanner-nocam-icon">📷</div>
            <div>Camera unavailable.</div>
            <div className="scanner-nocam-sub">
              {mode === "barcode" ? "Enter the UPC below" : "Upload a photo of the bill instead"}.
            </div>
          </div>
        )}
        <div className="scanner-hint">{hint}</div>
      </div>

      <div className="scanner-controls">
        {mode === "bill" && (
          <>
            {status === "live" && (
              <button className="scanner-capture" onClick={captureFrame} aria-label="Capture bill">
                <span className="scanner-capture-ring" />
              </button>
            )}
            <label className="scanner-upload">
              <input
                type="file"
                accept="image/*"
                capture="environment"
                onChange={(e) => { const f = e.target.files?.[0]; if (f) onFile(f); }}
              />
              <span>⬆ Upload a photo instead</span>
            </label>
          </>
        )}

        {mode === "barcode" && (
          <>
            {status === "live" && hasDetector && (
              <div className="scanner-scanning">Scanning for a barcode…</div>
            )}
            {status === "live" && !hasDetector && (
              <div className="scanner-scanning">Live scanning isn't supported here — enter the UPC:</div>
            )}
            <form
              className="scanner-manual"
              onSubmit={(e) => { e.preventDefault(); if (manual.trim()) finish(() => onBarcode(manual.trim())); }}
            >
              <input
                className="scanner-manual-input"
                inputMode="numeric"
                placeholder="Enter UPC number"
                value={manual}
                onChange={(e) => setManual(e.target.value)}
              />
              <button type="submit" className="scanner-manual-go" disabled={!manual.trim()}>Look up</button>
            </form>
          </>
        )}
      </div>
    </div>
  );
}
