import { readFileSync } from "node:fs";
import path from "node:path";
import { expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

const MAILPIT = "http://127.0.0.1:8025/api/v1";

export function run(): { tag: string; files: string } {
  return JSON.parse(readFileSync(path.join(import.meta.dirname, ".run.json"), "utf8"));
}

async function linkFor(email: string, after: number): Promise<string> {
  for (let i = 0; i < 40; i++) {
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

/** S-01 as a person does it: ask for a link, open it from the inbox, press Sign in. */
export async function signIn(page: Page, email: string): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Work email").fill(email);
  const asked = Date.now();
  await page.getByRole("button", { name: "Email me a sign-in link" }).click();
  await expect(page.getByText("If that address has access, a link is on its way.")).toBeVisible();
  await expect(page.getByText("Local development: open Mailpit")).toBeVisible();
  const link = await linkFor(email, asked);
  await page.goto(link);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.locator("header.topbar")).toBeVisible();
}

export async function signOut(page: Page, name: string): Promise<void> {
  await page.getByRole("button", { name }).click();
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("heading", { name: "You are signed out." })).toBeVisible();
}

/** axe-core WCAG 2.x A/AA scan; serious and critical findings fail the test. */
export async function axe(page: Page, label: string): Promise<void> {
  const result = await new AxeBuilder({ page: page as never }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze();
  const bad = result.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(bad.map((v) => `${label}: ${v.id} (${v.nodes.length}) ${v.nodes[0]?.target.join(" ")}`)).toEqual([]);
}
