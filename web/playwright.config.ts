import { defineConfig } from "@playwright/test";

// E2E-01 runs headless in the installed Google Chrome (no browser download), against the dev
// server and the local API. `make up` must be running; the dev server is started if needed.
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
    baseURL: "http://127.0.0.1:5173",
    channel: "chrome",
    headless: true,
    viewport: { width: 1440, height: 900 },
    acceptDownloads: true,
    trace: "retain-on-failure",
  },
  webServer: {
    command: "npm run dev",
    url: "http://127.0.0.1:5173/login",
    reuseExistingServer: true,
    timeout: 60_000,
  },
});
