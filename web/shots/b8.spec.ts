import { E2E_API, E2E_MAILPIT, ROOT } from "../e2e/stack";
import { execFileSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { expect, test, type Browser, type Page } from "@playwright/test";

// B8 (2026-11-13): the same seeded records (seed_demo.py --preload on matchdesk_shots) captured before
// and after the redesign, at 1440, 1024 and 375 wide: the queue, FF-1003 and one controller decision,
// plus the weekly drill-down and the first actionable case at phone width, measured.
// Run: cd web && SHOTS=before|after npx playwright test -c playwright.shots.config.ts b8
const PHASE = process.env.SHOTS ?? "after";
const OUT = path.join(ROOT, "docs/screenshots/b8", PHASE);
const SIZES = {
  1440: { width: 1440, height: 900 },
  1024: { width: 1024, height: 768 },
  375: { width: 375, height: 812 },
} as const;
type Size = keyof typeof SIZES;
const measured: Record<string, unknown> = { phase: PHASE, fixture: "seed_demo.py --preload, tenant Demo Distribution (synthetic)", period: "October 2026" };

async function link(email: string, after: number): Promise<string> {
  for (let i = 0; i < 60; i++) {
    const res = await fetch(`${E2E_MAILPIT}/search?query=${encodeURIComponent(`to:"${email}"`)}&limit=5`);
    const body = (await res.json()) as { messages: { ID: string; Created: string }[] };
    const fresh = body.messages.find((m) => new Date(m.Created).getTime() >= after - 2000);
    if (fresh) {
      const msg = (await (await fetch(`${E2E_MAILPIT}/message/${fresh.ID}`)).json()) as { Text: string };
      const m = /(http\S+#t=\S+)/.exec(msg.Text);
      if (m) return m[1];
    }
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error(`no sign-in mail for ${email}`);
}

async function signIn(page: Page, email: string): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Work email").fill(email);
  const asked = Date.now();
  await page.getByRole("button", { name: "Email me a sign-in link" }).click();
  await page.goto(await link(email, asked));
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.locator("header.topbar")).toBeVisible();
}

const PY = path.join(ROOT, "backend/.venv/bin/python");
function operatorCode(email: string): string {
  return execFileSync(PY, [path.join(ROOT, "backend/scripts/operator_code.py"), email], {
    cwd: path.join(ROOT, "backend"),
    env: { ...process.env, MATCHDESK_DATABASE_URL: "postgresql+psycopg://matchdesk_app@localhost:5432/matchdesk_shots", MATCHDESK_API_URL: E2E_API },
  })
    .toString()
    .split(" ")[0];
}

async function api<T>(page: Page, url: string): Promise<T> {
  return page.evaluate(async (u) => (await fetch(u, { credentials: "same-origin" })).json(), url) as Promise<T>;
}

async function settle(page: Page): Promise<void> {
  await expect(page.locator("main h1, h1").first()).toBeVisible();
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(800);
}

async function shot(page: Page, name: string, size: Size): Promise<void> {
  await settle(page);
  await page.screenshot({ path: path.join(OUT, `${name}-${size}.png`), fullPage: false });
}

type Exc = { id: string; invoice_id: string; invoice_line_id: string | null; type: string; doc_number: string | null; status: string };

async function clerk(browser: Browser, size: Size, dark = false): Promise<void> {
  const ctx = await browser.newContext({ viewport: SIZES[size], colorScheme: dark ? "dark" : "light" });
  const page = await ctx.newPage();
  await signIn(page, "clerk.demo@example.invalid");
  const all = await api<{ items: Exc[] }>(page, "/api/v1/exceptions?limit=200&status=open,pending_approval");
  const ff = all.items.find((e) => e.doc_number === "FF-1003" && e.type === "qty_over_received")!;
  const suffix = dark ? "-dark" : "";
  await page.goto("/exceptions");
  await shot(page, `01-queue${suffix}`, size);
  if (size === 375 && !dark) {
    // The first actionable case: its link to the match view, measured in the initial viewport.
    const first = page.locator('main a[href*="/invoices/"][href*="exc="]').filter({ visible: true }).first();
    const box = await first.boundingBox();
    const inView = box ? box.y >= 0 && box.y + box.height <= SIZES[375].height : false;
    measured.first_mobile_case = { top_px: box ? Math.round(box.y) : null, height_px: box ? Math.round(box.height) : null, visible_without_scrolling: inView, text: (await first.textContent())?.trim() };
  }
  await page.goto(`/invoices/${ff.invoice_id}?line=${ff.invoice_line_id ?? ""}&exc=${ff.id}&from=${encodeURIComponent("/exceptions")}`);
  await page.waitForTimeout(1500); // the PDF renders
  await shot(page, `02-ff1003${suffix}`, size);
  if (size === 1440 && !dark) {
    const receipt = page.locator('main a[href*="/receiving/imports/"]').first();
    measured.ff1003_receipt_link = { text: (await receipt.textContent())?.trim(), top_px: Math.round((await receipt.boundingBox())?.y ?? -1) };
  }
  if (!dark && (PHASE === "after" || size === 1440)) {
    // Dark theme in the same session (one sign-in per width keeps within the sign-in rate limit).
    await page.emulateMedia({ colorScheme: "dark" });
    await page.goto("/exceptions");
    await shot(page, "01-queue-dark", size);
    await page.goto(`/invoices/${ff.invoice_id}?line=${ff.invoice_line_id ?? ""}&exc=${ff.id}&from=${encodeURIComponent("/exceptions")}`);
    await page.waitForTimeout(1500);
    await shot(page, "02-ff1003-dark", size);
  }
  await ctx.close();
}

async function controller(browser: Browser, size: Size): Promise<void> {
  const ctx = await browser.newContext({ viewport: SIZES[size] });
  const page = await ctx.newPage();
  await signIn(page, "controller.demo@example.invalid");
  await page.goto("/approvals");
  await shot(page, "03-approval", size);
  await page.goto("/reports/weekly?week=2026-10-05");
  await shot(page, "04-weekly", size);
  if (size === 1440) {
    const weekly = await api<{ suppliers: { vendor_name: string | null; vendor_id: string | null; open_count: number; open_value: string }[] }>(page, "/api/v1/weekly-summary?week_start=2026-10-05");
    const ff = weekly.suppliers.find((s) => s.vendor_name === "Fictional Fasteners Ltd");
    // The supplier's open count (B7: a link named by its number; B8: named with supplier and week).
    const row = page.locator("main tbody tr", { hasText: "Fictional Fasteners Ltd" });
    await row.locator('a[href^="/exceptions"]').first().click();
    await settle(page);
    const rows = await page.locator('main a[href*="/invoices/"][href*="exc="]').filter({ visible: true }).count();
    measured.weekly_drilldown = {
      report: { supplier: ff?.vendor_name, open_count: ff?.open_count, open_value: ff?.open_value },
      queue_url: new URL(page.url()).pathname + new URL(page.url()).search,
      queue_rows_shown: rows,
      queue_total_text: (await page.locator("main tfoot, main [data-queue-total]").first().textContent().catch(() => null))?.replace(/\s+/g, " ").trim() ?? null,
    };
    await shot(page, "05-weekly-to-queue", size);
  }
  await ctx.close();
}

test.describe.configure({ mode: "serial" });
test.beforeAll(() => mkdirSync(OUT, { recursive: true }));
test.afterAll(() => writeFileSync(path.join(OUT, "measurements.json"), `${JSON.stringify(measured, null, 2)}\n`));

for (const size of [1440, 1024, 375] as Size[]) {
  test(`clerk screens at ${size}`, async ({ browser }) => clerk(browser, size));
  test(`controller screens at ${size}`, async ({ browser }) => controller(browser, size));
}

test("operator: console and account", async ({ browser }) => {
  const ctx = await browser.newContext({ viewport: SIZES[1440] });
  const page = await ctx.newPage();
  const email = "operator.demo@example.invalid";
  await page.goto("/login");
  await page.getByLabel("Work email").fill(email);
  const asked = Date.now();
  await page.getByRole("button", { name: "Email me a sign-in link" }).click();
  await page.goto(await link(email, asked));
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.getByLabel("One-time code from your authenticator app").fill(operatorCode(email));
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Operator console" })).toBeVisible();
  const tenants = await api<{ items: { id: string }[] }>(page, "/api/v1/operator/tenants");
  await page.goto(`/operator/tenants/${tenants.items[0].id}`);
  await shot(page, "06-operator-account", 1440);
  await ctx.close();
});
