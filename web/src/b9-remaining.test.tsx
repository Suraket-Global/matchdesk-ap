// B9 (web): the declaration on S-03, removing a line and the inconsistent note on S-07, the saved
// mapping on S-05, the assignee in the queue scope, credit and duplicate decisions on S-09, the
// S-10 banner, finding outcomes on S-13, archive and deletion on S-16, and the queue link that
// survives a reload (sessionStorage, scope keys only). All data synthetic.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { setLastInput } from "./api/client";
import { SessionProvider } from "./app/session";
import { OnboardingPage } from "./routes/Onboarding";
import { ReviewPage } from "./routes/Review";
import { ControllerDecision, Assignee } from "./routes/MatchDecisions";
import { PurchaseOrderPage } from "./routes/PurchaseOrder";
import { OutcomesSection } from "./routes/ReportOutcomes";
import { AccountDataPanel } from "./routes/AccountData";
import { apiQuery, cleanQueueUrl, lastQueueUrl, readScope, rememberQueue } from "./lib/queue";
import type { ExceptionItem, Report } from "./api/types";

vi.mock("./components/PdfViewer", () => ({ default: () => <div>pdf</div> }));

HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
  this.setAttribute("open", "");
};
HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) {
  this.removeAttribute("open");
};

type Handler = (url: string, init?: RequestInit) => { status?: number; body?: unknown } | undefined;
let handler: Handler = () => undefined;
const sent: { url: string; method: string; body: unknown; ifMatch: string | null }[] = [];
beforeEach(() => {
  sent.length = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      if (method !== "GET") {
        const h = new Headers(init?.headers);
        sent.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : null, ifMatch: h.get("If-Match") });
      }
      const r = handler(url, init) ?? { status: 404, body: { title: "Not found" } };
      return new Response(JSON.stringify(r.body ?? {}), { status: r.status ?? 200, headers: { "Content-Type": "application/json" } });
    }),
  );
  setLastInput(Date.now());
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.sessionStorage.clear();
});

const meFor = (role: string) => ({
  user: { id: "u1", email: "u@example.invalid", display_name: "Synthetic user", is_operator: false },
  memberships: [{ tenant_id: "t1", role, tenant_name: "Fictional Distributor" }],
  active_tenant_id: "t1",
  role,
  csrf_token: "x",
});

function wrap(ui: React.ReactNode, path = "/", route = "*", role = "controller") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  qc.setQueryData(["me"], meFor(role));
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

describe("S-03 no receiving records (B9)", () => {
  it("records the statement from step 3 and shows who declared it", async () => {
    let declared = false;
    handler = (url, init) => {
      if (url.includes("/no-receiving-declaration") && init?.method === "POST") {
        declared = true;
        return { status: 201, body: {} };
      }
      if (url.includes("/no-receiving-declaration"))
        return {
          body: {
            statement: "We have no warehouse receiving records for the purchase orders in this back-test.",
            declaration: declared ? { id: "d1", statement: "x", declared_by: "u1", declared_by_name: "Dana Controller", declared_at: "2026-11-13T10:00:00Z" } : null,
          },
        };
      if (url.includes("/qbo/connection")) return { body: { status: "connected", company_name: "Demo" } };
      if (url.includes("/pilot")) return { body: { pilot: null, governing: null } };
      return { body: { items: [] } };
    };
    wrap(<OnboardingPage />, "/onboarding");
    await userEvent.click(await screen.findByRole("button", { name: "We have no warehouse receiving records" }));
    expect(screen.getByText("Every invoiced line carries a \"receipt absent\" exception. None is shown as matched.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Record this statement" }));
    expect(sent.some((s) => s.url.endsWith("/onboarding/no-receiving-declaration") && s.method === "POST")).toBe(true);
    expect(await screen.findByTestId("no-receiving-declared")).toHaveTextContent("recorded by Dana Controller");
    expect(screen.getByText(/receipt coverage is 0%/)).toBeInTheDocument();
  });
});

