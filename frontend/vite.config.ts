import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// During dev, proxy API + health calls to the orchestrator on :8000 so the
// frontend can use relative URLs (and ship as an embeddable sales-app widget later).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // SSE endpoints need streaming — configure explicitly so http-proxy
      // does not buffer the response body.
      "/api/system-health/events": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        selfHandleResponse: false,
        configure: (proxy) => {
          proxy.on("proxyReq", (_, req) => {
            req.headers["accept"] = "text/event-stream";
          });
        },
      },
      "/api/production/events": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        selfHandleResponse: false,
        configure: (proxy) => {
          proxy.on("proxyReq", (_, req) => {
            req.headers["accept"] = "text/event-stream";
          });
        },
      },
      "/api": "http://127.0.0.1:8000",
      "/health": "http://127.0.0.1:8000",
    },
  },
});
