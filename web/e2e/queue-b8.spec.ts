import { expect, test } from "@playwright/test";
import { axe, run, signIn } from "./helpers";

// B8 regression checks on Playwright's own stack, after E2E-01 has loaded and worked the month
// (files run in name order: full-flow, pieces-b7, queue-b8). Full-dataset pagination beyond row 200
// is proved at the API in backend/tests/integration/test_b8_trust.py.

test("B8 first actionable case is visible and clickable at 375 x 812", async ({ browser }) => {
  const { tag } = run();
  const ctx = await browser.newContext({ viewport: { width: 375, height: 812 } });
  const page = await ctx.newPage();
  await signIn(page, `clerk.${tag}@example.invalid`);
  await page.goto("/exceptions");
  await expect(page.getByRole("heading", { name: "Exception queue" })).toBeVisible();
  const review = page.locator(".case-list .case").first().getByRole("link", { name: /^Review / });
  await expect(review).toBeVisible();
  const box = (await review.boundingBox())!;
  const card = (await page.locator(".case-list .case").first().boundingBox())!;
  console.log(`first mobile case: card top ${Math.round(card.y)} px, review control ${Math.round(box.y)} to ${Math.round(box.y + box.height)} px of 812`);
  expect(card.y).toBeGreaterThanOrEqual(0);
  expect(box.y + box.height).toBeLessThanOrEqual(812); // in the initial viewport, no scrolling
  // Nothing covers it: the element at its centre is the control itself.
  const hit = await page.evaluate(([x, y]) => document.elementFromPoint(x, y)?.closest("a")?.textContent?.trim() ?? "", [box.x + box.width / 2, box.y + box.height / 2]);
  expect(hit).toContain("Review");
  await review.click();
  await expect(page.getByRole("heading", { level: 1, name: /^Invoice / })).toBeVisible();
  await expect(page.getByRole("region", { name: "Calculation in figures" })).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(1);
  await ctx.close();
});

test("B8 weekly drill-down, queue to case and back keep the week, supplier and position", async ({ page }) => {
  const { tag } = run();
  await signIn(page, `clerk.${tag}@example.invalid`);
  await expect(page.locator("main h1")).toBeVisible();
  const week = (await page.evaluate(async () => (await fetch("/api/v1/weekly-summary?week_start=2026-10-05", { credentials: "same-origin" })).json())) as {
    suppliers: { vendor_name: string | null; open_count: number; open_value: string }[];
  };
  const ff = week.suppliers.find((s) => s.vendor_name === "Fictional Fasteners Ltd")!;
  expect(ff.open_count).toBe(1);
  expect(ff.open_value).toBe("168.00");
  await page.goto("/reports/weekly?week=2026-10-05");
  await page.getByRole("link", { name: /open exceptions for Fictional Fasteners Ltd/ }).click();
  await expect(page).toHaveURL(/from=2026-10-05&to=2026-10-11/);
  const scope = page.getByRole("group", { name: "Queue scope" });
  await expect(scope).toContainText("5 to 11 Oct 2026");
  await expect(scope).toContainText("Fictional Fasteners Ltd");
  // The same count and amount as the report: FF-1006 (22 October) is outside the week.
  await expect(page.locator(".queue-table tbody tr")).toHaveCount(1);
  await expect(page.locator("[data-queue-total]")).toHaveText("168.00");
  await axe(page, "queue from the weekly summary");
  // Refresh keeps the scope.
  await page.reload();
  await expect(page.getByRole("group", { name: "Queue scope" })).toContainText("5 to 11 Oct 2026");
  // Open the case; the crumb names the queue; Next is off for the last case; Back returns with focus.
  await page.getByRole("link", { name: /Review FF-1003/ }).click();
  await expect(page.getByRole("heading", { name: /Invoice FF-1003/ })).toBeVisible();
  const ledger = page.getByRole("region", { name: "Calculation in figures" });
  for (const t of ["100 EA", "60 EA", "40 EA", "CAD 4.20", "CAD 168.00"]) await expect(ledger).toContainText(t);
  await expect(page.getByRole("link", { name: /Exception queue: Fictional Fasteners Ltd, 5 to 11 Oct 2026/ })).toBeVisible();
  await expect(page.getByText("1 of 1")).toBeVisible();
  await expect(page.getByRole("button", { name: /Next exception/ })).toBeDisabled();
  // The receipt beside the received quantity opens the exact receiving row.
  await ledger.getByRole("link", { name: "receiving-warehouse-log.csv row 4" }).click();
  await expect(page.locator("tr.row-target")).toContainText("60");
  await page.getByRole("link", { name: "Back to the invoice" }).click();
  await page.getByRole("link", { name: /^Exception queue/ }).click();
  await expect(page).toHaveURL(/from=2026-10-05&to=2026-10-11.*sel=/);
  await expect(page.locator(".queue-table tbody tr").first()).toBeFocused();
  // Browser Back returns to the case; clearing one filter keeps the dates.
  await page.goBack();
  await expect(page.getByRole("heading", { name: /Invoice FF-1003/ })).toBeVisible();
  await page.goForward();
  await page.getByRole("button", { name: "Remove the supplier filter" }).click();
  await expect(page).toHaveURL(/from=2026-10-05&to=2026-10-11/);
  await expect(page).not.toHaveURL(/vendor=/);
});

test("B8 an empty week is not shown as a clean week", async ({ page }) => {
  const { tag } = run();
  await signIn(page, `controller.${tag}@example.invalid`);
  await page.goto("/reports/weekly?week=2026-12-07");
  await expect(page.getByText("No invoices checked for this week")).toBeVisible();
  await expect(page.getByText("CAD 0.00")).toHaveCount(0);
});
