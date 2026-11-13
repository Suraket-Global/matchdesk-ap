// B10 on Playwright's own stack, after B9 (file order): the outside deep-QA findings that a browser
// shows. Pasting "1,000" into S-07 used to throw "Cannot convert 1,000 to a BigInt" and replace the
// page with "This page could not be shown".
import { expect, test } from "@playwright/test";
import { run, signIn } from "./helpers";

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
