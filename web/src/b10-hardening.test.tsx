// B10 (web): the outside deep-QA findings on main 7206efb. All data synthetic.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { setLastInput } from "./api/client";
import { SessionProvider } from "./app/session";
import { AccountDataPanel } from "./routes/AccountData";
import { ReviewPage } from "./routes/Review";
import { WeeklyPage } from "./routes/Weekly";
import { OperationsPanel } from "./routes/Operator";
import { fireEvent } from "@testing-library/react";

vi.mock("./components/PdfViewer", () => ({ default: () => <div>pdf</div> }));

HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
  this.setAttribute("open", "");
};
HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) {
  this.removeAttribute("open");
};

type Handler = (url: string, init?: RequestInit) => { status?: number; body?: unknown } | undefined;
let handler: Handler = () => undefined;
const sent: { url: string; method: string; body: unknown }[] = [];
beforeEach(() => {
  sent.length = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      if (method !== "GET") sent.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : null });
      const r = handler(url, init) ?? { status: 404, body: { title: "Not found" } };
      return new Response(JSON.stringify(r.body ?? {}), { status: r.status ?? 200, headers: { "Content-Type": "application/json" } });
    }),
  );
  setLastInput(Date.now());
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const meFor = (role: string, operator = false) => ({
  user: { id: "u1", email: "u@example.invalid", display_name: "Synthetic user", is_operator: operator },
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

const incomplete = {
  id: "a1",
  status: "incomplete",
  requested_at: "2026-11-13T10:00:00Z",
  finished_at: "2026-11-13T10:01:00Z",
  expires_at: "2026-11-14T10:01:00Z",
  file_count: 12,
  byte_size: 2_400_000,
  downloadable: true,
  complete: false,
  expected_count: 13,
  included_count: 12,
  missing_count: 1,
};

describe("item 1: archive completeness on S-16", () => {
  it("shows Incomplete 12/13 with Retry missing files, and the deletion dialog needs an acknowledgement", async () => {
    handler = (url) => {
      if (url.endsWith("/exports/archive")) return { body: { items: [incomplete] } };
      if (url.includes("/retry")) return { status: 202, body: { ...incomplete, status: "queued" } };
      if (url.includes("/account/deletion-request"))
        return { body: { request: null, notice_days: 30, archive: { state: "incomplete", included: 12, expected: 13, checked_at: "2026-11-13T10:01:00Z" } } };
      return { status: 201, body: {} };
    };
    wrap(<AccountDataPanel />);
    expect(await screen.findByTestId("archive-state")).toHaveTextContent("Incomplete: 12/13 originals");
    expect(screen.queryByText("Ready")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Retry missing files" }));
    await waitFor(() => expect(sent[0]).toMatchObject({ url: "/api/v1/exports/archive/a1/retry", method: "POST" }));
    await userEvent.click(screen.getByRole("button", { name: "Request deletion" }));
    expect(screen.getByTestId("dialog-archive")).toHaveTextContent("Latest archive: Incomplete: 12/13 originals");
    await userEvent.type(screen.getByLabelText(/Type the account name/), "Fictional Distributor");
    const confirm = screen.getAllByRole("button", { name: "Request deletion" }).at(-1)!;
    expect(confirm).toBeDisabled(); // the acknowledgement is required
    await userEvent.click(screen.getByLabelText(/deleted without a complete archive/));
    expect(confirm).toBeEnabled();
    await userEvent.click(confirm);
    await waitFor(() => expect(sent.at(-1)).toMatchObject({ url: "/api/v1/account/deletion-requests", body: { acknowledge_incomplete_archive: true } }));
  });

  it("shows Complete 13/13 and needs no acknowledgement", async () => {
    handler = (url) => {
      if (url.endsWith("/exports/archive"))
        return { body: { items: [{ ...incomplete, status: "ready", complete: true, included_count: 13, file_count: 13, missing_count: 0 }] } };
      if (url.includes("/account/deletion-request"))
        return { body: { request: null, notice_days: 30, archive: { state: "complete", included: 13, expected: 13, checked_at: "2026-11-13T10:01:00Z" } } };
      return { status: 201, body: {} };
    };
    wrap(<AccountDataPanel />);
    expect(await screen.findByTestId("archive-state")).toHaveTextContent("Complete: 13/13 originals");
    expect(screen.queryByRole("button", { name: "Retry missing files" })).toBeNull();
  });
});

describe("item 2: Scheduled, Deleting and Cancelled are distinct", () => {
  it("offers no cancel while deleting", async () => {
    handler = (url) => {
      if (url.endsWith("/exports/archive")) return { body: { items: [] } };
      if (url.includes("/account/deletion-request"))
        return {
          body: {
            request: { id: "d1", tenant_id: "t1", status: "deleting", reason: null, requested_by: "u1", requested_at: "2026-10-01T10:00:00Z", decided_at: "2026-10-02T10:00:00Z", decision_note: null, delete_after: "2026-11-01T10:00:00Z", claimed_at: "2026-11-13T10:00:00Z", cancellable: false, version: 3, archive: { state: "complete", included: 3, expected: 3, checked_at: null, acknowledged: false } },
            notice_days: 30,
          },
        };
      return undefined;
    };
    wrap(<AccountDataPanel />);
    expect(await screen.findByText(/Deleting now/)).toBeInTheDocument();
    expect(screen.getByText("Deleting")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel the deletion" })).toBeNull();
  });

  it("says a cancelled request deleted nothing", async () => {
    handler = (url) => {
      if (url.endsWith("/exports/archive")) return { body: { items: [] } };
      if (url.includes("/account/deletion-request"))
        return {
          body: {
            request: { id: "d1", tenant_id: "t1", status: "cancelled", reason: null, requested_by: "u1", requested_at: "2026-10-01T10:00:00Z", decided_at: null, decision_note: null, delete_after: null, cancelled_at: "2026-10-03T10:00:00Z", cancellable: false, version: 2 },
            notice_days: 30,
          },
        };
      return undefined;
    };
    wrap(<AccountDataPanel />);
    expect(await screen.findByText(/was cancelled on .*nothing was deleted/)).toBeInTheDocument();
  });
});

const reviewDoc = () => ({
  id: "inv1",
  document_id: "doc1",
  vendor_id: "v1",
  vendor_name: "Fictional Fasteners Ltd",
  total: "1000.00",
  verification_status: "failed",
  qbo_bill: null,
  stale: false,
  doc_type: "invoice",
  doc_number: "FF-B10",
  doc_date: "2026-10-06",
  version: 4,
  lines: [],
  exceptions: [],
  review: {
    document_id: "doc1",
    document_state: "needs_review",
    verification_status: "failed",
    verification: {},
    fields: { doc_type: "invoice", vendor_id: "v1", doc_number: "FF-B10", doc_date: "2026-10-06", total: "1000.00", tax_total: "0.00", currency: "CAD" },
    vendor_name_read: "Fictional Fasteners Ltd",
    purchase_order_id: null,
    field_sources: {},
    review_draft: null,
    confirmed_by: null,
    confirmed_at: null,
    line_fields: [{ line_no: 1, id: "l1", supplier_item_code: "W-1", description: "Widget", qty: "100", uom: "EA", unit_price: "10", amount: "1000.00", line_kind: "item", page_no: null, field_sources: {} }],
    removed_lines: [],
    next_line_no: 2,
    version: 7,
  },
});

describe("item 3: pasting numbers on S-07 never breaks the page", () => {
  it("accepts a pasted 1,000, shows an inline reason for 1.000,5, and sends plain decimals", async () => {
    handler = (url, init) => {
      if (url.includes("/extraction") && init?.method === "PATCH") return { body: { ...reviewDoc().review, version: 8 } };
      if (url.includes("/confirm-extraction")) return { body: { id: "inv1", verification_status: "human_confirmed", version: 9 } };
      if (url.includes("/api/v1/invoices/inv1")) return { body: reviewDoc() };
      if (url.includes("/vendors")) return { body: { items: [{ id: "v1", name: "Fictional Fasteners Ltd" }] } };
      return { body: { items: [] } };
    };
    wrap(<ReviewPage />, "/invoices/inv1/review", "/invoices/:invoiceId/review", "clerk");
    const qtyField = await screen.findByLabelText("Line 1 Qty");
    // A paste replaces the value in one event, as the browser does.
    fireEvent.change(qtyField, { target: { value: "1,000" } });
    fireEvent.change(screen.getByLabelText("Line 1 Unit price"), { target: { value: "1" } });
    expect(screen.getByLabelText("Line 1 Qty")).toHaveValue("1,000"); // the field stays, as typed
    expect(screen.queryByText("This page could not be shown.", { exact: false })).toBeNull();
    expect(screen.getByText("All arithmetic checks pass.")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Line 1 Qty"), { target: { value: "1.000,5" } });
    expect(screen.getByLabelText("Line 1 Qty")).toHaveAttribute("aria-invalid", "true");
    expect(document.getElementById("l-1-qty-err")).toHaveTextContent("Use a dot for decimals: write 1000.50, not 1.000,50.");
    await userEvent.click(screen.getByRole("button", { name: "Confirm and match" }));
    expect(await screen.findByText("Fill in what is missing above before confirming.")).toBeInTheDocument();
    expect(sent.some((x) => x.url.includes("/confirm-extraction"))).toBe(false);
    fireEvent.change(screen.getByLabelText("Line 1 Qty"), { target: { value: "1,000" } });
    await userEvent.click(screen.getByRole("button", { name: "Confirm and match" }));
    await waitFor(() => expect(sent.some((x) => x.url.includes("/confirm-extraction"))).toBe(true));
    const patch = sent.find((x) => x.method === "PATCH")!.body as { lines: { qty: string; unit_price: string }[] };
    expect(patch.lines[0]).toMatchObject({ qty: "1000", unit_price: "1" });
  });
});

const weekly = (extra: object = {}) => ({
  week_start: "2026-10-05",
  week_end: "2026-10-11",
  state: "awaiting_invoices",
  measurement: { state: "awaiting_invoices", figures: false, title: "No invoices checked for this week", text: "No invoice is dated in this week, so there are no figures to read: this is not a clean result." },
  suppliers: [],
  total: { documents: 0, lines: 0, lines_matched: 0, pass_rate_pct: null, open_count: 0, open_value: "0.00", flagged_amount: "0.00" },
  sent: [],
  ...extra,
});

describe("items 5 and 6: S-14 delivery state and the unmeasured week", () => {
  it("shows the server's words for an empty week and no CAD 0.00", async () => {
    handler = (url) => (url.includes("/weekly-summary") ? { body: weekly() } : undefined);
    wrap(<WeeklyPage />, "/reports/weekly?week=2026-10-05", "/reports/weekly", "controller");
    expect(await screen.findByText("No invoices checked for this week")).toBeInTheDocument();
    expect(screen.queryByText("CAD 0.00")).toBeNull();
  });

  it("shows who did not receive the email and retries only them", async () => {
    const run = { week_start: "2026-10-05", trigger: "scheduled", recipients: 2, asked_at: "2026-10-13T16:00:00Z", sent_at: "2026-10-13T16:00:05Z", delivered: 1, failed: 1, pending: 0, deliveries: [{ recipient: "a@example.invalid", state: "sent", attempts: 1, error: null }, { recipient: "b@example.invalid", state: "failed", attempts: 1, error: "ConnectionRefusedError" }] };
    handler = (url, init) => {
      if (url.includes("/weekly-summary/send") && init?.method === "POST") return { body: { recipients: 2, delivered_now: 1, failed_now: 0, sent: 2, failed: 0, trigger: "scheduled" } };
      if (url.includes("/weekly-summary")) return { body: weekly({ state: "measured", measurement: { state: "measured", figures: true, title: null, text: null }, sent: [run] }) };
      return undefined;
    };
    wrap(<WeeklyPage />, "/reports/weekly?week=2026-10-05", "/reports/weekly", "controller");
    expect(await screen.findByTestId("weekly-deliveries")).toHaveTextContent("Not delivered");
    expect(screen.getByTestId("weekly-deliveries")).toHaveTextContent("delivered to 1 of 2 controllers");
    expect(screen.getByTestId("weekly-deliveries")).toHaveTextContent("Not delivered to b@example.invalid");
    await userEvent.click(screen.getByRole("button", { name: "Retry the failed recipients" }));
    await userEvent.click(screen.getByRole("button", { name: "Email now" }));
    await waitFor(() => expect(sent.at(-1)).toMatchObject({ url: "/api/v1/weekly-summary/send", body: { week_start: "2026-10-05" } }));
  });
});

describe("item 8: S-18 Operations", () => {
  it("lists a failing operation first with its error and the last success of the others", async () => {
    handler = (url) =>
      url.includes("/operator/operations")
        ? {
            body: {
              items: [
                { name: "weekly_summary", label: "Weekly summary email", state: "failing", last_success_at: "2026-11-12T10:00:00Z", last_failure_at: "2026-11-13T10:00:00Z", last_error: "ConnectionRefusedError", consecutive_failures: 3 },
                { name: "archive_expiry", label: "Archive expiry (24 hours)", state: "ok", last_success_at: "2026-11-13T10:00:00Z", last_failure_at: null, last_error: null, consecutive_failures: 0 },
              ],
            },
          }
        : undefined;
    wrap(<OperationsPanel />);
    expect(await screen.findByText("1 operation late or failing")).toBeInTheDocument();
    expect(screen.getByTestId("op-weekly_summary")).toHaveTextContent("Failing");
    expect(screen.getByTestId("op-weekly_summary")).toHaveTextContent("ConnectionRefusedError, 3 attempts");
    expect(screen.getByTestId("op-archive_expiry")).toHaveTextContent("On time");
  });
});
