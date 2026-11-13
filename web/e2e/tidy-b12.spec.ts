// B12 on Playwright's own stack, after B10 (file order): the resizable S-09 panes, the controller's
// usage on S-16, and deleting one document from S-07. Runs last, because it deletes a document of
// the tagged tenant. All data synthetic.
import { execFileSync } from "node:child_process";
import { expect, test, type Page } from "@playwright/test";
import { axe, run, signIn } from "./helpers";

test.beforeAll(() => {
  // The sign-in limits are emptied on this isolated database only (as in the B9 file).
  execFileSync("psql", ["-q", "-d", "matchdesk_e2e", "-c", "delete from auth_rate_events"]);
});

async function invoices(page: Page): Promise<{ id: string; doc_number: string | null; verification_status: string }[]> {
  return page.evaluate(async () => (await (await fetch("/api/v1/invoices?limit=50")).json()).items);
}

test("B12 S-09 panes resize by keyboard, are remembered in the tab and reset by a double click", async ({ page }) => {
  const { tag } = run();
  await signIn(page, `controller.${tag}@example.invalid`);
  const inv = (await invoices(page))[0];
  await page.goto(`/invoices/${inv.id}`);
  const seps = page.getByRole("separator");
  await expect(seps).toHaveCount(2);
  const first = seps.first();
  await expect(first).toHaveAttribute("aria-valuenow", "36");
  const before = await page.locator(".pane-doc").boundingBox();
  await first.focus();
  await page.keyboard.press("Shift+ArrowRight");
  await expect(first).toHaveAttribute("aria-valuenow", "46");
  const after = await page.locator(".pane-doc").boundingBox();
  expect(after!.width).toBeGreaterThan(before!.width + 50);
  await axe(page, "S-09 with separators");
  // Remembered for this tab across a reload.
  await page.reload();
  await expect(page.getByRole("separator").first()).toHaveAttribute("aria-valuenow", "46");
  // A drag on the second handle.
  const s2 = await page.getByRole("separator").nth(1).boundingBox();
  await page.mouse.move(s2!.x + s2!.width / 2, s2!.y + 60);
  await page.mouse.down();
  await page.mouse.move(s2!.x + s2!.width / 2 - 80, s2!.y + 60, { steps: 4 });
  await page.mouse.up();
  const moved = Number(await page.getByRole("separator").nth(1).getAttribute("aria-valuenow"));
  expect(moved).toBeLessThan(46 + 40);
  await page.getByRole("separator").first().dblclick();
  await expect(page.getByRole("separator").first()).toHaveAttribute("aria-valuenow", "36");
  await expect(page.getByRole("separator").nth(1)).toHaveAttribute("aria-valuenow", "76");
  // Narrower than the three-pane layout: no handle, the panes stack as before.
  await page.setViewportSize({ width: 1000, height: 900 });
  await expect(page.getByRole("separator")).toHaveCount(0);
  await page.setViewportSize({ width: 375, height: 812 });
  await expect(page.getByRole("separator")).toHaveCount(0);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});

test("B12 the controller sees usage and deletes one document with a reason", async ({ page }) => {
  const { tag } = run();
  await signIn(page, `controller.${tag}@example.invalid`);
  await page.goto("/settings/users");
  await expect(page.getByRole("heading", { name: "Usage" })).toBeVisible();
  await expect(page.getByText(/billable units? in all/)).toBeVisible();
  const list = await invoices(page);
  const target = list[list.length - 1];
  await page.goto(`/invoices/${target.id}/review`);
  await page.getByRole("button", { name: "Delete document" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("An approved report that included it does not change.", { exact: false })).toBeVisible();
  await axe(page, "delete document dialog");
  const confirm = dialog.getByRole("button", { name: "Delete document" });
  if (target.verification_status !== "failed") {
    await expect(confirm).toBeDisabled();
    await dialog.getByLabel("Reason").fill("Uploaded to the wrong account (synthetic)");
  }
  await confirm.click();
  await expect(page).toHaveURL(/\/invoices$/);
  await expect(page.getByText(/^Deleted /).first()).toBeVisible();
  expect((await invoices(page)).map((i) => i.id)).not.toContain(target.id);
  // The document itself says so and offers nothing more.
  await page.goto(`/invoices/${target.id}`);
  await expect(page.getByText(/kept here as history/)).toBeVisible();
});
