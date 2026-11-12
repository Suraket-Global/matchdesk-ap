// B8 financial-trust fixes (web): weekly drill-down scope, the queue's server-side scope and totals,
// queue-to-case navigation from the server's order, empty versus zero, truthful QuickBooks label.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { setLastInput } from "./api/client";
import { SessionProvider } from "./app/session";
import { WeeklyPage } from "./routes/Weekly";
import { ExceptionsPage } from "./routes/Exceptions";
import { MatchViewPage } from "./routes/MatchView";
import { apiQuery, describeScope, queueLink, readScope } from "./lib/queue";

vi.mock("./components/PdfViewer", () => ({ default: () => <div>pdf</div> }));

type Handler = (url: string, init?: RequestInit) => { status?: number; body?: unknown };
let handler: Handler = () => ({ status: 404 });
const calls: string[] = [];
beforeEach(() => {
  calls.length = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push(url);
      const r = handler(url, init);
      return new Response(JSON.stringify(r.body ?? {}), { status: r.status ?? 200, headers: { "Content-Type": "application/json" } });
    }),
  );
  setLastInput(Date.now());
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const me = {
  user: { id: "u1", email: "u@example.invalid", display_name: "Synthetic user", is_operator: false },
  memberships: [{ tenant_id: "t1", role: "clerk", tenant_name: "Fictional Distributor" }],
  active_tenant_id: "t1",
  role: "clerk",
  csrf_token: "x",
};

function Where() {
  const l = useLocation();
  return <output data-testid="where">{l.pathname + l.search}</output>;
}

function wrap(ui: React.ReactNode, path: string, route = "*") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  qc.setQueryData(["me"], me);
  render(
    <QueryClientProvider client={qc}>
      <SessionProvider>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path={route} element={ui} />
            <Route path="/exceptions" element={<><ExceptionsPage /><Where /></>} />
          </Routes>
          <Where />
        </MemoryRouter>
      </SessionProvider>
    </QueryClientProvider>,
  );
}

const exc = (id: string, doc: string, amount: string, extra: object = {}) => ({
  id,
  invoice_id: `inv-${id}`,
  invoice_line_id: `line-${id}`,
  type: "qty_over_received",
  sub_reason: null,
  status: "open",
  value_class: "finding_candidate",
  qualifying: true,
  resolution_code: null,
  resolution_note: null,
  variance_qty: "40",
  variance_amount: amount,
  reported_amount: amount,
  allowed_codes: ["confirmed_overbilling", "waived"],
  version: 1,
  vendor_id: "v1",
  vendor_name: "Fictional Fasteners Ltd",
  doc_number: doc,
  po_number: "4471",
  line_no: 1,
  supplier_item_code: "HB-M8",
  raised_at: new Date().toISOString(),
  ...extra,
});

