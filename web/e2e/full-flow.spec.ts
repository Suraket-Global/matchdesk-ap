import path from "node:path";
import { readdirSync } from "node:fs";
import { expect, test } from "@playwright/test";
import { axe, run, signIn, signOut } from "./helpers";

// E2E-01: the whole product as docs/PLAY.md tells the owner to play it, clerk then controller.
test("E2E-01 clerk loads the month and resolves, controller approves and exports", async ({ page }) => {
  const { tag, files } = run();
  const clerk = `clerk.${tag}@example.invalid`;
  const controller = `controller.${tag}@example.invalid`;

  await page.goto("/login");
  await axe(page, "sign in");
  await signIn(page, clerk);
  await expect(page.getByRole("heading", { name: "Onboarding checklist" })).toBeVisible();

  // S-05: receiving file, columns matched automatically, one row rejected, seven imported.
  await page.getByRole("link", { name: "Receiving", exact: true }).click();
  await page.locator("#rfile").setInputFiles(path.join(files, "receiving-warehouse-log.csv"));
  await page.getByLabel("Who keeps this record").fill("Demo Receiver");
  await page.getByRole("button", { name: "Upload and preview" }).click();
  await expect(page.getByRole("heading", { name: "1. Match the columns" })).toBeVisible();
  await page.getByRole("button", { name: "Check rows" }).click();
  await expect(page.getByText("7 rows valid, 1 rejected.")).toBeVisible();
  await expect(page.getByRole("cell", { name: "Unknown PO number" })).toBeVisible();
  await page.getByRole("button", { name: "Import 7 valid rows" }).click();
  await expect(page.getByText(/Imported 7 rows\./)).toBeVisible();

  // S-06: thirteen files, one byte-identical copy; totals add up.
  await page.getByRole("link", { name: "Intake", exact: true }).click();
  const pdfs = readdirSync(path.join(files, "invoices")).map((f) => path.join(files, "invoices", f));
  expect(pdfs).toHaveLength(13);
  await page.locator(".dropzone input[type=file]").setInputFiles(pdfs);
  await expect(page).toHaveURL(/\/intake\/batches\//, { timeout: 60_000 });
  await expect(page.getByText(/Reading 13 files\. 10 ready, 2 need review, 0 failed, 1 duplicate, 0 still in progress\./).first()).toBeVisible({
    timeout: 90_000,
  });
  await axe(page, "batch");

  // S-07: FF-1006 prints a wrong total; the clerk corrects it beside the PDF.
  await page.getByRole("row", { name: /FF-1006/ }).getByRole("link", { name: "Review extraction" }).click();
  await expect(page.getByText("Lines + tax = 0.80, document total 8.00")).toBeVisible();
  await expect(page.locator("canvas")).toBeVisible();
  await page.getByLabel("Total", { exact: true }).fill("0.80");
  await expect(page.getByText("All arithmetic checks pass.")).toBeVisible();
  await axe(page, "extraction review");
  await page.getByRole("button", { name: "Confirm and match" }).click();
  await expect(page.getByRole("heading", { name: /Invoice FF-1006/ })).toBeVisible();

  // S-07: SS-5120 has no supplier name; the clerk chooses the supplier.
  await page.goto("/invoices?state=needs_review");
  await page.getByRole("link", { name: "SS-5120" }).click();
  await page.locator("#h-vendor_id").selectOption({ label: "Synthetic Supply Co" });
  await page.getByRole("button", { name: "Confirm and match" }).click();
  await expect(page.getByRole("heading", { name: /Invoice SS-5120/ })).toBeVisible();

  // S-08 and S-09: the queue, then waive the small "no purchase order" line with a note.
  await page.getByRole("link", { name: "Exceptions", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Exception queue" })).toBeVisible();
  await expect(page.locator("tbody tr").first()).toBeVisible();
  await axe(page, "exception queue");
  await page.getByRole("button", { name: /No purchase order/ }).click();
  await expect(page).toHaveURL(/type=no_po/);
  await page.getByRole("link", { name: "FF-1007" }).click();
  await expect(page.getByRole("heading", { name: /Invoice FF-1007/ })).toBeVisible();
  await expect(page.locator(".workings .sentence")).toBeVisible();
  await axe(page, "match view");
  await page.locator("#res-code").selectOption("waived");
  await page.locator("#res-note").fill("PO 4999 does not exist; trivial amount (synthetic).");
  await page.getByRole("button", { name: "Resolve and next" }).click();
  await expect(page.getByRole("heading", { name: "Exception queue" })).toBeVisible();

  // The match view never counts the QuickBooks billed quantity as received (DD-06).
  await page.goto("/exceptions?type=qty_over_received");
  await page.getByRole("link", { name: "FF-1003" }).click();
  await expect(page.locator(".workings .sentence")).toContainText("Received to date 60 EA.");
  await expect(page.locator(".workings .sentence")).toContainText("Excess 40 × 4.2 = 168.00.");
  await expect(page.getByText("receiving-warehouse-log.csv row 4")).toBeVisible();

  await signOut(page, "Demo Clerk");

  // Controller: approvals land first, then the report.
  await signIn(page, controller);
  await expect(page.getByRole("heading", { name: "Approvals" })).toBeVisible();
  await axe(page, "approvals");
  await page.getByRole("row", { name: /CT-25/ }).getByRole("button", { name: "Approve" }).click();
  await expect(page.getByRole("dialog")).toContainText("1 CS of Imaginary Packaging Inc code CT-25 = 25 EA");
  await page.getByRole("dialog").getByRole("button", { name: "Approve" }).click();
  await expect(page.getByText("Approved. The affected lines are being re-matched.")).toBeVisible();

  await page.getByRole("link", { name: "Reports", exact: true }).click();
  await page.getByLabel("Test month").fill("2026-10");
  await page.getByRole("button", { name: /Create draft for October 2026/ }).click();
  await expect(page.getByText(/DRAFT · version \d+ · figures may change\./)).toBeVisible();
  // Matching after the approval may still be running: refresh until nothing blocks approval.
  for (let i = 0; i < 10; i++) {
    if (!(await page.getByText("Before this version can be approved:").isVisible())) break;
    await page.waitForTimeout(2000);
    await page.getByRole("button", { name: "Refresh draft" }).click();
    await expect(page.getByText(/DRAFT · version \d+/)).toBeVisible();
  }
  await expect(page.getByText("Before this version can be approved:")).toHaveCount(0);
  await axe(page, "report");
  const draftPdf = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export PDF" }).click();
  expect((await draftPdf).suggestedFilename()).toMatch(/-draft\.pdf$/);

  await page.getByRole("button", { name: /^Approve version \d+$/ }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("Approved figures cannot be changed");
  await dialog.getByRole("checkbox").check();
  await dialog.getByRole("button", { name: /^Approve version/ }).click();
  await expect(page.getByText(/APPROVED by Demo Controller/)).toBeVisible();
  await expect(page.getByText(/Qualifying discrepancies in this version: CAD [\d,]+\.\d\d\. Threshold CAD 500\.00\./)).toBeVisible();
  const approvedPdf = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export PDF" }).click();
  expect((await approvedPdf).suggestedFilename()).toMatch(/-approved\.pdf$/);
  const csv = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export CSV" }).click();
  expect((await csv).suggestedFilename()).toMatch(/\.csv$/);

  // S-17: the audit log shows what happened, read only.
  await page.goto("/audit");
  await expect(page.getByRole("cell", { name: /Report/i }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: /delete|edit/i })).toHaveCount(0);
});

test("a clerk who opens /approvals sees forbidden, and an unknown route is not found", async ({ page }) => {
  const { tag } = run();
  await signIn(page, `clerk.${tag}@example.invalid`);
  await page.goto("/approvals");
  await expect(page.getByRole("heading", { name: "Your role does not include this page" })).toBeVisible();
  await page.goto("/no/such/page");
  await expect(page.getByRole("heading", { name: "Not found" })).toBeVisible();
  await page.goto("/invoices/00000000-0000-0000-0000-000000000000");
  await expect(page.getByText(/Not found\. It may have been removed/)).toBeVisible();
});

test("phone width keeps the reading screens usable without sideways scrolling", async ({ browser }) => {
  const { tag } = run();
  const ctx = await browser.newContext({ viewport: { width: 375, height: 812 } });
  const page = await ctx.newPage();
  await signIn(page, `controller.${tag}@example.invalid`);
  for (const p of ["/onboarding", "/approvals", "/reports", "/settings/quickbooks", "/settings/users"]) {
    await page.goto(p);
    await expect(page.locator("main h1")).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow, p).toBeLessThanOrEqual(1);
  }
  await ctx.close();
});
