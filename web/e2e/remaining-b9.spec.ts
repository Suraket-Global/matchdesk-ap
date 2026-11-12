// B9 on Playwright's own stack, after E2E-01, B7 and B8 (file order). The five screens that used to
// say "Open in a wider window" are worked at 375 x 812; the sidebar's queue link survives a reload;
// the assignee filter; the S-10 banner from recorded responses; the "no receiving records"
// declaration on a second, fresh tagged tenant; the archive; the deletion request and the operator's
// schedule. B9_SHOTS=1 also writes the screenshots in docs/screenshots/b9/.
import { execFileSync } from "node:child_process";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { ROOT, stack } from "./stack";
import { axe, linkFor, run, signIn } from "./helpers";

const SHOTS = process.env.B9_SHOTS === "1";
const SHOT_DIR = path.join(ROOT, "docs/screenshots/b9");
const PY = path.join(ROOT, "backend/.venv/bin/python");
const E2E_DB = "postgresql+psycopg://matchdesk_app@localhost:5432/matchdesk_e2e";
const TENANT = "Demo Distributor Ltd (synthetic)";

async function shot(page: Page, name: string): Promise<void> {
  if (SHOTS) await page.screenshot({ path: path.join(SHOT_DIR, `${name}.png`), fullPage: false });
}

async function noSideways(page: Page, label: string): Promise<void> {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow, `${label}: sideways scroll`).toBeLessThanOrEqual(1);
  await expect(page.getByText("Open in a wider window")).toHaveCount(0);
}

async function api<T>(page: Page, url: string, init?: { method: string; body?: unknown; ifMatch?: number; form?: Record<string, string> }): Promise<T> {
  return page.evaluate(
    async ({ url, init }) => {
      const me = await (await fetch("/api/v1/me")).json();
      const headers: Record<string, string> = { "X-CSRF-Token": me.csrf_token };
      if (init?.ifMatch !== undefined) headers["If-Match"] = String(init.ifMatch);
      let body: BodyInit | undefined;
      if (init?.form) {
        const fd = new FormData();
        for (const [k, v] of Object.entries(init.form)) {
          if (k === "file") fd.append(k, new Blob([v], { type: "text/csv" }), "b9-walk.csv");
          else fd.append(k, v);
        }
        body = fd;
      } else if (init?.body !== undefined) {
        headers["Content-Type"] = "application/json";
        body = JSON.stringify(init.body);
      }
      const r = await fetch(url, { method: init?.method ?? "GET", headers, body });
      return r.json();
    },
    { url, init },
  ) as Promise<T>;
}

function operatorCode(email: string): string {
  return execFileSync(PY, [path.join(ROOT, "backend/scripts/operator_code.py"), email], {
    cwd: path.join(ROOT, "backend"),
    env: { ...process.env, MATCHDESK_DATABASE_URL: E2E_DB },
  })
    .toString()
    .split(" ")[0];
}
async function signInOperator(page: Page, email: string): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Work email").fill(email);
  const asked = Date.now();
  await page.getByRole("button", { name: "Email me a sign-in link" }).click();
  await expect(page.getByText("If that address has access, a link is on its way.")).toBeVisible();
  await page.goto(await linkFor(email, asked));
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByLabel("One-time code from your authenticator app")).toBeVisible();
  // A code is accepted once: wait for a fresh 30-second step after any earlier operator sign-in.
  await new Promise((r) => setTimeout(r, 31_000 - (Date.now() % 30_000)));
  await page.getByLabel("One-time code from your authenticator app").fill(operatorCode(email));
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Operator console" })).toBeVisible();
}

// A second tagged tenant for the declaration. The sign-in limits (5 links per address per 15 minutes,
// 20 per IP per hour; TRD 8.1) are emptied on this isolated database only, so this file's sign-ins
// are not refused after the earlier files used them.
test.beforeAll(() => {
  stack("seed", "--tag", `${run().tag}nr`);
  execFileSync("psql", ["-q", "-d", "matchdesk_e2e", "-c", "delete from auth_rate_events"]);
});

