import path from "node:path";
import { readdirSync } from "node:fs";
import { expect, test } from "@playwright/test";
import { axe, cardsAtPhoneWidth, run, signIn, signOut, tablesFit } from "./helpers";

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
  await expect(page.getByText(/13 files read: 10 ready, 2 need review, 0 failed, 1 duplicate\./).first()).toBeVisible({
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
  await tablesFit(page, "extraction review at 1440"); // B6 review M3
  await expect(page.getByLabel("Line 1 Unit price")).toBeVisible();
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
  // W3: the coverage strip is live before any report draft exists.
  await expect(page.locator(".coverage")).toContainText(/Receipt coverage \d+(\.\d+)?% of invoiced PO lines/);
  await axe(page, "exception queue");
  await tablesFit(page, "exception queue at 1440"); // B6 review M2
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
  // The type filter stays visible and says what it filters, after its last item went (review, minor).
  await expect(page.getByRole("button", { name: /No purchase order/ })).toBeVisible();
  await expect(page.getByText('No open exceptions of type "No purchase order".')).toBeVisible();

  // The match view never counts the QuickBooks billed quantity as received (DD-06).
  await page.goto("/exceptions?type=qty_over_received");
  await page.getByRole("link", { name: "FF-1003" }).click();
  await expect(page.locator(".workings .sentence")).toContainText("Received to date 60 EA.");
  await expect(page.locator(".workings .sentence")).toContainText("Excess 40 × 4.20 = 168.00.");
  await expect(page.getByText("receiving-warehouse-log.csv row 4")).toBeVisible();
  // W1: a ?from= that is not a path inside the app is ignored.
  await page.goto(`${page.url().split("&from=")[0]}&from=${encodeURIComponent("javascript:alert(1)")}`);
  await expect(page.getByRole("link", { name: "Exception queue" })).toHaveAttribute("href", "/exceptions");

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
  await tablesFit(page, "report at 1440");
  const draftPdf = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export PDF" }).click();
  expect((await draftPdf).suggestedFilename()).toMatch(/-draft\.pdf$/);

  await page.getByRole("button", { name: /^Approve version \d+$/ }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("Approved figures cannot be changed");
  await dialog.getByRole("checkbox").check();
  await dialog.getByRole("button", { name: /^Approve version/ }).click();
  await expect(page.getByText(/APPROVED by Demo Controller/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Refresh draft" })).toHaveCount(0); // review, minor
  // W2: the list and the report give the same flagged-discrepancy figure under the same words.
  const flagged = (await page.locator(".cards > div").first().locator(".big").innerText()).replace("CAD ", "").trim();
  await page.getByRole("link", { name: "Back-test reports" }).click();
  await expect(page.getByRole("columnheader", { name: /Flagged discrepancies/ })).toBeVisible();
  await expect(page.getByRole("row", { name: /Approved/ }).getByRole("cell", { name: flagged, exact: true })).toBeVisible();
  await page.goBack();
  await expect(page.getByText(/Qualifying discrepancies in this version: CAD [\d,]+\.\d\d\. Threshold CAD 500\.00\./)).toBeVisible();
  const approvedPdf = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export PDF" }).click();
  expect((await approvedPdf).suggestedFilename()).toMatch(/-approved\.pdf$/);
  const csv = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export CSV" }).click();
  expect((await csv).suggestedFilename()).toMatch(/\.csv$/);

  // App-flow S-16 and S-05 columns (review).
  await page.goto("/settings/users");
  await expect(page.getByRole("columnheader", { name: "Last sign-in" })).toBeVisible();
  await page.goto("/receiving");
  await expect(page.getByRole("columnheader", { name: "Rows waiting for controller approval" })).toBeVisible();

  // S-17: the audit log shows what happened, read only.
  await page.goto("/audit");
  await expect(page.getByRole("cell", { name: /Report/i }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: /delete|edit/i })).toHaveCount(0);
  await tablesFit(page, "audit log at 1440"); // B6 review M7
  await expect(page.locator("main table")).not.toContainText(/[0-9a-f]{8}-[0-9a-f]{4}-/); // no identifiers
  // B6 review M6: an approved report with nothing changed offers no identical new draft.
  await page.goto("/reports");
  await page.getByRole("row", { name: /Approved/ }).getByRole("link").first().click();
  await expect(page.getByRole("button", { name: /new draft version/ })).toHaveCount(0);
});

test("a clerk who opens /approvals sees forbidden, and an unknown route is not found", async ({ page }) => {
  const { tag } = run();
  await signIn(page, `clerk.${tag}@example.invalid`);
  await page.goto("/approvals");
  await expect(page.getByRole("heading", { name: "Your role does not include this page" })).toBeVisible();
  await page.goto("/no/such/page");
  await expect(page.getByRole("heading", { name: "Not found" })).toBeVisible();
  // An unknown record is the not-found page (S-19), not an error banner (review, minor).
  await page.goto("/invoices/00000000-0000-0000-0000-000000000000");
  await expect(page.getByRole("heading", { name: "Not found" })).toBeVisible();
});

test("phone width keeps the reading screens usable without sideways scrolling", async ({ browser }) => {
  const { tag } = run();
  const ctx = await browser.newContext({ viewport: { width: 375, height: 812 } });
  const page = await ctx.newPage();
  await signIn(page, `controller.${tag}@example.invalid`);
  await page.goto("/reports");
  await expect(page.locator("main h1")).toBeVisible();
  const links = page.locator("main table a");
  const report = (await links.count()) ? await links.first().getAttribute("href") : null;
  const pages = ["/onboarding", "/approvals", "/reports", "/settings/quickbooks", "/settings/users", "/invoices", "/receiving", "/audit"];
  if (report) pages.push(report);
  for (const p of pages) {
    await page.goto(p);
    await expect(page.locator("main h1")).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    // On failure, name the elements that stick out of the page (not those inside a scrolling box).
    const culprits = await page.evaluate(() =>
      [...document.querySelectorAll("body *")]
        .filter((e) => e.getBoundingClientRect().right > window.innerWidth + 1 || e.scrollWidth > e.clientWidth + 1)
        .filter((e) => !["auto", "scroll", "hidden"].includes(getComputedStyle(e).overflowX))
        .filter((e) => {
          for (let p = e.parentElement; p && p !== document.body; p = p.parentElement) if (["auto", "scroll", "hidden"].includes(getComputedStyle(p).overflowX)) return false;
          return true;
        })
        .slice(0, 5)
        .map((e) => `${e.tagName.toLowerCase()}.${String(e.className)} ${Math.round(e.getBoundingClientRect().right)}`),
    );
    expect(overflow, `${p}: ${culprits.join(", ")}`).toBeLessThanOrEqual(1);
    await cardsAtPhoneWidth(page, `${p} at 375`); // B6 review M8
  }
  await ctx.close();
});

test("an expired session goes to sign-in once and shows nothing of the old session", async ({ page, context }) => {
  // Review W8: a cached user after expiry sent sign-in back to the app, which sent it back again.
  const { tag } = run();
  await signIn(page, `clerk.${tag}@example.invalid`);
  await expect(page.locator("main h1")).toBeVisible();
  await context.clearCookies(); // the server no longer knows this browser
  await page.getByRole("link", { name: "Invoices", exact: true }).click();
  await expect(page.getByRole("heading", { name: "You are signed out." })).toBeVisible();
  await page.getByRole("link", { name: "Sign in" }).click();
  await expect(page.getByLabel("Work email")).toBeVisible();
  await page.waitForTimeout(1000);
  await expect(page.getByLabel("Work email")).toBeVisible(); // still here: no loop
  await expect(page.locator("header.topbar")).toHaveCount(0);
});
