// B14 (2026-11-17, web): what the independent acceptance test could not reach, as automated checks:
// paging of the exception queue in the screen (S-08) and the 60-minute idle sign-out (S-01).
// Pane drag-resize, voiding an import, aliases and reopening run in the browser
// (web/e2e/uncovered-b14.spec.ts). All data synthetic.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { setLastInput, setLastServerContact } from "./api/client";
import { IdleGuard } from "./app/App";
import { SessionProvider } from "./app/session";
import { ExceptionsPage } from "./routes/Exceptions";

HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
  this.setAttribute("open", "");
};
HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) {
  this.removeAttribute("open");
};

type Handler = (url: string, init?: RequestInit) => { status?: number; body?: unknown } | undefined;
let handler: Handler = () => undefined;
const calls: { url: string; method: string }[] = [];
beforeEach(() => {
  calls.length = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, method: init?.method ?? "GET" });
      const r = handler(url, init) ?? { status: 404, body: { title: "Not found" } };
      return new Response(r.status === 204 ? null : JSON.stringify(r.body ?? {}), { status: r.status ?? 200, headers: { "Content-Type": "application/json" } });
    }),
  );
  setLastInput(Date.now());
  setLastServerContact(Date.now());
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  setLastServerContact(Date.now());
});

const me = {
  user: { id: "u1", email: "u@example.invalid", display_name: "Synthetic user", is_operator: false },
  memberships: [{ tenant_id: "t1", role: "clerk", tenant_name: "Fictional Distributor" }],
  active_tenant_id: "t1",
  role: "clerk",
  csrf_token: "x",
};

function wrap(ui: React.ReactNode, path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  qc.setQueryData(["me"], me);
  render(
    <QueryClientProvider client={qc}>
      <SessionProvider>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path="/signed-out" element={<p>You are signed out.</p>} />
            <Route path="*" element={ui} />
          </Routes>
        </MemoryRouter>
      </SessionProvider>
    </QueryClientProvider>,
  );
}

const row = (n: number, amount: string) => ({
  id: `e${n}`,
  invoice_id: `inv${n}`,
  invoice_line_id: `line${n}`,
  type: "qty_over_received",
  sub_reason: null,
  status: "open",
  value_class: "finding_candidate",
  qualifying: true,
  resolution_code: null,
  resolution_note: null,
  variance_qty: "1",
  variance_amount: amount,
  reported_amount: amount,
  allowed_codes: ["confirmed_overbilling", "waived"],
  version: 1,
  vendor_id: "v1",
  vendor_name: "Fictional Fasteners Ltd",
  doc_number: `FF-${2000 + n}`,
  po_number: "4471",
  line_no: 1,
  supplier_item_code: "HB-M8",
  raised_at: new Date().toISOString(),
});

describe("queue paging in the screen (S-08)", () => {
  it("shows the first page with the scope's total, then the next page from the cursor, same scope and order", async () => {
    const page = (items: object[], next: string | null) => ({ body: { items, counters: { open: 150 }, type_counters: { qty_over_received: 150 }, total_count: 150, total_value: "11325.00", next_cursor: next } });
    const first = Array.from({ length: 100 }, (_, i) => row(i, String(150 - i) + ".00"));
    const second = Array.from({ length: 50 }, (_, i) => row(100 + i, String(50 - i) + ".00"));
    handler = (url) => {
      if (url.startsWith("/api/v1/exceptions?") && url.includes("limit=100")) return url.includes("cursor=c-100") ? page(second, null) : page(first, "c-100");
      if (url.startsWith("/api/v1/exceptions?")) return { body: { items: [], total_count: 0, total_value: "0.00", counters: {}, type_counters: {}, next_cursor: null } };
      if (url.startsWith("/api/v1/coverage")) return { body: { state: "measured", item_lines: 150, receipt_coverage_pct: "100.00", coverage_class_a_pct: "100.00", coverage_class_b_pct: "0.00" } };
      return { body: { items: [] } };
    };
    wrap(<ExceptionsPage />, "/exceptions?vendor=v1");
    await screen.findAllByText("FF-2000");
    expect(screen.getByText("Showing 100 of 150 exceptions in this scope")).toBeTruthy();
    expect(screen.queryByText("FF-2100")).toBeNull();
    // The total is the server's for the whole scope, not the sum of the rows loaded.
    expect(document.querySelector("[data-queue-total]")?.textContent).toBe("11,325.00");
    await userEvent.click(screen.getByRole("button", { name: "Show the next 50" }));
    await screen.findAllByText("FF-2149");
    expect(screen.getByText("150 exceptions in this scope")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Show the next/ })).toBeNull();
    expect(document.querySelector("[data-queue-total]")?.textContent).toBe("11,325.00");
    // No row twice, none skipped.
    const shown = [...document.querySelectorAll("tbody tr")].length;
    expect(shown).toBe(150);
    // The second request carries the cursor and exactly the first request's scope and order.
    const lists = calls.map((c) => c.url).filter((u) => u.startsWith("/api/v1/exceptions?") && u.includes("limit=100"));
    const [a, b] = [new URL(lists[0], "http://x").searchParams, new URL(lists[lists.length - 1], "http://x").searchParams];
    expect(b.get("cursor")).toBe("c-100");
    b.delete("cursor");
    expect(Object.fromEntries(b)).toEqual(Object.fromEntries(a));
    expect(a.get("vendor_id")).toBe("v1");
  });
});

/** Whether the "Stay signed in?" dialog is open (a closed dialog stays in the page, not shown). */
const asking = () => !!document.querySelector("dialog[open]");

describe("idle sign-out (S-01, 60 minutes)", () => {
  it("asks two minutes before the limit and stays signed in when asked to", async () => {
    handler = (url, init) => (url.endsWith("/auth/session/extend") && init?.method === "POST" ? { body: { idle_expires_at: "2026-11-17T12:00:00Z" } } : undefined);
    setLastServerContact(Date.now() - 58.5 * 60_000);
    wrap(<IdleGuard tickMs={10} />, "/exceptions");
    await waitFor(() => expect(asking()).toBe(true));
    expect(screen.getByText(/You will be signed out in 2 minutes because there has been no activity/)).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Stay signed in", hidden: true }));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/auth/session/extend") && c.method === "POST")).toBe(true));
    expect(screen.queryByText("You are signed out.")).toBeNull();
    await waitFor(() => expect(asking()).toBe(false));
  });

  it("does not ask while the server saw the browser recently", async () => {
    setLastServerContact(Date.now() - 30 * 60_000);
    wrap(<IdleGuard tickMs={10} />, "/exceptions");
    await new Promise((r) => setTimeout(r, 60));
    expect(asking()).toBe(false);
  });

  it("signs out after 60 idle minutes: ends the server session and leaves the page", async () => {
    handler = (url, init) => (url.endsWith("/auth/session") && init?.method === "DELETE" ? { status: 204 } : undefined);
    setLastServerContact(Date.now() - 61 * 60_000);
    wrap(<IdleGuard tickMs={10} />, "/exceptions?vendor=v1");
    expect(await screen.findByText("You are signed out.")).toBeTruthy();
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/api/v1/auth/session") && c.method === "DELETE")).toBe(true));
  });
});
