// Regression tests for the B3/B4 review of 2026-11-12 (web). Each failed before its fix.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { errorText, ApiError, get, lastServerContact, setLastInput } from "./api/client";
import { SessionProvider } from "./app/session";
import { safePath } from "./lib/format";
import { price } from "./lib/decimal";
import { zeroCounted } from "./lib/words";
import { ApprovalsPage } from "./routes/Approvals";
import { BulkDialog, ExceptionsPage } from "./routes/Exceptions";
import { ReportsPage } from "./routes/Reports";
import { ReviewPage } from "./routes/Review";
import type { ExceptionItem } from "./api/types";

vi.mock("./components/PdfViewer", () => ({ default: () => <div>pdf</div> }));
// jsdom has no modal dialogs.
HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
  this.setAttribute("open", "");
};
HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) {
  this.removeAttribute("open");
};

type Handler = (url: string, init?: RequestInit) => { status?: number; body?: unknown } | Promise<{ status?: number; body?: unknown }>;
let handler: Handler = () => ({ status: 404, body: {} });
const calls: { url: string; init?: RequestInit }[] = [];

beforeEach(() => {
  calls.length = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, init });
      const r = await handler(url, init);
      return new Response(JSON.stringify(r.body ?? {}), { status: r.status ?? 200, headers: { "Content-Type": "application/json" } });
    }),
  );
  setLastInput(Date.now());
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const ME = {
  user: { id: "u1", email: "clerk@example.invalid", display_name: "Synthetic clerk", is_operator: false },
  memberships: [{ tenant_id: "t1", role: "controller", tenant_name: "Fictional Distributor" }],
  active_tenant_id: "t1",
  role: "controller",
  csrf_token: "x",
};

function wrap(ui: React.ReactNode, path = "/", route = "*") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  qc.setQueryData(["me"], ME);
  render(
    <QueryClientProvider client={qc}>
      <SessionProvider>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path={route} element={ui} />
          </Routes>
        </MemoryRouter>
      </SessionProvider>
    </QueryClientProvider>,
  );
  return qc;
}

const exc = (over: Partial<ExceptionItem>): ExceptionItem => ({
  id: "e1",
  invoice_id: "i1",
  invoice_line_id: "l1",
  type: "price_variance",
  sub_reason: null,
  status: "open",
  value_class: "finding_candidate",
  qualifying: true,
  resolution_code: null,
  resolution_note: null,
  resolved_by: null,
  variance_qty: null,
  variance_amount: "9.00",
  reported_amount: "9.00",
  possibly_credited: false,
  label: null,
  allowed_codes: ["source_corrected", "waived"],
  stale: false,
  version: 1,
  doc_number: "SS-5110",
  ...over,
});

describe("W1: ?from= and ?next= stay inside the app", () => {
  it("refuses javascript:, full URLs and protocol-relative paths", () => {
    for (const bad of ["javascript:alert(1)", "https://evil.example/x", "//evil.example", "/\\evil.example", "exceptions"])
      expect(safePath(bad, "/exceptions")).toBe("/exceptions");
    expect(safePath("/exceptions?type=no_po&sel=1", "/")).toBe("/exceptions?type=no_po&sel=1");
  });
});

describe("W7 and minor: amounts in words", () => {
  it("an exception counted under another one on the line is recognised, not shown as a value", () => {
    expect(zeroCounted({ reported_amount: "0.00", variance_amount: "740.00" })).toBe(true);
    expect(zeroCounted({ reported_amount: "740.00", variance_amount: "740.00" })).toBe(false);
    expect(zeroCounted({ reported_amount: "0.00", variance_amount: "0.00" })).toBe(false);
  });
  it("prices keep their cents (4.20, not 4.2)", () => {
    expect(price("4.200000")).toBe("4.20");
    expect(price("0.075000")).toBe("0.075");
    expect(price("18")).toBe("18.00");
  });
});

describe("W8: session", () => {
  it("a polling request after a minute without input is background and is not activity", async () => {
    handler = () => ({ body: { items: [] } });
    const before = lastServerContact();
    setLastInput(Date.now() - 120_000);
    await new Promise((r) => setTimeout(r, 5));
    await get("/api/v1/exceptions");
    const headers = calls[0].init?.headers as Record<string, string>;
    expect(headers["X-Background-Request"]).toBe("1");
    expect(lastServerContact()).toBe(before);
    setLastInput(Date.now());
    await get("/api/v1/exceptions");
    expect((calls[1].init?.headers as Record<string, string>)["X-Background-Request"]).toBeUndefined();
    expect(lastServerContact()).toBeGreaterThan(before);
  });
  it("an expired session forgets the user and every cached read", async () => {
    handler = () => ({ status: 401, body: { title: "Not signed in" } });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    qc.setQueryData(["me"], ME);
    qc.setQueryData(["exceptions", "queue"], { items: [exc({})] });
    render(
      <QueryClientProvider client={qc}>
        <SessionProvider>
          <span>app</span>
        </SessionProvider>
      </QueryClientProvider>,
    );
    await expect(get("/api/v1/exceptions")).rejects.toBeInstanceOf(ApiError);
    await waitFor(() => expect(qc.getQueryData(["me"])).toBeNull());
    expect(qc.getQueryData(["exceptions", "queue"])).toBeUndefined();
  });
  it("an anti-forgery refusal is not described as a role refusal", () => {
    expect(errorText(new ApiError(403, "Anti-forgery token missing or wrong"))).toMatch(/Reload the page/);
    expect(errorText(new ApiError(403, "Forbidden"))).toMatch(/role/);
  });
});

