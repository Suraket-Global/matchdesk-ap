/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The API runs on 127.0.0.1:8101 (make up). The browser only ever talks to this origin, so the
// session cookie stays first-party and the API's Origin check sees the app's own address.
const API = process.env.MATCHDESK_API_URL ?? "http://127.0.0.1:8101";

// TRD 8.7 response headers; the proxy sets them in production, the preview server here.
const CSP =
  "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; " +
  "worker-src 'self' blob:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'";

export default defineConfig({
  plugins: [react()],
  server: {
    // The demo files are readable by the dev server only (for in-browser checks); never in a build.
    fs: { allow: [".", "../play-files"] },
    proxy: {
      "/api": { target: API, changeOrigin: false },
      "/oauth": { target: API, changeOrigin: false },
    },
  },
  preview: {
    proxy: {
      "/api": { target: API, changeOrigin: false },
      "/oauth": { target: API, changeOrigin: false },
    },
    headers: {
      "Content-Security-Policy": CSP,
      "X-Content-Type-Options": "nosniff",
      "Referrer-Policy": "no-referrer",
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    // No inline scripts or styles in the output (CSP without 'unsafe-inline').
    assetsInlineLimit: 0,
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    css: false,
  },
});