const review = (extra: object = {}) => ({
  id: "inv1",
  document_id: "doc1",
  vendor_id: "v1",
  vendor_name: "Fictional Fasteners Ltd",
  purchase_order_id: null,
  po_number: "4471",
  total: "50.00",
  verification_status: "failed",
  qbo_bill: null,
  stale: false,
  doc_type: "invoice",
  doc_number: "FF-B9",
  doc_date: "2026-10-06",
  version: 4,
  lines: [],
  exceptions: [],
  review: {
    document_id: "doc1",
    document_state: "needs_review",
    verification_status: "failed",
    verification: {},
    fields: { doc_type: "invoice", vendor_id: "v1", doc_number: "FF-B9", doc_date: "2026-10-06", total: "50.00", tax_total: "0.00", currency: "CAD" },
    vendor_name_read: "Fictional Fasteners Ltd",
    purchase_order_id: null,
    field_sources: {},
    review_draft: null,
    confirmed_by: null,
    confirmed_at: null,
    line_fields: [
      { line_no: 1, id: "l1", supplier_item_code: "W-1", description: "Widget", qty: "10", uom: "EA", unit_price: "4.20", amount: "42.00", line_kind: "item", page_no: null, field_sources: {} },
      { line_no: 2, id: "l2", supplier_item_code: "W-1", description: "Widget again", qty: "1", uom: "EA", unit_price: "4.20", amount: "4.20", line_kind: "item", page_no: null, field_sources: {} },
    ],
    removed_lines: [],
    next_line_no: 3,
    version: 7,
    ...extra,
  },
});

describe("S-07 remove a line and the inconsistent note (B9)", () => {
  it("removes a stored line with a reason and the record version", async () => {
    handler = (url) => {
      if (url.includes("/removal")) return { body: { ...review().review, version: 8, line_fields: [review().review.line_fields[0]], gates: { lines_add_up: true } } };
      if (url.includes("/api/v1/invoices/inv1")) return { body: review() };
      return { body: { items: [] } };
    };
    wrap(<ReviewPage />, "/invoices/inv1/review", "/invoices/:invoiceId/review", "clerk");
    await userEvent.click(await screen.findByRole("button", { name: "Remove line 2" }));
    await userEvent.type(screen.getByLabelText("Reason"), "Printed twice");
    const dialogButtons = screen.getAllByRole("button", { name: "Remove line 2" });
    await userEvent.click(dialogButtons[dialogButtons.length - 1]);
    await waitFor(() => expect(sent.some((s) => s.url.endsWith("/lines/l2/removal"))).toBe(true));
    const call = sent.find((s) => s.url.endsWith("/lines/l2/removal"))!;
    expect(call.ifMatch).toBe("7");
    expect(call.body).toEqual({ reason: "Printed twice" });
  });

  it("asks for a note before confirming a document that does not add up", async () => {
    handler = (url) => {
      if (url.includes("/confirm-extraction")) return { body: { id: "inv1", verification_status: "human_confirmed_inconsistent", version: 8 } };
      if (url.includes("/api/v1/invoices/inv1")) return { body: review({ line_fields: [review().review.line_fields[0]] }) };
      return { body: { items: [] } };
    };
    wrap(<ReviewPage />, "/invoices/inv1/review", "/invoices/:invoiceId/review", "clerk");
    await userEvent.click(await screen.findByRole("checkbox", { name: /does not add up/ }));
    await userEvent.click(screen.getByRole("button", { name: "Confirm and match" }));
    expect(await screen.findByText("Say in the note why the document itself does not add up.")).toBeInTheDocument();
    expect(sent.some((s) => s.url.includes("/confirm-extraction"))).toBe(false);
    await userEvent.type(screen.getByLabelText(/Note \(required\)/), "Eco fee left out of the total (synthetic)");
    await userEvent.click(screen.getByRole("button", { name: "Confirm and match" }));
    await waitFor(() => expect(sent.some((s) => s.url.includes("/confirm-extraction"))).toBe(true));
    expect(sent.find((s) => s.url.includes("/confirm-extraction"))!.body).toEqual({ accept_inconsistent: true, note: "Eco fee left out of the total (synthetic)" });
  });

  it("offers no removal on a confirmed document and shows its note", async () => {
    handler = (url) =>
      url.includes("/api/v1/invoices/inv1")
        ? { body: review({ verification_status: "human_confirmed_inconsistent", inconsistent_note: "Surcharge on the total only" }) }
        : { body: { items: [] } };
    wrap(<ReviewPage />, "/invoices/inv1/review", "/invoices/:invoiceId/review", "clerk");
    expect(await screen.findByText("Surcharge on the total only")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Remove line/ })).toBeNull();
  });
});