describe("weekly drill-down (B8)", () => {
  it("links each open count to the queue with the exact week, supplier and status", async () => {
    handler = () => ({
      body: {
        week_start: "2026-10-05",
        week_end: "2026-10-11",
        state: "measured",
        suppliers: [
          { vendor_id: "v1", vendor_name: "Fictional Fasteners Ltd", documents: 1, lines: 1, lines_matched: 0, pass_rate_pct: "0.0", open_count: 1, open_value: "168.00", flagged_amount: "168.00" },
          { vendor_id: null, vendor_name: null, documents: 1, lines: 1, lines_matched: 0, pass_rate_pct: "0.0", open_count: 1, open_value: "0.50", flagged_amount: "0.00" },
        ],
        total: { documents: 2, lines: 2, lines_matched: 0, pass_rate_pct: "0.0", open_count: 2, open_value: "168.50", flagged_amount: "168.00" },
        sent: [],
      },
    });
    wrap(<WeeklyPage />, "/reports/weekly?week=2026-10-07");
    const link = await screen.findByRole("link", { name: /1 open exceptions for Fictional Fasteners Ltd/ });
    const href = new URL(link.getAttribute("href")!, "http://x");
    expect(href.pathname).toBe("/exceptions");
    expect(Object.fromEntries(href.searchParams)).toEqual({ vendor: "v1", from: "2026-10-05", to: "2026-10-11", src: "weekly" });
    // A supplier the reader could not identify is reachable too.
    expect(screen.getByRole("link", { name: /supplier not identified/ }).getAttribute("href")).toContain("vendor=none");
  });

  it("keeps the dates in the queue's request, shows them, and clearing the supplier keeps them", async () => {
    handler = (url) =>
      url.startsWith("/api/v1/exceptions?")
        ? { body: { items: [exc("e1", "FF-1003", "168.00")], counters: { open: 1 }, type_counters: { qty_over_received: 1 }, total_count: 1, total_value: "168.00", next_cursor: null } }
        : url.startsWith("/api/v1/vendors")
          ? { body: { items: [{ id: "v1", name: "Fictional Fasteners Ltd" }] } }
          : { body: { state: "measured", item_lines: 1, receipt_coverage_pct: "100.00", coverage_class_a_pct: "100.00", coverage_class_b_pct: "0.00", items: [], total_count: 0, total_value: "0.00" } };
    wrap(<ExceptionsPage />, queueLink({ vendor: "v1", from: "2026-10-05", to: "2026-10-11", src: "weekly" }), "/exceptions");
    await screen.findAllByText("FF-1003");
    const list = calls.find((u) => u.startsWith("/api/v1/exceptions?") && u.includes("vendor_id=v1"))!;
    const q = new URL(list, "http://x").searchParams;
    expect([q.get("period_start"), q.get("period_end"), q.get("status"), q.get("vendor_id")]).toEqual(["2026-10-05", "2026-10-11", "open,pending_approval", "v1"]);
    const scope = screen.getByRole("group", { name: "Queue scope" });
    expect(within(scope).getByText(/5 to 11 Oct 2026/)).toBeInTheDocument();
    // The footer is the server's count and value of the whole scope, as on the weekly summary.
    expect(screen.getByText("1 exception in this scope")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Remove the supplier filter" }));
    await waitFor(() => expect(screen.getAllByTestId("where")[0].textContent).toBe("/exceptions?from=2026-10-05&to=2026-10-11&src=weekly"));
  });
});

describe("queue scope helpers (B8)", () => {
  it("sends every filter and the sort to the server, never filtering loaded rows", () => {
    const s = readScope(new URLSearchParams("type=price_variance&vendor=v1&min=10&max=200&sort=age"));
    const q = apiQuery(s, "2026-10");
    expect(Object.fromEntries(q)).toEqual({
      status: "open,pending_approval",
      period_start: "2026-10-01",
      period_end: "2026-10-31",
      sort: "age",
      type: "price_variance",
      vendor_id: "v1",
      min_value: "10",
      max_value: "200",
    });
    expect(describeScope(readScope(new URLSearchParams("from=2026-10-05&to=2026-10-11&vendor=v1")), "2026-10", "Fictional Fasteners Ltd")).toBe(
      "Fictional Fasteners Ltd, 5 to 11 Oct 2026",
    );
  });
});

describe("queue to case and back (B8)", () => {
  it("takes previous and next from the server's order for the same scope, and returns to the queue after the last", async () => {
    const from = "/exceptions?from=2026-10-05&to=2026-10-11&sel=e2";
    handler = (url) => {
      if (url.startsWith("/api/v1/invoices/")) {
        return {
          body: {
            id: "inv-e2",
            document_id: "d1",
            doc_type: "invoice",
            doc_number: "FF-1003",
            doc_date: "2026-10-07",
            vendor_id: "v1",
            vendor_name: "Fictional Fasteners Ltd",
            total: "420.00",
            stale: false,
            verification_status: "passed",
            exceptions: [exc("e2", "FF-1003", "168.00", { invoice_id: "inv-e2", invoice_line_id: "l1" })],
            lines: [
              {
                id: "l1",
                line_no: 1,
                status: "exception",
                stale: false,
                line_kind: "item",
                qty: "100",
                uom: "EA",
                receipts: [{ id: "r1", received_date: "2026-09-04", qty: "60", source_file: "receiving-warehouse-log.csv", source_row: 4, receiving_import_id: "imp1", evidence_class: "A", evidence_words: "warehouse record", counts: true, not_counted_reason: null, receiver_ref: null }],
                purchase_order: { id: "po1", po_number: "4471", line_id: "pl1", line_no: 1, uom: "EA", qty_ordered: "100", unit_price: "4.20" },
                match: { line_kind: "item", qty_ordered: "100", qty_received_cum: "60", qty_invoiced_cum_net: "100", qty_invoiced_prior_qbo: null, receipt_line_count: 1, covered: true, po_unit_price: "4.20", invoice_unit_price_po_uom: "4.20", calculation: "Received to date 60 EA." },
              },
            ],
          },
        };
      }
      if (url.includes("/neighbours")) return { body: { previous: { id: "e1", invoice_id: "inv-e1", invoice_line_id: null, doc_number: "SS-5111", type: "qty_over_received" }, next: null, position: 2, total: 2 } };
      return { body: { waiver_limit: "100.00", items: [] } };
    };
    wrap(<MatchViewPage />, `/invoices/inv-e2?line=l1&exc=e2&from=${encodeURIComponent(from)}`, "/invoices/:invoiceId");
    // FF-1003 acceptance: billed, received with its exact row, excess, unit price, exposure.
    const ledger = await screen.findByRole("region", { name: "Calculation in figures" });
    for (const t of ["100 EA", "60 EA", "40 EA", "CAD 4.20", "CAD 168.00"]) expect(within(ledger).getByText(t)).toBeInTheDocument();
    expect(within(ledger).getByRole("link", { name: "receiving-warehouse-log.csv row 4" }).getAttribute("href")).toMatch(/^\/receiving\/imports\/imp1\?row=4&from=/);
    const neighbours = calls.find((u) => u.includes("/neighbours"))!;
    expect(neighbours).toContain("period_start=2026-10-05");
    expect(await screen.findByText("2 of 2")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Next exception/ })).toBeDisabled();
    expect(screen.getByRole("link", { name: /Exception queue/ }).getAttribute("href")).toBe(from);
    await userEvent.click(screen.getByRole("button", { name: /Previous exception/ }));
    await waitFor(() => expect(screen.getAllByTestId("where")[0].textContent).toContain("/invoices/inv-e1?"));
  });
});