test("B9 the five former wide-only screens work at 375 x 812", async ({ browser }) => {
  const { tag } = run();
  const ctx = await browser.newContext({ viewport: { width: 375, height: 812 } });
  const page = await ctx.newPage();
  await signIn(page, `controller.${tag}@example.invalid`);
  // Intake upload: the file picker is there and reachable.
  await page.goto("/intake");
  await expect(page.getByRole("button", { name: "Choose files" })).toBeVisible();
  await noSideways(page, "intake");
  await shot(page, "intake-375");
  // Extraction review: fields, the line blocks and the confirm control.
  const inv = (await api<{ items: { id: string; doc_number: string }[] }>(page, "/api/v1/invoices?limit=5")).items[0];
  await page.goto(`/invoices/${inv.id}/review`);
  await expect(page.getByLabel("Line 1 Unit price")).toBeVisible();
  await expect(page.getByRole("button", { name: "Confirm and match" })).toBeVisible();
  await noSideways(page, "review");
  await shot(page, "review-375");
  // Receiving column step: a draft, its column choices and "Check rows".
  const draft = await api<{ id: string }>(page, "/api/v1/receiving/imports", {
    method: "POST",
    form: { file: "PO Number,Line,Qty Received,Date Received\n4471,1,1,2026-10-03\n", evidence_class: "A" },
  });
  await page.goto(`/receiving/imports/${draft.id}`);
  await expect(page.getByLabel("PO number (required)")).toBeVisible();
  await expect(page.getByRole("button", { name: "Check rows" })).toBeVisible();
  await noSideways(page, "receiving column step");
  await shot(page, "receiving-columns-375");
  // Aliases: the confirm form; tolerances: values and the save that previews first.
  await page.goto("/aliases");
  await expect(page.getByRole("heading", { name: "Confirm an alias" })).toBeVisible();
  await noSideways(page, "aliases");
  await shot(page, "aliases-375");
  await page.goto("/settings/tolerances");
  await expect(page.getByLabel("Quantity tolerance")).toBeVisible();
  await noSideways(page, "tolerances");
  await shot(page, "tolerances-375");
  await ctx.close();
});

test("B9 the sidebar returns to the last queue after a reload; assignee filter", async ({ page }) => {
  const { tag } = run();
  await signIn(page, `clerk.${tag}@example.invalid`);
  await page.goto("/exceptions?status=open,pending_approval,resolved,waived,auto_closed");
  const first = page.locator(".queue-table tbody tr").first();
  await expect(first).toBeVisible();
  // Assign the first case to me through the bulk bar, then filter by "Me".
  await first.locator("input[type=checkbox]").check();
  await page.getByRole("combobox", { name: "Assign the selected exceptions" }).selectOption({ label: "Me" });
  await expect(page.getByText(/1 exception assigned to you/)).toBeVisible();
  await page.goto("/exceptions?assignee=me&status=open,pending_approval,resolved,waived,auto_closed");
  await expect(page.locator(".queue-table tbody tr")).toHaveCount(1);
  await expect(page.locator(".queue-table tbody tr").first()).toContainText("Assigned to you");
  await expect(page.getByRole("group", { name: "Queue scope" })).toContainText("Assignee");
  await shot(page, "queue-assignee-1440");
  // Leave the queue, reload the tab, and come back through the sidebar.
  await page.goto("/invoices");
  await page.reload();
  await page.locator('nav[aria-label="Main"] a[href^="/exceptions"]:visible').first().click();
  await expect(page).toHaveURL(/assignee=me/);
  await expect(page.locator(".queue-table tbody tr")).toHaveCount(1);
  const stored = await page.evaluate(() => window.sessionStorage.getItem("md.lastQueue"));
  expect(stored).toBe("/exceptions?status=open%2Cpending_approval%2Cresolved%2Cwaived%2Cauto_closed&assignee=me");
});

test("B9 S-10 changed in QuickBooks from recorded responses", async ({ page }) => {
  const { tag } = run();
  await signIn(page, `controller.${tag}@example.invalid`);
  const po = (await api<{ items: { id: string }[] }>(page, "/api/v1/purchase-orders?po_number=4471")).items[0];
  await page.goto(`/purchase-orders/${po.id}`);
  await expect(page.getByTestId("changed-in-quickbooks")).toHaveCount(0);
  stack("po-change", `${TENANT} ${tag}`);
  await page.reload();
  const banner = page.getByTestId("changed-in-quickbooks");
  await expect(banner).toContainText("Ordered 100 → 80");
  await expect(banner).toContainText("matched again", { timeout: 60_000 });
  await axe(page, "purchase order with changes");
  await shot(page, "po-changed-1440");
});

