import { defineConfig } from "@playwright/test";
import { E2E_API, E2E_WEB } from "./e2e/stack";

// E2E-01 runs headless in the installed Google Chrome (no browser download) on its own stack:
// database matchdesk_e2e, API on 8102 and a worker (created and dropped by global setup and
// teardown), and a web dev server on 5174 proxied to that API. PostgreSQL and Mailpit must run.
export default defineConfig({
  testDir: "e2e",
  timeout: 180_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  globalSetup: "./e2e/global-setup.ts",
  globalTeardown: "./e2e/global-teardown.ts",
  use: {
    baseURL: E2E_WEB,
    channel: "chrome",
    headless: true,
    viewport: { width: 1440, height: 900 },
    acceptDownloads: true,
    trace: "retain-on-failure",
  },
  webServer: {
    command: "npm run dev:e2e",
    url: `${E2E_WEB}/login`,
    env: { MATCHDESK_API_URL: E2E_API },
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
