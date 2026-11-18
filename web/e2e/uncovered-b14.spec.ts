// B14 (2026-11-17) on Playwright's own stack, after every earlier file (file order): the Critical and
// Major findings of the independent acceptance test walked in the browser on a fresh preloaded
// tenant, and what that test could not reach: dragging a pane, voiding an import, creating and
// retiring an alias, reopening an exception. All data synthetic; the account is created here.
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { ROOT, stack } from "./stack";
import { linkFor, run, signIn, signOut } from "./helpers";

const PY = path.join(ROOT, "backend/.venv/bin/python");
const E2E_DB = "postgresql+psycopg://matchdesk_app@localhost:5432/matchdesk_e2e";
const TENANT = "Demo Distributor Ltd (synthetic)";
const tag = () => `${run().tag}b14`;
const dir = mkdtempSync(path.join(os.tmpdir(), "matchdesk-b14-"));

/** A synthetic invoice PDF in the demo's own layout (backend/scripts/seed_demo.py). */
function invoicePdf(number: string, day: string, po: string, code: string, desc: string, qty: number, price: string): Buffer {
  const file = path.join(dir, `${number}.pdf`);
  const src = `import sys, pathlib; sys.path.insert(0, "scripts"); from seed_demo import invoice_pdf; pathlib.Path(sys.argv[1]).write_bytes(invoice_pdf("Fictional Fasteners Ltd", sys.argv[2], sys.argv[3], sys.argv[4], [(sys.argv[5], sys.argv[6], int(sys.argv[7]), "EA", sys.argv[8])], [], None))`;
  execFileSync(PY, ["-c", src, file, number, day, po, code, desc, String(qty), price], { cwd: path.join(ROOT, "backend") });
  return readFileSync(file);
}

async function api<T>(page: Page, url: string, init?: { method: string; body?: unknown; ifMatch?: number }): Promise<T> {
  return page.evaluate(
    async ({ url, init }) => {
      const me = await (await fetch("/api/v1/me")).json();
      const headers: Record<string, string> = { "X-CSRF-Token": me.csrf_token };
      if (init?.ifMatch !== undefined) headers["If-Match"] = String(init.ifMatch);
      if (init?.body !== undefined) headers["Content-Type"] = "application/json";
      const r = await fetch(url, { method: init?.method ?? "GET", headers, body: init?.body !== undefined ? JSON.stringify(init.body) : undefined });
      return r.json();
    },
    { url, init },
  ) as Promise<T>;
}

type Inv = { id: string; doc_number: string | null };
type Exc = { id: string; invoice_id: string; type: string; status: string; doc_number: string; reported_amount: string | null; version: number };
const invoiceId = async (page: Page, number: string) => (await api<{ items: Inv[] }>(page, "/api/v1/invoices?limit=200")).items.find((i) => i.doc_number === number)!.id;
const openExceptions = async (page: Page) => (await api<{ items: Exc[]; total_value: string }>(page, "/api/v1/exceptions?status=open,pending_approval&limit=200&period_start=2026-10-01&period_end=2026-10-31"));

/** Nothing is being matched and nothing is out of date on this invoice (acceptance C1). */
async function settledView(page: Page, number: string): Promise<void> {
  await page.goto(`/invoices/${await invoiceId(page, number)}`);
  await expect(page.getByRole("heading", { name: new RegExp(`Invoice ${number}`) })).toBeVisible();
  await expect(page.getByText(/^Matching…/)).toHaveCount(0, { timeout: 30_000 });
  await expect(page.locator(".lines-tabs").getByText("Out of date")).toHaveCount(0);
}

test.beforeAll(() => {
  execFileSync("psql", ["-q", "-d", "matchdesk_e2e", "-c", "delete from auth_rate_events"]);
  stack("seed", "--tag", tag(), "--preload", "--files-dir", path.join(dir, "play"));
});