test("B9 S-09 credit decision on the possibly credited case, S-13 outcomes on the governing version", async ({ page }) => {
  const { tag } = run();
  await signIn(page, `controller.${tag}@example.invalid`);
  // After the S-10 read, the vendor credit VC-DEMO-9 ties to FF-1003 only by supplier and amount.
  const inv = (await api<{ items: { id: string; doc_number: string }[] }>(page, "/api/v1/invoices?limit=200")).items.find((i) => i.doc_number === "FF-1003")!;
  await page.goto(`/invoices/${inv.id}`);
  const decision = page.getByRole("group", { name: "Credit decision" });
  await expect(decision).toContainText("VC-DEMO-9", { timeout: 30_000 });
  await expect(decision).toContainText("listed as undecided, not as a finding");
  await decision.scrollIntoViewIfNeeded();
  await shot(page, "credit-decision-1440");
  await decision.getByRole("button", { name: "Credited", exact: true }).click();
  await expect(page.getByText(/Recorded: credited/)).toBeVisible();
  await expect(page.getByText(/Credited in QuickBooks \(VC-DEMO-9\), decided by the controller/).first()).toBeVisible({ timeout: 30_000 });
  // S-13: make the approved October version governing, then record what happened to a finding.
  const reports = await api<{ items: { id: string; status: string }[] }>(page, "/api/v1/reports/backtest?limit=20");
  const approved = reports.items.find((r) => r.status === "approved")!;
  await page.goto(`/reports/backtest/${approved.id}`);
  await page.getByRole("button", { name: /Make version \d+ the governing version/ }).click();
  await page.getByRole("button", { name: "Make it governing" }).click();
  const outcomes = page.getByRole("region", { name: "8. What happened to the flagged discrepancies" });
  await outcomes.getByRole("button", { name: "Record confirmation" }).first().click();
  await page.getByRole("dialog").getByRole("button", { name: "Record" }).click();
  await expect(page.getByText("Confirmation recorded.")).toBeVisible();
  await outcomes.getByRole("button", { name: "Record credit recovered" }).first().click();
  await page.getByRole("dialog").getByLabel("Or the QuickBooks credit or refund reference").fill("Vendor credit VC-DEMO-10 (synthetic)");
  await page.getByRole("dialog").getByRole("button", { name: "Record" }).click();
  await expect(page.getByTestId("credit-recovered")).toContainText("1 item recorded");
  await axe(page, "report with outcomes");
  await outcomes.scrollIntoViewIfNeeded();
  await shot(page, "report-outcomes-1440");
});

test("B9 archive, deletion request and the operator's schedule", async ({ page }) => {
  const { tag } = run();
  await signIn(page, `controller.${tag}@example.invalid`);
  await page.goto("/settings/users");
  await page.getByRole("button", { name: "Prepare an archive" }).click();
  const dl = page.getByRole("button", { name: "Download the archive" });
  await expect(dl).toBeVisible({ timeout: 60_000 });
  const [file] = await Promise.all([page.waitForEvent("download"), dl.click()]);
  expect(file.suggestedFilename()).toMatch(/^matchdesk-archive-\d{4}-\d{2}-\d{2}\.zip$/);
  await page.getByRole("button", { name: "Request deletion" }).click();
  const dialog = page.getByRole("dialog", { name: "Request deletion of this account" });
  await expect(dialog.getByRole("button", { name: "Request deletion" })).toBeDisabled();
  await dialog.getByLabel(/Type the account name/).fill(`${TENANT} ${tag}`);
  await dialog.getByRole("button", { name: "Request deletion" }).click();
  await expect(page.getByText(/Deletion requested on/)).toBeVisible();
  await axe(page, "users and account data");
  await shot(page, "account-data-1440");
  // The operator schedules it with 30 days' notice; the controller then cancels.
  await page.context().clearCookies(); // a new person signs in on this browser
  await signInOperator(page, `operator.${tag}@example.invalid`);
  const panel = page.getByRole("region", { name: "Account deletion requests" });
  await expect(panel).toContainText(`${TENANT} ${tag}`);
  await panel.getByRole("button", { name: "Schedule deletion" }).first().click();
  await page.getByRole("dialog").getByRole("button", { name: "Schedule deletion" }).click();
  await expect(page.getByText(/Deletion scheduled for/)).toBeVisible();
  await shot(page, "operator-deletion-1440");
  await page.context().clearCookies();
  await signIn(page, `controller.${tag}@example.invalid`);
  await page.goto("/settings/users");
  await expect(page.getByText(/Scheduled: every document, report and audit event/)).toBeVisible();
  await page.getByRole("button", { name: "Cancel the deletion" }).click();
  await expect(page.getByRole("button", { name: "Request deletion" })).toBeVisible();
});

test("B9 the no-receiving-records declaration on a fresh account", async ({ page }) => {
  const tag2 = `${run().tag}nr`;
  await signIn(page, `controller.${tag2}@example.invalid`);
  await page.goto("/onboarding");
  await page.getByRole("button", { name: "We have no warehouse receiving records" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Record this statement" }).click();
  await expect(page.getByTestId("no-receiving-declared")).toContainText("receipt coverage is 0%");
  await axe(page, "onboarding with the declaration");
  await shot(page, "no-receiving-1440");
});
