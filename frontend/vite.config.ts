import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// During dev, proxy API + health calls to the orchestrator on :8000 so the
// frontend can use relative URLs (and ship as an embeddable POS widget later).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/health": "http://127.0.0.1:8000",
    },
  },
});
