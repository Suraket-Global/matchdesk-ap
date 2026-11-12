import path from "node:path";
import { expect, test, type Browser, type Page } from "@playwright/test";
import { ROOT } from "../e2e/stack";

const MAILPIT = "http://127.0.0.1:8025/api/v1";
const OUT = process.env.SHOTS_DIR ?? path.join(ROOT, "docs/screenshots", process.env.SHOTS ?? "after");
const SIZES = { desktop: { width: 1440, height: 900 }, mobile: { width: 375, height: 812 } } as const;

async function link(email: string, after: number): Promise<string> {
  for (let i = 0; i < 60; i++) {
    const res = await fetch(`${MAILPIT}/search?query=${encodeURIComponent(`to:"${email}"`)}&limit=5`);
    const body = (await res.json()) as { messages: { ID: string; Created: string }[] };
    const fresh = body.messages.find((m) => new Date(m.Created).getTime() >= after - 2000);
    if (fresh) {
      const msg = (await (await fetch(`${MAILPIT}/message/${fresh.ID}`)).json()) as { Text: string };
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

async function api<T>(page: Page, url: string): Promise<T> {
  return page.evaluate(async (u) => (await fetch(u, { credentials: "same-origin" })).json(), url) as Promise<T>;
}

async function shoot(page: Page, name: string, url: string, size: keyof typeof SIZES): Promise<void> {
  await page.goto(url);
  await expect(page.locator("main h1, h1").first()).toBeVisible();
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(700);
  await page.screenshot({ path: path.join(OUT, `${name}-${size}.png`), fullPage: false });
}

async function walk(browser: Browser, size: keyof typeof SIZES): Promise<void> {
  const ctx = await browser.newContext({ viewport: SIZES[size] });
  const page = await ctx.newPage();
  await shoot(page, "01-sign-in", "/login", size);
  await signIn(page, "clerk.demo@example.invalid");
  type P<T> = { items: T[] };
  const all = await api<P<{ invoice_id: string; id: string; invoice_line_id: string | null; type: string }>>(
    page,
    "/api/v1/exceptions?limit=200&status=open,pending_approval",
  );
  const pick = all.items?.find((e) => e.type === "qty_over_received") ?? all.items?.[0];
  const exc = { items: pick ? [pick] : [] };
  const review = await api<P<{ id: string }>>(page, "/api/v1/invoices?state=needs_review");
  const batches = await api<P<{ id: string }>>(page, "/api/v1/intake/batches?limit=5");
  const imports = await api<P<{ id: string }>>(page, "/api/v1/receiving/imports");
  const clerk: [string, string][] = [
    ["02-onboarding", "/onboarding"],
    ["03-exceptions", "/exceptions"],
    ["04-match-view", exc.items?.[0] ? `/invoices/${exc.items[0].invoice_id}?line=${exc.items[0].invoice_line_id ?? ""}&exc=${exc.items[0].id}` : "/invoices"],
    ["05-invoices", "/invoices"],
    ["06-intake", "/intake"],
    ["07-batch", batches.items?.[0] ? `/intake/batches/${batches.items[0].id}` : "/intake"],
    ["08-review", review.items?.[0] ? `/invoices/${review.items[0].id}/review` : "/invoices"],
    ["09-receiving", "/receiving"],
    ["10-receiving-import", imports.items?.[0] ? `/receiving/imports/${imports.items[0].id}` : "/receiving"],
    ["11-aliases", "/aliases"],
    ["12-quickbooks", "/settings/quickbooks"],
  ];
  for (const [name, url] of clerk) await shoot(page, name, url, size);
  await ctx.clearCookies();
  await signIn(page, "controller.demo@example.invalid");
  await shoot(page, "13-approvals", "/approvals", size);
  await page.goto("/reports");
  const month = page.getByLabel("Test month");
  await month.fill("2026-10");
  await page.getByRole("button", { name: /Create draft for October 2026/ }).click();
  await expect(page).toHaveURL(/\/reports\/backtest\//);
  const report = new URL(page.url()).pathname;
  for (const [name, url] of [
    ["14-reports", "/reports"],
    ["15-report", report],
    ["16-tolerances", "/settings/tolerances"],
    ["17-users", "/settings/users"],
    ["18-audit", "/audit"],
    ["19-settings", "/settings"],
  ] as [string, string][])
    await shoot(page, name, url, size);
  await ctx.close();
}

test("screens at 1440x900", async ({ browser }) => walk(browser, "desktop"));
test("screens at 375x812", async ({ browser }) => {
  // The second walk creates a second draft for the same month; that is fine on the throwaway stack.
  await walk(browser, "mobile");
});

test("dark theme at 1440x900", async ({ browser }) => {
  if (process.env.SHOTS === "before") test.skip();
  const ctx = await browser.newContext({ viewport: SIZES.desktop, colorScheme: "dark" });
  const page = await ctx.newPage();
  await signIn(page, "clerk.demo@example.invalid");
  const all = await api<{ items: { invoice_id: string; id: string; invoice_line_id: string | null; type: string }[] }>(page, "/api/v1/exceptions?limit=200&status=open,pending_approval");
  const e = all.items.find((x) => x.type === "qty_over_received") ?? all.items[0];
  await shoot(page, "20-exceptions-dark", "/exceptions", "desktop");
  await shoot(page, "21-match-view-dark", `/invoices/${e.invoice_id}?line=${e.invoice_line_id ?? ""}&exc=${e.id}`, "desktop");
  await ctx.close();
});