test("B14 C1, M3, M1: a draft receiving file dates nothing; refused files stay on the batch; a possible duplicate is the exception shown", async ({ page }) => {
  await signIn(page, `clerk.${tag()}@example.invalid`);
  await settledView(page, "FF-1003");
  // C1 (a): a second receiving file, uploaded and left as a draft (PLAY.md section 10 step 3).
  await page.goto("/receiving");
  await page.locator("#rfile").setInputFiles({ name: "second-log.csv", mimeType: "text/csv", buffer: Buffer.from("PO,Line,Qty,UOM,Received,Receiver\n4471,1,5,EA,2026-10-12,R-2001\n") });
  await page.getByRole("button", { name: "Upload and preview" }).click();
  await expect(page.getByRole("button", { name: "Check rows" })).toBeVisible();
  await page.getByRole("button", { name: "Check rows" }).click();
  await expect(page.getByLabel("Validation result")).toBeVisible();
  for (const n of ["FF-1003", "SS-5102", "IP-301"]) await settledView(page, n);

  // M3: a file that is not a PDF, an empty file and a real invoice in one upload.
  await page.goto("/intake");
  await page.locator('input[type="file"]').first().setInputFiles([
    { name: "junk.pdf", mimeType: "application/pdf", buffer: Buffer.from("this is not a PDF") },
    { name: "empty.pdf", mimeType: "application/pdf", buffer: Buffer.alloc(0) },
    { name: "FF-1010.pdf", mimeType: "application/pdf", buffer: invoicePdf("FF-1010", "2026-10-05", "4390", "HB-M8", "Hex bolt M8", 250, "0.42") },
  ]);
  await expect(page).toHaveURL(/\/intake\/batches\//);
  await expect(page.getByRole("heading", { name: "2 files refused" })).toBeVisible();
  await expect(page.getByText("junk.pdf")).toBeVisible();
  await expect(page.getByText("Not a PDF, PNG or JPEG file")).toBeVisible();
  await expect(page.getByText("The file is empty")).toBeVisible();
  await expect(page.getByText(/3 files chosen: 2 refused and not read\./).first()).toBeVisible();
  await expect(page.getByRole("group", { name: "Files: 3" })).toBeVisible();
  await expect(page.getByText(/1 ready/).first()).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText("Every file in this batch is read. Nothing needs review.")).toHaveCount(0);
  await expect(page.getByText(/2 files refused and not read; their names and reasons are below/)).toBeVisible();
  await page.reload(); // still there after a reload: it is the server's record, not a flash
  await expect(page.getByText("junk.pdf")).toBeVisible();

  // M1: FF-1010 has the total of FF-1001 three days later, and over-bills its PO line as well.
  await expect.poll(async () => (await openExceptions(page)).items.filter((e) => e.doc_number === "FF-1010").map((e) => e.type).sort(), { timeout: 60_000 }).toContain("possible_duplicate");
  const mine = (await openExceptions(page)).items.filter((e) => e.doc_number === "FF-1010");
  expect(mine.length).toBeGreaterThan(1); // a line exception too: the case the tester hit
  // M2: the document's money once in the queue.
  expect(mine.reduce((a, e) => a + Math.round(Number(e.reported_amount ?? "0") * 100), 0)).toBe(10500);
  await page.goto("/exceptions?type=possible_duplicate");
  const dupRow = page.locator(".queue-table tbody tr", { hasText: "FF-1010" });
  await expect(dupRow).toContainText("Possible duplicate");
  await dupRow.getByRole("link", { name: "Review" }).click();
  const panel = page.getByRole("region", { name: "Resolution" });
  await expect(panel.getByRole("heading", { name: "Possible duplicate" })).toBeVisible();
  await expect(panel.getByText("About the whole document, not one line.")).toBeVisible();
  await expect(panel.getByText("Waiting for the controller's decision.")).toBeVisible();
  await expect(panel.getByLabel("Resolve as")).toHaveCount(0); // never another exception's controls
  await expect(page.getByRole("heading", { name: /Invoice FF-1010 whole document/ })).toBeVisible();
  const url = page.url();
  await signOut(page, "Demo Clerk");

  await signIn(page, `controller.${tag()}@example.invalid`);
  await page.goto(url);
  const ctl = page.getByRole("region", { name: "Resolution" });
  await expect(ctl.getByRole("heading", { name: "Possible duplicate" })).toBeVisible();
  await ctl.getByRole("radio", { name: /Is a duplicate/ }).check();
  await expect(ctl.getByTestId("decision-effect")).toContainText("CAD 105.00");
  await ctl.getByRole("button", { name: "Confirm: Is a duplicate" }).click();
  await expect(page.getByText(/Recorded: is a duplicate/)).toBeVisible();
  await expect.poll(async () => (await openExceptions(page)).items.filter((e) => e.doc_number === "FF-1010").map((e) => `${e.type} ${e.reported_amount}`), { timeout: 60_000 }).toEqual(["duplicate 105.00"]);
  await settledView(page, "FF-1010");
});