describe("W6: bulk result keeps the names", () => {
  it("names each item after the queue reloaded without them", async () => {
    handler = (url) => (url.includes("bulk-resolutions") ? { body: { results: [{ id: "e1", result: "resolved" }] } } : { body: { waiver_limit: "100.00", waiver_period_cap: "500.00" } });
    function Host() {
      const [items, setItems] = useState([exc({})]);
      return (
        <>
          <button onClick={() => setItems([])}>reload queue</button>
          <BulkDialog items={items} onClose={() => undefined} />
        </>
      );
    }
    wrap(<Host />);
    await userEvent.click(screen.getByRole("button", { name: /Resolve 1 item$/ }));
    await screen.findByText(/1 resolved/);
    await userEvent.click(screen.getByText("reload queue"));
    expect(screen.getByText(/SS-5110/)).toBeInTheDocument();
  });
});

describe("W5: Mark reviewed empties the new-alias list", () => {
  it("re-reads the aliases after the acknowledgement", async () => {
    let reviewed = false;
    handler = (url, init) => {
      if (url.includes("review-acknowledgement")) {
        reviewed = true;
        return { body: { acknowledged: 1 } };
      }
      if (url.includes("/api/v1/aliases"))
        return {
          body: {
            items: [{ id: "a1", vendor_id: "v1", vendor_name: "Synthetic Supply Co", supplier_item_code: "TIE-200", item_sku: "TIE200", conversion_factor: "1.000000", approved_by: null, reviewed_at: reviewed ? "2026-11-12T10:00:00Z" : null, status: "active", created_by_name: "Synthetic clerk" }],
          },
        };
      void init;
      return { body: { items: [] } };
    };
    wrap(<ApprovalsPage />);
    expect(await screen.findByText(/TIE-200/)).toBeInTheDocument();
    expect(screen.getByText(/New aliases are waiting for your review/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Mark reviewed" }));
    await waitFor(() => expect(screen.queryByText(/TIE-200/)).not.toBeInTheDocument());
  });
});

describe("W2: one figure, one label", () => {
  it("the report list shows flagged discrepancies as the report page does (findings plus not received)", async () => {
    handler = () => ({
      body: {
        items: [
          { id: "r1", period_start: "2026-10-01", period_end: "2026-10-31", version_no: 1, status: "draft", data_cutoff_at: "2026-11-12T10:00:00Z", findings_amount: "927.30", not_received_amount: "110.00", unverified_amount: "5.00", is_stale: false },
        ],
      },
    });
    wrap(<ReportsPage />);
    expect(await screen.findByText("1,037.30")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /Flagged discrepancies/ })).toBeInTheDocument();
  });
});

describe("W3: coverage strip without a report", () => {
  it("shows live coverage when no report draft exists", async () => {
    handler = (url) => {
      if (url.includes("/api/v1/coverage")) return { body: { period_start: "2026-10-01", period_end: "2026-10-31", item_lines: 12, receipt_coverage_pct: "83.33", coverage_class_a_pct: "91.67", coverage_class_b_pct: "8.33" } };
      if (url.includes("/api/v1/reports")) return { body: { items: [] } };
      return { body: { items: [], type_counters: {} } };
    };
    wrap(<ExceptionsPage />);
    expect(await screen.findByText("83.33%")).toBeInTheDocument();
    expect(screen.getByText(/warehouse log 75%, signed delivery documents 8.33%/)).toBeInTheDocument();
  });
});

describe("W4 and W8: extraction review", () => {
  const review = {
    id: "i1",
    document_id: "d1",
    doc_number: "FF-1006",
    doc_type: "invoice",
    review: {
      document_id: "d1",
      document_state: "needs_review",
      verification_status: "failed",
      verification: {},
      fields: { doc_type: "invoice", vendor_id: "", doc_number: "FF-1006", doc_date: "2026-10-22", po_number_read: "4540", references_invoice_number: null, currency: "CAD", subtotal: "0.80", tax_total: "0", total: "0.80" },
      vendor_name_read: null,
      purchase_order_id: null,
      field_sources: {},
      review_draft: null,
      confirmed_by: null,
      confirmed_at: null,
      line_fields: [{ line_no: 1, id: "l1", supplier_item_code: "WS-M8", description: "Washer M8", qty: "10.0000", uom: "EA", unit_price: "0.080000", amount: "0.80", line_kind: "item", page_no: 1, field_sources: {} }],
      version: 3,
    },
    lines: [],
    exceptions: [],
  };
  let release: () => void = () => undefined;
  beforeEach(() => {
    handler = (url, init) => {
      if (url.includes("/extraction") && init?.method === "PATCH")
        return new Promise((resolve) => {
          release = () => resolve({ body: { ...review.review, version: 4 } });
        });
      if (url.includes("/api/v1/invoices/i1")) return { body: review };
      return { body: { items: [] } };
    };
  });
  it("tags a changed field edited at once, and keeps typing during a draft save unsaved", async () => {
    wrap(<ReviewPage />, "/invoices/i1/review", "/invoices/:invoiceId/review");
    const num = await screen.findByLabelText("Document number");
    expect(screen.queryByText("edited")).not.toBeInTheDocument();
    await userEvent.type(num, "A");
    expect(screen.getByText("edited")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Save draft" }));
    await userEvent.type(num, "B"); // typed while the save is on its way
    await act(async () => release());
    await waitFor(() => expect(screen.getByText(/Draft saved at/)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Save draft" })).toBeEnabled();
  });
  it("does not offer 'the document does not add up' when only the supplier is missing", async () => {
    wrap(<ReviewPage />, "/invoices/i1/review", "/invoices/:invoiceId/review");
    await screen.findByText(/Supplier not identified/);
    expect(screen.queryByText(/does not add up/)).not.toBeInTheDocument();
  });
});