describe("empty versus zero (B8)", () => {
  it("does not show a fresh account's week or queue as a clean result", async () => {
    handler = (url) =>
      url.startsWith("/api/v1/weekly-summary")
        ? { body: { week_start: "2026-10-05", week_end: "2026-10-11", state: "awaiting_invoices", suppliers: [], total: { documents: 0, lines: 0, lines_matched: 0, pass_rate_pct: null, open_count: 0, open_value: "0.00", flagged_amount: "0.00" }, sent: [] } }
        : { body: {} };
    wrap(<WeeklyPage />, "/reports/weekly?week=2026-10-05");
    expect(await screen.findByText("Nothing checked for this week")).toBeInTheDocument();
    expect(screen.queryByText("CAD 0.00")).not.toBeInTheDocument();
    cleanup();
    handler = (url) =>
      url.startsWith("/api/v1/coverage")
        ? { body: { state: "awaiting_receiving", item_lines: 3, receipt_coverage_pct: null, coverage_class_a_pct: null, coverage_class_b_pct: null } }
        : url.startsWith("/api/v1/exceptions?")
          ? { body: { items: [], counters: {}, type_counters: {}, total_count: 0, total_value: "0.00", next_cursor: null } }
          : { body: { items: [] } };
    wrap(<ExceptionsPage />, "/exceptions", "/exceptions");
    expect(await screen.findByText("Waiting for receiving evidence")).toBeInTheDocument();
    expect(screen.queryByText(/No open exceptions/)).not.toBeInTheDocument();
    expect(screen.getAllByText("Not measured").length).toBeGreaterThan(0);
  });
});
