// Runs after full-flow.spec.ts (file order): its emailed invoice must not arrive before the receiving
// file, or a late-evidence approval would be waiting in E2E-01.
import { execFileSync } from "node:child_process";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { E2E_API, ROOT } from "./stack";
import { axe, linkFor, run, signIn, signOut, tablesFit } from "./helpers";

const PY = path.join(ROOT, "backend/.venv/bin/python");
const E2E_DB = "postgresql+psycopg://matchdesk_app@localhost:5432/matchdesk_e2e";

let lastStep = -1;

/** The operator's current one-time code. A code is accepted once, so a second sign-in waits for the
 * next 30-second step. */
async function operatorCode(email: string): Promise<string> {
  while (Math.floor(Date.now() / 30_000) === lastStep) await new Promise((r) => setTimeout(r, 1000));
  lastStep = Math.floor(Date.now() / 30_000);
  return readCode(email);
}

function readCode(email: string): string {
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
  await page.getByLabel("One-time code from your authenticator app").fill(await operatorCode(email));
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Operator console" })).toBeVisible();
}

// B7: the four pieces as docs/PLAY.md section 9 tells the owner to play them.
test("B7 operator console, support access, pilot record, weekly summary and email intake", async ({ page }) => {
  const { tag } = run();
  const controller = `controller.${tag}@example.invalid`;
  const operator = `operator.${tag}@example.invalid`;

  // S-18: the operator sees accounts and the pilot record, never documents; asks for access.
  await signInOperator(page, operator);
  await axe(page, "operator console");
  await page.getByRole("link", { name: new RegExp(tag) }).click();
  await expect(page.getByRole("heading", { name: "Pilot record" })).toBeVisible();
  await expect(page.getByLabel("Refund threshold (CAD)")).toHaveValue("500.00");
  await page.getByLabel("Signed terms reference").fill(`Pilot terms v2 (synthetic) ${tag}`);
  await page.getByRole("button", { name: "Save pilot record" }).click();
  await expect(page.getByText("Pilot record saved.")).toBeVisible();
  await page.getByLabel("Reason the controller will see").fill("Check the October back-test (synthetic)");
  await page.getByRole("button", { name: "Ask for support access" }).click();
  await expect(page.getByText(/waiting for a controller/)).toBeVisible();
  await page.goto("/invoices");
  await expect(page.getByRole("heading", { name: "Operator console" })).toBeVisible(); // no tenant screens
  await signOut(page, "Demo Operator");

  // S-16: the controller grants it; S-03 shows the pilot terms; S-14 by week; email intake.
  await signIn(page, controller);
  await page.goto("/onboarding");
  await expect(page.getByRole("heading", { name: "Pilot terms" })).toBeVisible();
  await expect(page.getByText(`Pilot terms v2 (synthetic) ${tag}`)).toBeVisible();
  await page.goto("/settings/users");
  await page.getByRole("button", { name: "Grant 1 day" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Grant access" }).click();
  await expect(page.getByText(/MatchDesk support can read this account until/)).toBeVisible();
  await page.goto("/reports/weekly?week=2026-10-05");
  await expect(page.getByRole("heading", { name: "Weekly summary" })).toBeVisible();
  await axe(page, "weekly summary");
  await tablesFit(page, "weekly summary at 1440");
  await page.getByRole("button", { name: "Email this week now" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Email now" }).click();
  await expect(page.getByText(/Weekly summary emailed to 1 controller/)).toBeVisible();
  // make demo-email against Playwright's stack: one message accepted, one held.
  const out = execFileSync(PY, [path.join(ROOT, "backend/scripts/demo_email.py")], {
    cwd: path.join(ROOT, "backend"),
    env: { ...process.env, MATCHDESK_DATABASE_URL: E2E_DB, MATCHDESK_API_URL: E2E_API, MATCHDESK_DEMO_TENANT: `Demo Distributor Ltd (synthetic) ${tag}` },
  }).toString();
  expect(out).toContain("processed");
  expect(out).toContain("held");
  await page.goto("/intake");
  await expect(page.getByRole("heading", { name: "Invoices by email" })).toBeVisible();
  await expect(page.getByText("accounts@unknown-supplier.example")).toBeVisible();
  await axe(page, "intake with email");
  await page.getByRole("button", { name: "Release into a batch" }).click();
  await expect(page.getByText("Released: its attachments are in a new batch.")).toBeVisible();
  await expect(page.getByText("Held for you (0)")).toBeVisible();
  await signOut(page, "Demo Controller");

  // The operator opens the account read only: banner on every screen, and the way out.
  await signInOperator(page, operator);
  await page.getByRole("link", { name: new RegExp(tag) }).click();
  await page.getByRole("button", { name: "Open the account, read only" }).click();
  await expect(page.getByText("Support access, read only.")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Exception queue" })).toBeVisible();
  await expect(page.getByRole("button", { name: /Resolve/ })).toHaveCount(0);
  await page.getByRole("button", { name: "Leave the account" }).click();
  await expect(page.getByRole("heading", { name: "Operator console" })).toBeVisible();
});
