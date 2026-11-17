// B15 (2026-11-17): bugs found while recording the product tour. All data synthetic.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { setLastInput } from "./api/client";
import { SessionProvider } from "./app/session";
import { ReviewPage } from "./routes/Review";
import { TolerancesPage } from "./routes/Settings";
import { PurchaseOrderPage } from "./routes/PurchaseOrder";
import PdfViewer, { imageType } from "./components/PdfViewer";
import { cad, cur, parseNumberInput, setCurrency } from "./lib/decimal";

vi.mock("pdfjs-dist", () => ({
  GlobalWorkerOptions: {},
  getDocument: () => ({ promise: Promise.reject(new Error("not a PDF")) }),
}));
vi.mock("pdfjs-dist/build/pdf.worker.min.mjs?url", () => ({ default: "worker.js" }));

type Reply = { status?: number; body?: unknown; raw?: BodyInit; type?: string };
type Handler = (url: string, init?: RequestInit) => Reply | undefined;
let handler: Handler = () => undefined;
const sent: { url: string; method: string; ifMatch: string | null; body: unknown }[] = [];

beforeEach(() => {
  sent.length = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      const h = new Headers(init?.headers);
      if (method !== "GET") sent.push({ url, method, ifMatch: h.get("If-Match"), body: init?.body ? JSON.parse(String(init.body)) : null });
      const r = handler(url, init) ?? { status: 404, body: { title: "Not found" } };
      if (r.raw !== undefined) return new Response(r.raw, { status: r.status ?? 200, headers: { "Content-Type": r.type ?? "application/octet-stream" } });
      return new Response(JSON.stringify(r.body ?? {}), { status: r.status ?? 200, headers: { "Content-Type": "application/json" } });
    }),
  );
  setLastInput(Date.now());
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  setCurrency("CAD");
});

const meFor = (role: string, currency = "CAD") => ({
  user: { id: "u1", email: "u@example.invalid", display_name: "Synthetic user", is_operator: false },
  memberships: [{ tenant_id: "t1", role, tenant_name: "Fictional Distributor" }],
  active_tenant_id: "t1",
  role,
  currency,
  csrf_token: "x",
});

function wrap(ui: React.ReactNode, path = "/", route = "*", role = "controller", currency = "CAD") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  qc.setQueryData(["me"], meFor(role, currency));
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
}

const review = (version: number, draft: unknown = null) => ({
  document_id: "doc1",
  document_state: "needs_review",
  verification_status: "failed",
  verification: {},
  fields: { doc_type: "invoice", vendor_id: "v1", doc_number: "FF-B15", doc_date: "2026-10-06", total: "1000.00", tax_total: "0.00", currency: "CAD" },
  vendor_name_read: "Fictional Fasteners Ltd",
  purchase_order_id: null,
  field_sources: {},
  review_draft: draft,
  confirmed_by: null,
  confirmed_at: null,
  line_fields: [{ line_no: 1, id: "l1", supplier_item_code: "W-1", description: "Widget", qty: "100", uom: "EA", unit_price: "10", amount: "1000.00", line_kind: "item", page_no: null, field_sources: {} }],
  removed_lines: [],
  next_line_no: 2,
  version,
});

const invoice = (version: number) => ({
  id: "inv1",
  document_id: "doc1",
  vendor_id: "v1",
  vendor_name: "Fictional Fasteners Ltd",
  total: "1000.00",
  verification_status: "failed",
  qbo_bill: null,
  stale: false,
  doc_type: "invoice",
  doc_number: "FF-B15",
  doc_date: "2026-10-06",
  version: 4,
  lines: [],
  exceptions: [],
  review: review(version),
});

describe("bug 1: autosave keeps what was typed and Confirm works after it", () => {
  it("does not put the old value back after the 30-second draft save, and confirms with the new version", async () => {
    let server = 7; // the review version the server holds
    handler = (url, init) => {
      const m = init?.method ?? "GET";
      const ifMatch = Number(new Headers(init?.headers).get("If-Match"));
      if (url.includes("/extraction") && m === "PATCH") {
        if (ifMatch !== server) return { status: 409, body: { title: "changed by someone else", current: review(server) } };
        server += 1;
        const b = JSON.parse(String(init!.body)) as { draft: boolean; fields: unknown; lines: unknown };
        return { body: { ...review(server, b.draft ? { fields: b.fields, lines: b.lines, saved_at: "2026-11-17T10:00:00Z" } : null) } };
      }
      if (url.includes("/confirm-extraction")) {
        if (ifMatch !== server) return { status: 409, body: { title: "changed by someone else", current: review(server) } };
        return { body: { id: "inv1", verification_status: "human_confirmed", version: server + 1 } };
      }
      if (url.includes("/api/v1/invoices/inv1")) return { body: invoice(server) };
      if (url.includes("/vendors")) return { body: { items: [{ id: "v1", name: "Fictional Fasteners Ltd" }] } };
      return { body: { items: [] } };
    };
    const ticks: (() => void)[] = [];
    const real = window.setInterval.bind(window);
    vi.spyOn(window, "setInterval").mockImplementation(((fn: () => void, ms?: number) => {
      if (ms === 30_000) ticks.push(fn);
      return real(() => undefined, 1_000_000);
    }) as typeof window.setInterval);
    wrap(<ReviewPage />, "/invoices/inv1/review", "/invoices/:invoiceId/review", "clerk");
    const desc = await screen.findByLabelText("Line 1 Description");
    fireEvent.change(desc, { target: { value: "Widget, blue" } });
    await act(async () => {
      ticks.at(-1)!();
    });
    await waitFor(() => expect(sent.filter((x) => x.method === "PATCH").length).toBe(1));
    expect(sent[0]).toMatchObject({ ifMatch: "7", body: { draft: true } });
    await waitFor(() => expect(screen.getByText(/Draft saved at/)).toBeInTheDocument());
    // The typed value stays on screen after the save.
    expect(screen.getByLabelText("Line 1 Description")).toHaveValue("Widget, blue");
    fireEvent.click(screen.getByRole("button", { name: "Confirm and match" }));
    await waitFor(() => expect(sent.some((x) => x.url.includes("/confirm-extraction"))).toBe(true));
    const final = sent.filter((x) => x.method === "PATCH")[1];
    expect(final).toMatchObject({ ifMatch: "8", body: { draft: false } });
    expect((final.body as { lines: { description: string }[] }).lines[0].description).toBe("Widget, blue");
    expect(sent.find((x) => x.url.includes("/confirm-extraction"))!.ifMatch).toBe("9");
    expect(screen.queryByText(/changed by someone else/)).toBeNull();
  });
});