test("B14 C2, C1 (b)(c), M4: a decided credit raises no finding; nothing is left out of date; the PDF reads as a document", async ({ page }) => {
  await signIn(page, `controller.${tag()}@example.invalid`);
  // A tolerance save re-matches every supplier (the step before the tester's credit decision).
  const tol = await api<{ match_run_id: string | null }>(page, "/api/v1/tolerances/default", { method: "PUT", body: { price_tol_abs: "0.02" } });
  expect(tol).toBeTruthy();
  stack("po-change", `${TENANT} ${tag()}`); // PO 4471 ordered 80 instead of 100; VC-DEMO-9 appears
  await expect.poll(async () => (await openExceptions(page)).items.filter((e) => e.doc_number === "FF-1003").map((e) => e.type).sort(), { timeout: 90_000 }).toEqual(["qty_over_ordered", "qty_over_received"]);
  const before = (await openExceptions(page)).items.filter((e) => e.doc_number === "FF-1003");
  expect(before.find((e) => e.type === "qty_over_received")!.reported_amount).toBe("168.00");
  expect(before.find((e) => e.type === "qty_over_ordered")!.reported_amount).toBe("0.00");
  const totalBefore = Number((await openExceptions(page)).total_value);
  const over = before.find((e) => e.type === "qty_over_received")!;
  await page.goto(`/invoices/${over.invoice_id}?exc=${over.id}`);
  const panel = page.getByRole("region", { name: "Resolution" });
  await expect(panel.getByText("Possibly credited in QuickBooks")).toBeVisible();
  await panel.getByRole("radio", { name: /^Credited/ }).check();
  await panel.getByRole("button", { name: "Confirm: Credited" }).click();
  await expect(page.getByText(/Recorded: credited/)).toBeVisible();
  // C2: nothing open is left on FF-1003, and the queue lost exactly the 168.00, not 84.00 less.
  await expect.poll(async () => (await openExceptions(page)).items.filter((e) => e.doc_number === "FF-1003").length, { timeout: 60_000 }).toBe(0);
  expect(Math.round((totalBefore - Number((await openExceptions(page)).total_value)) * 100)).toBe(16800);
  await page.goto("/exceptions");
  await expect(page.locator(".queue-table tbody tr", { hasText: "FF-1003" })).toHaveCount(0);
  await page.goto(`/invoices/${over.invoice_id}`);
  await expect(page.locator(".ledger")).toContainText("Credited");
  await expect(page.locator(".ledger")).not.toContainText("Exposure");
  // C1 (b): the other suppliers' invoices are not out of date after the decision.
  for (const n of ["SS-5102", "IP-301", "FF-1001"]) await settledView(page, n);
  // C1 (c): a document deleted by the controller after the all-supplier run.
  await page.goto(`/invoices/${await invoiceId(page, "FF-1004")}/review`);
  await page.getByRole("button", { name: "Delete document" }).click();
  const del = page.getByRole("dialog");
  await del.getByLabel("Reason").fill("Uploaded by mistake (synthetic)");
  await del.getByRole("button", { name: "Delete document" }).click();
  await expect(page).toHaveURL(/\/invoices$/);
  for (const n of ["SS-5102", "IP-302", "FF-1003"]) await settledView(page, n);

  // The report draft is never blocked by out-of-date results, and FF-1003 is in no finding.
  const draft = await api<{ id: string; blocking: string[]; findings_amount: string; qualifying_amount: string }>(page, "/api/v1/reports/backtest", { method: "POST", body: { period_start: "2026-10-01", period_end: "2026-10-31" } });
  expect(draft.blocking.filter((b) => /out of date|out-of-date/.test(b))).toEqual([]);
  const full = await api<{ findings: { section: string; amount: string; qualifying: boolean; snapshot: { doc_number: string } }[]; flagged_amount: string }>(page, `/api/v1/reports/backtest/${draft.id}`);
  expect(full.findings.filter((f) => f.snapshot.doc_number === "FF-1003" && (f.qualifying || ["finding", "not_received"].includes(f.section)))).toEqual([]);
  await page.goto(`/reports/backtest/${draft.id}`);
  await expect(page.getByText("Lines with out-of-date results")).toHaveCount(0);
  await expect(page.getByTestId("deleted-after-approval")).toHaveCount(0); // nothing approved before the deletion
  // M4: the PDF of this draft, read back.
  const pdf = await page.evaluate(async (id) => {
    const r = await fetch(`/api/v1/reports/backtest/${id}/export?format=pdf`);
    return new TextDecoder("latin1").decode(await r.arrayBuffer());
  }, draft.id);
  const lines = [...pdf.matchAll(/\((.*)\) Tj T\*/g)].map((m) => m[1].replace(/\\([()\\])/g, "$1"));
  expect(Math.max(...lines.map((l) => l.length))).toBeLessThanOrEqual(96);
  const text = lines.join("\n");
  expect(text).toContain("MatchDesk back-test report");
  expect(text).toContain(`Account: ${TENANT} ${tag()}`);
  expect(text).not.toMatch(/\b[a-z]+_[a-z_]+\b/); // no internal code
  expect(text).not.toMatch(/\d{4}-\d{2}-\d{2}T\d{2}:/); // no raw timestamp
  for (const s of new Set(full.findings.map((f) => f.snapshot as unknown as { vendor_name?: string }).map((s) => s.vendor_name).filter(Boolean))) expect(text.replace(/\s+/g, " ")).toContain(String(s).split(" ")[0]);
  const figure = (label: string) => lines.find((l) => l.trim().startsWith(label))!.trim().split(/\s+/).pop();
  expect(figure("Flagged discrepancies")).toBe(full.flagged_amount);
  expect(figure("Qualifying total for the refund")).toBe(draft.qualifying_amount);
  await expect(page.getByText(new RegExp(`CAD ${full.flagged_amount.replace(/\B(?=(\d{3})+(?!\d))/g, ",")}`)).first()).toBeVisible(); // the screen's figure
});