const exc = (extra: Partial<ExceptionItem> = {}): ExceptionItem => ({
  id: "e1",
  invoice_id: "inv1",
  invoice_line_id: "l1",
  type: "price_variance",
  sub_reason: null,
  status: "open",
  value_class: "open_undecided",
  qualifying: false,
  resolution_code: null,
  resolution_note: null,
  resolved_by: null,
  variance_qty: null,
  variance_amount: "15.00",
  reported_amount: "15.00",
  possibly_credited: true,
  label: null,
  allowed_codes: ["confirmed_overbilling"],
  stale: false,
  version: 3,
  ...extra,
});

describe("S-09 controller decisions and the assignee (B9)", () => {
  it("sends a credit decision with If-Match and says what each choice does", async () => {
    handler = (url) => (url.includes("/credit-decision") ? { body: exc() } : { body: {} });
    wrap(<ControllerDecision exc={exc()} detail={{ ...exc(), credit_bill: { doc_number: "VC-9", txn_date: "2026-10-20", total: "15.00" } }} onDone={() => undefined} />);
    expect(screen.getByTestId("decision-facts")).toHaveTextContent("VC-9, CAD 15.00"); // B10: grouped facts
    expect(screen.getByText(/listed as undecided, not as a finding/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("radio", { name: /Not credited/ }));
    await userEvent.click(screen.getByRole("button", { name: "Confirm: Not credited" }));
    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]).toMatchObject({ url: "/api/v1/exceptions/e1/credit-decision", ifMatch: "3", body: { decision: "not_credited", note: null } });
  });

  it("lets only the controller decide a possible duplicate", async () => {
    handler = () => ({ body: exc({ type: "possible_duplicate", possibly_credited: false }) });
    wrap(<ControllerDecision exc={exc({ type: "possible_duplicate", possibly_credited: false })} onDone={() => undefined} />, "/", "*", "clerk");
    expect(screen.getByText("Waiting for the controller's decision.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Is a duplicate" })).toBeNull();
  });

  it("assigns the exception to a member", async () => {
    handler = (url) => {
      if (url.includes("/members")) return { body: { items: [{ user_id: "u1", name: "Synthetic user", role: "clerk" }, { user_id: "u2", name: "Dana Controller", role: "controller" }], me: "u1" } };
      if (url.includes("/assignment")) return { body: { ...exc(), assigned_to: "u2", assigned_to_name: "Dana Controller" } };
      return { body: {} };
    };
    wrap(<Assignee exc={exc()} detail={exc()} />, "/", "*", "clerk");
    await screen.findByRole("option", { name: "Dana Controller" });
    await userEvent.selectOptions(screen.getByLabelText("Assigned to"), "u2");
    await waitFor(() => expect(sent[0]).toMatchObject({ url: "/api/v1/exceptions/e1/assignment", method: "PUT", ifMatch: "3", body: { user_id: "u2" } }));
  });
});

describe("S-08 assignee scope and the queue link after a reload (B9)", () => {
  it("carries the assignee into the API query", () => {
    const s = readScope(new URLSearchParams("assignee=me&status=open"));
    expect(apiQuery(s, "2026-10").get("assignee")).toBe("me");
  });

  it("keeps only the scope keys and survives a reload through sessionStorage", () => {
    rememberQueue("/exceptions?assignee=me&vendor=v1&sel=e9&note=private%20words");
    expect(window.sessionStorage.getItem("md.lastQueue")).toBe("/exceptions?vendor=v1&assignee=me");
    expect(lastQueueUrl()).toBe("/exceptions?vendor=v1&assignee=me");
    expect(cleanQueueUrl("/invoices/inv1")).toBeNull();
    expect(cleanQueueUrl("/exceptions?type=<script>")).toBe("/exceptions");
  });

  it("falls back to memory when storage is refused", () => {
    const spy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const get = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    rememberQueue("/exceptions?type=price_variance");
    expect(lastQueueUrl()).toBe("/exceptions?type=price_variance");
    spy.mockRestore();
    get.mockRestore();
  });
});

