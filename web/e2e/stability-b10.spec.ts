// B10 on Playwright's own stack, after B9 (file order): the outside deep-QA findings that a browser
// shows. Pasting "1,000" into S-07 used to throw "Cannot convert 1,000 to a BigInt" and replace the
// page with "This page could not be shown".
import { execFileSync } from "node:child_process";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { ROOT } from "./stack";
import { axe, linkFor, run, signIn } from "./helpers";

test("B10 pasting 1,000 and 1.000,5 into the review screen keeps the form open", async ({ page }) => {
  const { tag } = run();
  await signIn(page, `clerk.${tag}@example.invalid`);
  const items = await page.evaluate(async () => (await (await fetch("/api/v1/invoices?limit=50")).json()).items as { id: string }[]);
  await page.goto(`/invoices/${items[0].id}/review`);
  const qty = page.getByLabel("Line 1 Qty");
  await expect(qty).toBeVisible();
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  // A paste: the whole value arrives in one input event.
  await qty.selectText();
  await page.keyboard.insertText("1,000");
  await expect(qty).toHaveValue("1,000");
  await expect(page.getByText("This page could not be shown", { exact: false })).toHaveCount(0);
  await expect(page.locator("#l-1-qty-err")).toHaveCount(0);
  await qty.selectText();
  await page.keyboard.insertText("1.000,5");
  await expect(page.locator("#l-1-qty-err")).toHaveText("Use a dot for decimals: write 1000.50, not 1.000,50.");
  await expect(qty).toHaveAttribute("aria-invalid", "true");
  const total = page.getByLabel("Total", { exact: true });
  await total.selectText();
  await page.keyboard.insertText("12a");
  await expect(page.locator("#h-total-err")).toContainText("Use digits");
  await expect(page.getByRole("button", { name: "Confirm and match" })).toBeVisible();
  await expect(page.getByText("This page could not be shown", { exact: false })).toHaveCount(0);
  expect(errors.filter((m) => m.includes("BigInt"))).toEqual([]);
});

// ------------------------------------------------------------------ the changed screens (B10)
// Each changed screen at 1440 x 900 and 375 x 812 with an axe scan; B10_SHOTS=1 also writes the
// screenshots in docs/screenshots/b10/. Mutations run on this isolated stack only.

const SHOTS = process.env.B10_SHOTS === "1";
const SHOT_DIR = path.join(ROOT, "docs/screenshots/b10");
const PY = path.join(ROOT, "backend/.venv/bin/python");
const E2E_DB = "postgresql+psycopg://matchdesk_app@localhost:5432/matchdesk_e2e";
const SIZES = [
  { w: 1440, h: 900 },
  { w: 375, h: 812 },
];

async function both(page: Page, name: string, label: string, ready: () => Promise<void>): Promise<void> {
  for (const s of SIZES) {
    await page.setViewportSize({ width: s.w, height: s.h });
    // The sidebar slides away below 1024 px; let it finish before the screenshot.
    await expect(page.locator("aside.sidebar, [aria-label='Sidebar']").first()).not.toBeInViewport({ ratio: 0.5 }).catch(() => undefined);
    await page.waitForTimeout(400);
    await ready();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow, `${label} at ${s.w}: sideways scroll`).toBeLessThanOrEqual(1);
    if (SHOTS) await page.screenshot({ path: path.join(SHOT_DIR, `${name}-${s.w}.png`), fullPage: false });
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  await axe(page, label);
}

async function api<T>(page: Page, url: string, init?: { method: string; body?: unknown; form?: Record<string, string> }): Promise<T> {
  return page.evaluate(
    async ({ url, init }) => {
      const me = await (await fetch("/api/v1/me")).json();
      const headers: Record<string, string> = { "X-CSRF-Token": me.csrf_token };
      let body: BodyInit | undefined;
      if (init?.form) {
        const fd = new FormData();
        for (const [k, v] of Object.entries(init.form)) {
          if (k === "file") fd.append(k, new Blob([v], { type: "text/csv" }), "b10-walk.csv");
          else fd.append(k, v);
        }
        body = fd;
      } else if (init?.body !== undefined) {
        headers["Content-Type"] = "application/json";
        body = JSON.stringify(init.body);
      }
      return (await fetch(url, { method: init?.method ?? "GET", headers, body })).json();
    },
    { url, init },
  ) as Promise<T>;
}

function operatorCode(email: string): string {
  return execFileSync(PY, [path.join(ROOT, "backend/scripts/operator_code.py"), email], { cwd: path.join(ROOT, "backend"), env: { ...process.env, MATCHDESK_DATABASE_URL: E2E_DB } })
    .toString()
    .split(" ")[0];
}