test("B14 coverage: pane drag, reopen, alias create and retire, void an import", async ({ page }) => {
  await signIn(page, `controller.${tag()}@example.invalid`);
  // Pane drag-resize (S-09): the first handle dragged right widens the document pane; the value
  // follows the pointer and is kept on reload.
  await page.goto(`/invoices/${await invoiceId(page, "SS-5102")}`);
  const sep = page.getByRole("separator").first();
  await expect(sep).toHaveAttribute("aria-valuenow", "36");
  const grid = (await page.locator(".match-grid").boundingBox())!;
  const box = (await sep.boundingBox())!;
  const doc0 = (await page.locator(".pane-doc").boundingBox())!.width;
  await page.mouse.move(box.x + box.width / 2, box.y + 80);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 + grid.width * 0.1, box.y + 80, { steps: 8 });
  await page.mouse.up();
  const now = Number(await sep.getAttribute("aria-valuenow"));
  expect(now).toBeGreaterThanOrEqual(44);
  expect(now).toBeLessThanOrEqual(48);
  expect((await page.locator(".pane-doc").boundingBox())!.width).toBeGreaterThan(doc0 + grid.width * 0.07);
  await page.reload();
  await expect(page.getByRole("separator").first()).toHaveAttribute("aria-valuenow", String(now));
  // Dragged far past the limit, a pane never collapses and the page never scrolls sideways.
  const b2 = (await page.getByRole("separator").first().boundingBox())!;
  await page.mouse.move(b2.x + b2.width / 2, b2.y + 80);
  await page.mouse.down();
  await page.mouse.move(grid.x + grid.width + 400, b2.y + 80, { steps: 6 });
  await page.mouse.up();
  expect((await page.locator(".pane-act").boundingBox())!.width).toBeGreaterThan(150);
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(1);
  await page.getByRole("separator").first().dblclick();
  await expect(page.getByRole("separator").first()).toHaveAttribute("aria-valuenow", "36");

  // Reopen an exception (S-09): resolve one, then reopen it; history is kept.
  const target = (await openExceptions(page)).items.find((e) => e.type === "price_variance" || e.type === "qty_over_received")!;
  await page.goto(`/invoices/${target.invoice_id}?exc=${target.id}`);
  const panel = page.getByRole("region", { name: "Resolution" });
  await panel.getByLabel("Resolve as").selectOption("confirmed_overbilling");
  await panel.getByRole("button", { name: /^Resolve/ }).click();
  await expect(page.getByText(/Resolved: Confirmed overbilling/)).toBeVisible();
  await page.goto(`/invoices/${target.invoice_id}?exc=${target.id}`); // "Resolve and next" moved on
  await expect(panel.getByText(/Resolved as Confirmed overbilling/)).toBeVisible();
  await panel.getByRole("button", { name: "Reopen" }).click();
  await expect(page.getByText("Reopened. History is kept.")).toBeVisible();
  await expect(panel.getByLabel("Resolve as")).toBeVisible();
  const events = await api<{ items: { event: string }[] }>(page, `/api/v1/exceptions/${target.id}/events`);
  expect(events.items.map((e) => e.event)).toEqual(expect.arrayContaining(["resolved", "reopened"]));
  expect((await openExceptions(page)).items.some((e) => e.id === target.id)).toBe(true);

  // Alias: retire one in the screen, then create it again; both re-match and nothing stays stale.
  // (The demo has another alias waiting for approval, so the count is compared with the start.)
  const unresolved = async () => (await openExceptions(page)).items.filter((e) => e.type === "alias_unconfirmed" || e.type === "po_line_not_found").length;
  const atStart = await unresolved();
  await page.goto("/aliases");
  const row = page.locator("table tbody tr", { hasText: "HB-M8" }).first();
  await expect(row).toBeVisible();
  await row.getByRole("button", { name: "Retire" }).click();
  await page.getByRole("dialog").getByLabel("Reason (required)").fill("Wrong item (synthetic)");
  await page.getByRole("dialog").getByRole("button", { name: "Retire alias" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect.poll(async () => (await api<{ items: { supplier_item_code: string; status: string }[] }>(page, "/api/v1/aliases?limit=200")).items.filter((a) => a.supplier_item_code === "HB-M8" && a.status === "retired").length).toBe(1);
  await expect.poll(unresolved, { timeout: 60_000 }).toBeGreaterThan(atStart);
  await settledView(page, "FF-1001");
  const aliases = await api<{ items: { id: string; vendor_id: string; item_id: string; supplier_item_code: string; status: string }[] }>(page, "/api/v1/aliases?limit=200");
  const retired = aliases.items.find((a) => a.supplier_item_code === "HB-M8" && a.status === "retired")!;
  expect(retired).toBeTruthy();
  await page.goto(`/aliases?vendor=${retired.vendor_id}&code=HB-M8`);
  await page.getByLabel("Our item", { exact: true }).selectOption(retired.item_id);
  await page.getByRole("button", { name: "Confirm alias" }).click();
  await expect.poll(async () => (await api<typeof aliases>(page, "/api/v1/aliases?limit=200")).items.filter((a) => a.supplier_item_code === "HB-M8" && a.status === "active").length, { timeout: 30_000 }).toBe(1);
  await expect.poll(unresolved, { timeout: 60_000 }).toBe(atStart);
  await settledView(page, "FF-1001");

  // Void an import (S-05): its receipt lines stop counting; the lines it covered become receipt
  // absent, never matched, and every result is current again.
  const imports = await api<{ items: { id: string; state: string }[] }>(page, "/api/v1/receiving/imports?limit=50");
  const committed = imports.items.find((i) => i.state === "succeeded")!;
  await page.goto(`/receiving/imports/${committed.id}`);
  await page.getByRole("button", { name: "Void import" }).click();
  await page.getByRole("dialog").getByLabel("Reason (required)").fill("Wrong month's log (synthetic)");
  await page.getByRole("dialog").getByRole("button", { name: "Void import" }).click();
  await expect(page.getByText(/Voided: Wrong month's log/)).toBeVisible();
  await expect.poll(async () => (await openExceptions(page)).items.filter((e) => e.type === "receipt_absent").length, { timeout: 60_000 }).toBeGreaterThan(3);
  for (const n of ["FF-1001", "SS-5102", "IP-301"]) await settledView(page, n);
  await page.goto(`/invoices/${await invoiceId(page, "FF-1001")}`);
  await expect(page.locator(".lines-tabs")).toContainText("Receipt absent");
  await expect(page.locator(".lines-tabs")).not.toContainText("Matched");
});

test("B14 M5: the operator creates an account and its first controller signs in", async ({ page, browser }) => {
  const op = `operator.${tag()}@example.invalid`;
  await page.goto("/login");
  await page.getByLabel("Work email").fill(op);
  const asked = Date.now();
  await page.getByRole("button", { name: "Email me a sign-in link" }).click();
  await expect(page.getByText("If that address has access, a link is on its way.")).toBeVisible();
  await page.goto(await linkFor(op, asked));
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  const codeField = page.getByLabel("One-time code from your authenticator app");
  await expect(codeField).toBeVisible();
  // m6: a wrong code says so.
  await codeField.fill("000000");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByText("That code was not accepted.")).toBeVisible();
  await new Promise((r) => setTimeout(r, 31_000 - (Date.now() % 30_000)));
  const code = execFileSync(PY, [path.join(ROOT, "backend/scripts/operator_code.py"), op], { cwd: path.join(ROOT, "backend"), env: { ...process.env, MATCHDESK_DATABASE_URL: E2E_DB } }).toString().split(" ")[0];
  await codeField.fill(code);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Operator console" })).toBeVisible();

  const name = `Fictional Newco ${tag()}`;
  const first = `first.${tag()}@example.invalid`;
  await page.getByText("Create a pilot account").click();
  await page.getByLabel("Company name").fill(name);
  const create = page.getByRole("button", { name: "Create account and invite" });
  await expect(create).toBeDisabled(); // no account without its first controller
  await page.getByLabel("First controller's email").fill(first);
  const sent = Date.now();
  await create.click();
  await expect(page.getByRole("heading", { name })).toBeVisible();
  const panel = page.getByTestId("first-controller");
  await expect(panel).toContainText("Invitation sent");
  await expect(panel).toContainText(first);
  // The same name again is refused; one account exists.
  await page.goto("/operator/tenants");
  await page.getByText("Create a pilot account").click();
  await page.getByLabel("Company name").fill(name);
  await page.getByLabel("First controller's email").fill(first);
  await page.getByRole("button", { name: "Create account and invite" }).click();
  await expect(page.getByText(/already exists/)).toBeVisible();
  await expect(page.getByRole("link", { name })).toHaveCount(1);

  // The invited controller, in a browser of their own.
  const ctx = await browser.newContext();
  const theirs = await ctx.newPage();
  const link = await linkFor(first, sent);
  expect(link).toContain("/invite#t=");
  await theirs.goto(link);
  await theirs.getByRole("button", { name: "Join" }).click();
  await expect(theirs.locator("header.topbar")).toBeVisible();
  // Trial guidance (2026-11-19): a new account is a 7-day free trial; its controller is offered the
  // guided tour once, walks it with Next, and the bar names the next step.
  const shots = path.join(ROOT, "docs/screenshots/trial");
  const tour = theirs.getByTestId("tour");
  await expect(tour).toBeVisible();
  await expect(tour).toContainText("Welcome to your 7-day free trial");
  await theirs.screenshot({ path: path.join(shots, "1-welcome.png") });
  await theirs.getByRole("button", { name: "Start the tour" }).click();
  await expect(tour).toContainText("Your checklist");
  // The highlight sits on the real menu item (no animation from the corner).
  const spotAt = async (sel: string) =>
    theirs.evaluate((q) => {
      const t = document.querySelector(q)!.getBoundingClientRect();
      const s = document.querySelector(".tour-spot")!.getBoundingClientRect();
      return Math.abs(s.top + 6 - t.top) < 2 && Math.abs(s.left + 6 - t.left) < 2;
    }, sel);
  expect(await spotAt('[data-tour="nav-onboarding"]')).toBe(true);
  await theirs.screenshot({ path: path.join(shots, "2-checklist.png") });
  for (const title of ["1. Connect QuickBooks Online", "2. Load your receiving record", "3. Upload the month's invoices", "4. Your findings"]) {
    await theirs.getByRole("button", { name: "Next" }).click();
    await expect(tour.getByRole("heading", { name: title })).toBeVisible();
  }
  expect(await spotAt('[data-tour="nav-exceptions"]')).toBe(true);
  await theirs.screenshot({ path: path.join(shots, "3-findings-example.png") });
  for (const title of ["The back-test report", "Where you are", "Help is one click away"]) {
    await theirs.getByRole("button", { name: "Next" }).click();
    await expect(tour.getByRole("heading", { name: title })).toBeVisible();
  }
  await theirs.getByRole("button", { name: "Finish" }).click();
  await expect(tour).toHaveCount(0);
  const banner = theirs.getByTestId("sample-banner");
  await expect(banner).toContainText("7-day free trial, day 1 of 7.");
  await expect(banner).toContainText("Next: connect QuickBooks Online");
  await theirs.screenshot({ path: path.join(shots, "4-banner.png") });
  await theirs.reload();
  await expect(theirs.locator("header.topbar")).toBeVisible();
  await expect(theirs.getByTestId("tour")).toHaveCount(0); // finished: not offered again
  await theirs.getByRole("button", { name: new RegExp(first) }).click();
  await theirs.getByRole("button", { name: "Take the tour" }).click();
  await expect(theirs.getByTestId("tour")).toBeVisible();
  await theirs.keyboard.press("Escape");
  await expect(theirs.getByTestId("tour")).toHaveCount(0);
  // On a phone the tour is a centred card and the page does not scroll sideways.
  await theirs.setViewportSize({ width: 375, height: 812 });
  await theirs.goto("/onboarding");
  await theirs.locator('[data-tour="user-menu"]').click(); // on a phone the button shows initials only
  await theirs.getByRole("button", { name: "Take the tour" }).click();
  await theirs.getByRole("button", { name: "Start the tour" }).click();
  await expect(theirs.getByTestId("tour")).toContainText("Your checklist");
  expect(await theirs.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await theirs.screenshot({ path: path.join(shots, "5-phone.png") });
  await theirs.getByRole("button", { name: "Skip tour" }).click();
  await theirs.setViewportSize({ width: 1440, height: 900 });
  const me = await theirs.evaluate(async () => (await fetch("/api/v1/me")).json());
  expect([me.role, me.user.email, me.memberships[0].tenant_name]).toEqual(["controller", first, name]);
  await theirs.goto("/settings/users");
  await expect(theirs.getByText(first).first()).toBeVisible();
  await ctx.close();

  await page.goto("/operator/tenants");
  await page.getByRole("link", { name }).click();
  await expect(page.getByTestId("first-controller")).toContainText("Has a controller");
  await expect(page.getByTestId("first-controller").getByRole("button", { name: "Send invitation" })).toHaveCount(0);
});