describe("S-10 changed in QuickBooks (B9)", () => {
  it("shows the old and new values and that the lines are being matched again", async () => {
    handler = (url) =>
      url.includes("/purchase-orders/po1")
        ? {
            body: {
              id: "po1",
              po_number: "4471",
              vendor_id: "v1",
              vendor_name: "Fictional Fasteners Ltd",
              txn_date: "2026-09-01",
              qbo_status: "Open",
              total: "336.00",
              lines: [],
              changed_in_quickbooks: {
                detected_at: "2026-11-13T10:00:00Z",
                rematched_at: null,
                changes: [
                  { po_line_id: "pl1", line_no: 1, change: "changed", before: { qty_ordered: "100", unit_price: "4.2", uom: "EA" }, after: { qty_ordered: "80", unit_price: "4.2", uom: "EA" } },
                  { po_line_id: "pl2", line_no: 2, change: "removed", before: { qty_ordered: "500", unit_price: "0.08", uom: "EA" }, after: null },
                ],
              },
            },
          }
        : { body: { items: [] } };
    wrap(<PurchaseOrderPage />, "/purchase-orders/po1", "/purchase-orders/:poId");
    const banner = await screen.findByTestId("changed-in-quickbooks");
    expect(banner).toHaveTextContent("Ordered 100 → 80");
    expect(banner).toHaveTextContent("Line 2: deleted in QuickBooks");
    expect(banner).toHaveTextContent("being matched again");
  });
});

describe("S-13 finding outcomes (B9)", () => {
  it("keeps flagged, confirmed and recovered apart and records a confirmation", async () => {
    const report = { id: "r1", status: "approved" } as unknown as Report;
    const finding = { id: "f1", exception_id: "e1", section: "finding", type: "price_variance", amount: "15.00", qualifying: true, paid_status: "unpaid", snapshot: { doc_number: "INV-1", line_no: 1 } };
    handler = (url) => {
      if (url.endsWith("/outcomes") && url.includes("/reports/backtest/r1"))
        return {
          body: {
            is_governing: true,
            totals: { flagged: { count: 1, amount: "15.00" }, controller_confirmed: { count: 0, amount: "0.00" }, credit_recovered: { count: 0, amount: "0.00" } },
            by_finding: {},
          },
        };
      if (url.includes("/reports/findings/f1/outcomes")) return { status: 201, body: {} };
      return { body: { items: [] } };
    };
    wrap(<OutcomesSection report={report} flagged={[finding]} />);
    expect(await screen.findByText("Needs a confirmation first")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Record confirmation" }));
    const amount = screen.getByLabelText("Overcharge confirmed (CAD)");
    await userEvent.clear(amount);
    await userEvent.type(amount, "12.00");
    await userEvent.click(screen.getByRole("button", { name: "Record" }));
    await waitFor(() => expect(sent[0]).toMatchObject({ url: "/api/v1/reports/findings/f1/outcomes", body: { outcome: "controller_confirmed", amount: "12.00" } }));
  });
});

describe("S-16 account data (B9)", () => {
  it("needs the account name typed before a deletion request", async () => {
    handler = (url) => {
      if (url.includes("/exports/archive")) return { body: { items: [{ id: "a1", status: "ready", requested_at: "2026-11-13T10:00:00Z", finished_at: "2026-11-13T10:01:00Z", expires_at: "2026-11-14T10:01:00Z", file_count: 14, byte_size: 2_400_000, downloadable: true, complete: true, expected_count: 14, included_count: 14, missing_count: 0 }] } };
      if (url.includes("/account/deletion-request")) return { body: { request: null, notice_days: 30, archive: { state: "complete", included: 14, expected: 14, checked_at: "2026-11-13T10:01:00Z" } } };
      return { status: 201, body: {} };
    };
    wrap(<AccountDataPanel />);
    expect(await screen.findByRole("button", { name: "Download the archive" })).toBeInTheDocument();
    expect(screen.getByText(/Complete: 14\/14 originals, 2.4 MB/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Request deletion" }));
    const confirm = screen.getAllByRole("button", { name: "Request deletion" }).at(-1)!;
    expect(confirm).toBeDisabled();
    await userEvent.type(screen.getByLabelText(/Type the account name/), "Fictional Distributor");
    expect(confirm).toBeEnabled();
    await userEvent.click(confirm);
    await waitFor(() => expect(sent[0]).toMatchObject({ url: "/api/v1/account/deletion-requests", body: { confirm_name: "Fictional Distributor" } }));
  });
});
