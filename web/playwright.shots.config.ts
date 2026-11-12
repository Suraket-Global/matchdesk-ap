import "./shots/profile";
import { defineConfig } from "@playwright/test";
import { E2E_API, E2E_WEB, E2E_WEB_PORT } from "./e2e/stack";

// Screenshots of every main screen for docs/UI.md (B6), on Playwright's own stack (matchdesk_e2e)
// with the untagged demo tenant preloaded. SHOTS=before|after names the folder under docs/screenshots.
export default defineConfig({
  testDir: "shots",
  timeout: 300_000,
  expect: { timeout: 20_000 },
  workers: 1,
  reporter: [["list"]],
  globalSetup: "./shots/setup.ts",
  globalTeardown: "./shots/teardown.ts",
  use: { baseURL: E2E_WEB, channel: "chrome", headless: true },
  webServer: {
    command: `npx vite --host 127.0.0.1 --port ${E2E_WEB_PORT} --strictPort`,
    url: `${E2E_WEB}/login`,
    env: { MATCHDESK_API_URL: E2E_API },
    reuseExistingServer: false,
  },
});