test("B10 the changed screens at 1440 and 375", async ({ page }) => {
  test.setTimeout(300_000);
  execFileSync("psql", ["-q", "-d", "matchdesk_e2e", "-c", "delete from auth_rate_events"]);
  const { tag } = run();
  await signIn(page, `controller.${tag}@example.invalid`);
  // S-07: a mismatch opens the total check; a field that cannot be read says why beside it.
  const inv = (await api<{ items: { id: string }[] }>(page, "/api/v1/invoices?limit=50")).items[0];
  await page.goto(`/invoices/${inv.id}/review`);
  await page.getByLabel("Total", { exact: true }).fill("1,012.50");
  await page.getByLabel("Line 1 Qty").fill("1.000,5");
  await both(page, "review-mismatch", "review with a mismatch", async () => {
    await expect(page.getByTestId("total-check")).toContainText("Differs by");
    await expect(page.locator("#l-1-qty-err")).toBeVisible();
  });
  // S-05: each mapping with a value from the file; required ones first; optional folded.
  const draft = await api<{ id: string }>(page, "/api/v1/receiving/imports", {
    method: "POST",
    form: { file: "PO Number,Line,Qty Received,When\n4471,1,60,2026-10-03\n", evidence_class: "A" },
  });
  await page.goto(`/receiving/imports/${draft.id}`);
  await both(page, "receiving-mapping", "receiving column mapping", async () => {
    await expect(page.getByTestId("map-qty_received")).toContainText("60");
  });
  // S-11 and S-15: the live example and what a save does.
  await page.goto("/aliases");
  await page.getByLabel("Supplier unit", { exact: true }).fill("CS");
  await page.getByLabel("Our unit", { exact: true }).fill("EA");
  await page.getByLabel("Conversion (our units per supplier unit)").fill("25");
  await both(page, "aliases-example", "aliases", async () => {
    await expect(page.getByTestId("alias-headline")).toContainText("1 CS → 25 EA");
  });
  await page.goto("/settings/tolerances");
  await both(page, "tolerances-example", "tolerances", async () => {
    await expect(page.getByTestId("tolerance-consequence")).toContainText("Saving re-matches");
  });
  // S-14: the delivery of each run.
  await page.goto("/reports/weekly?week=2026-10-05");
  await both(page, "weekly-delivery", "weekly summary", async () => {
    await expect(page.getByTestId("weekly-deliveries")).toContainText("Delivered");
  });
  // S-13: scope, the three totals and the row states (the governing version from B9).
  const reports = await api<{ items: { id: string; status: string }[] }>(page, "/api/v1/reports/backtest?limit=50");
  const approved = reports.items.find((r) => r.status === "approved")!;
  await page.goto(`/reports/backtest/${approved.id}`);
  const scope = page.getByTestId("outcome-scope");
  await scope.scrollIntoViewIfNeeded();
  await both(page, "report-outcomes", "report outcomes", async () => {
    await scope.scrollIntoViewIfNeeded();
    await expect(scope).toContainText("Confirmed by the controller");
  });
  // S-16: complete archive; the deletion dialog names it.
  await page.goto("/settings/users");
  await both(page, "account-data", "account data", async () => {
    await expect(page.getByTestId("archive-state")).toContainText("originals");
  });
  // A request from the second tagged account, for the operator's console.
  await page.context().clearCookies();
  const tag2 = `${tag}nr`;
  await signIn(page, `controller.${tag2}@example.invalid`);
  await api(page, "/api/v1/account/deletion-requests", { method: "POST", body: { confirm_name: `Demo Distributor Ltd (synthetic) ${tag2}`, reason: "B10 walk (synthetic)", acknowledge_incomplete_archive: true } });
  await page.context().clearCookies();
  const op = `operator.${tag}@example.invalid`;
  await page.goto("/login");
  await page.getByLabel("Work email").fill(op);
  const asked = Date.now();
  await page.getByRole("button", { name: "Email me a sign-in link" }).click();
  await page.goto(await linkFor(op, asked));
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await new Promise((r) => setTimeout(r, 31_000 - (Date.now() % 30_000)));
  await page.getByLabel("One-time code from your authenticator app").fill(operatorCode(op));
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Operator console" })).toBeVisible();
  await both(page, "operator-console", "operator console", async () => {
    await expect(page.getByTestId("deletion-row").first()).toContainText("Needs your decision");
    await expect(page.getByRole("heading", { name: "Operations" })).toBeVisible();
  });
});