describe("bug 2: the tolerances form accepts the value it stored", () => {
  it("counts significant decimals, not trailing zeros, and keeps the real limit", () => {
    const rules = { places: 4, whole: 10 };
    expect(parseNumberInput("0.010000", rules)).toEqual({ ok: true, value: "0.0100" });
    expect(parseNumberInput("0.00001", rules)).toMatchObject({ ok: false, error: "At most 4 decimal places." });
    expect(parseNumberInput("0.123450", rules)).toMatchObject({ ok: false });
    expect(parseNumberInput("12.50", { places: 2, whole: 12 })).toEqual({ ok: true, value: "12.50" });
  });

  it("shows stored NUMERIC values without trailing zeros and no error", async () => {
    const tol = { id: "t1", vendor_id: null, qty_tolerance: "0.0000", price_tol_abs: "0.010000", price_tol_pct: "2.5000", charge_allowance: "5.00", valid_from: "2026-10-01T00:00:00Z", valid_to: null };
    handler = (url) => {
      if (url.includes("/tolerances/preview")) return { body: { lines_rematched: 0, exceptions_cleared: 0 } };
      if (url.includes("/api/v1/tolerances")) return { body: { default: tol, vendors: [], history: [], waiver_limit: "50.00", waiver_period_cap: "500.00", receipt_note: "A missing receiving record stays an exception." } };
      return { body: { items: [] } };
    };
    wrap(<TolerancesPage />, "/settings/tolerances", "/settings/tolerances", "controller");
    expect(await screen.findByLabelText("Price tolerance (amount)")).toHaveValue("0.01");
    expect(screen.getByLabelText("Price tolerance (percent)")).toHaveValue("2.5");
    expect(screen.queryByText(/At most 4 decimal places/)).toBeNull();
    expect(screen.getByTestId("tolerance-example")).not.toHaveTextContent("Not valid yet");
    // A stored value typed back with its zeros is accepted too.
    fireEvent.change(screen.getByLabelText("Price tolerance (amount)"), { target: { value: "0.010000" } });
    expect(screen.queryByText(/At most 4 decimal places/)).toBeNull();
  });
});

describe("bug 3: a PNG or JPEG document is shown in extraction review", () => {
  const png = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0, 0, 0, 13]);
  const jpeg = new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 0, 16]);

  it("tells images from PDFs by their first bytes", () => {
    expect(imageType(png.buffer)).toBe("image/png");
    expect(imageType(jpeg.buffer)).toBe("image/jpeg");
    expect(imageType(new TextEncoder().encode("%PDF-1.4").buffer)).toBeNull();
  });

  it("draws the image from the authenticated bytes with zoom and fit", async () => {
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:doc1"), revokeObjectURL: vi.fn() }));
    handler = (url) => (url.includes("/documents/doc1/content") ? { raw: png, type: "image/png" } : undefined);
    wrap(<PdfViewer documentId="doc1" label="Document FF-B15" />);
    await waitFor(() => expect(document.querySelector("img")).not.toBeNull());
    const img = document.querySelector("img")!;
    expect(img).toHaveAttribute("src", "blob:doc1");
    expect(img.getAttribute("alt")).toContain("Document FF-B15");
    expect(document.querySelector("canvas")).toBeNull();
    // The image's own width sets the zoom (the walk found the load handler reading a stale event).
    Object.defineProperty(img, "naturalWidth", { value: 1700, configurable: true });
    fireEvent.load(img);
    await waitFor(() => expect(img.style.width).toBe("1700px"));
    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(img.style.width).toBe("2125px");
    expect(screen.getByRole("button", { name: "Fit width" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.queryByText(/could not be shown/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Fit width" }));
    expect(screen.getByRole("button", { name: "Fit width" })).toHaveAttribute("aria-pressed", "true");
  });
});

describe("bug 5: money carries the account's currency", () => {
  it("labels with the account currency; the pilot terms stay CAD", () => {
    setCurrency("USD");
    expect(cur("205")).toBe("USD 205.00");
    expect(cad("500.00")).toBe("CAD 500.00");
  });

  it("the PO page of a USD account says USD, not CAD", async () => {
    handler = (url) =>
      url.includes("/purchase-orders/po1")
        ? { body: { id: "po1", po_number: "1001", vendor_id: "v1", vendor_name: "Fictional Fasteners Ltd", txn_date: "2026-09-01", qbo_status: "Open", total: "205.00", lines: [], changed_in_quickbooks: null } }
        : { body: { items: [] } };
    wrap(<PurchaseOrderPage />, "/purchase-orders/po1", "/purchase-orders/:poId", "controller", "USD");
    expect(await screen.findByText(/total in QuickBooks USD 205\.00/)).toBeInTheDocument();
    expect(screen.queryByText(/CAD 205/)).toBeNull();
  });
});
