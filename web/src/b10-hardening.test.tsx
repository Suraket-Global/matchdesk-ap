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
import { ControllerDecision } from "./routes/MatchDecisions";
import { ReceivingImportPage } from "./routes/Receiving";
import { AliasesPage } from "./routes/Aliases";
import { OutcomesSection } from "./routes/ReportOutcomes";
import { TolerancesPage } from "./routes/Settings";
import { OperationsPanel, OperatorPage } from "./routes/Operator";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { act } from "@testing-library/react";
import { MAX_TOASTS, toast, ToastHost } from "./components/Toast";
import { DownloadButton } from "./components/DownloadButton";
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

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((n) => {
    const p = join(dir, n);
    if (statSync(p).isDirectory()) return sources(p);
    return /\.tsx?$/.test(n) && !/\.test\./.test(n) ? [p] : [];
  });
}

describe("item 9: toast tone", () => {
  it("guard: no failure is announced with a success or neutral tone", () => {
    const bad: string[] = [];
    for (const f of sources(resolve(process.cwd(), "src"))) {
      const text = readFileSync(f, "utf8");
      // Every toast's arguments, balanced; one whose text comes from an error must say "error".
      for (let i = text.indexOf("toast("); i >= 0; i = text.indexOf("toast(", i + 6)) {
        if (/[\w.]/.test(text[i - 1] ?? "")) continue;
        let depth = 1;
        let k = i + 6;
        while (k < text.length && depth > 0) {
          if ("([{".includes(text[k])) depth += 1;
          else if (")]}".includes(text[k])) depth -= 1;
          k += 1;
        }
        const args = text.slice(i + 6, k - 1);
        if (/errorText|\berr\b|could not|not delivered/i.test(args) && !/"error"\s*,?\s*$/.test(args.trim())) bad.push(`${f}: toast(${args.slice(0, 80)})`);
      }
    }
    expect(bad).toEqual([]);
  });

  it("an error toast stays until dismissed; at most two are shown", () => {
    vi.useFakeTimers();
    render(<ToastHost />);
    act(() => toast("Saved.", "success"));
    act(() => toast("The export could not be prepared.", "error"));
    act(() => toast("Reading from QuickBooks started.", "info"));
    expect(document.querySelectorAll(".toast").length).toBe(MAX_TOASTS);
    act(() => {
      vi.advanceTimersByTime(7000);
    });
    expect(document.querySelectorAll(".toast.error").length).toBe(1);
    expect(document.querySelectorAll(".toast.info").length).toBe(0);
    vi.useRealTimers();
  });

  it("a failed download shows its reason and Retry download inline", async () => {
    handler = () => ({ status: 503, body: { title: "Storage unavailable", detail: "The archive could not be read from storage." } });
    wrap(<DownloadButton path="/api/v1/exports/archive/a1/content" filename="x.zip">Download the archive</DownloadButton>);
    await userEvent.click(screen.getByRole("button", { name: "Download the archive" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Download failed:");
    expect(screen.getByRole("button", { name: "Retry download" })).toBeInTheDocument();
  });
});

describe("item 11: the credit decision states its facts and its effect", () => {
  it("groups invoice, credit, supplier, amount and the missing link, and says what Credited does before confirming", async () => {
    const e = { id: "e1", invoice_id: "inv1", invoice_line_id: "l1", type: "price_variance", status: "open", possibly_credited: true, reported_amount: "168.00", variance_amount: "168.00", doc_number: "INV-DEMO-7", line_no: 2, vendor_name: "Fictional Fasteners Ltd", version: 3 };
    handler = (url) => (url.includes("/credit-decision") ? { body: e } : { body: {} });
    wrap(<ControllerDecision exc={e as never} detail={{ ...e, credit_bill: { doc_number: "VC-DEMO-9", txn_date: "2026-10-20", total: "168.00" } } as never} onDone={() => undefined} />);
    const facts = screen.getByTestId("decision-facts");
    for (const t of ["INV-DEMO-7, line 2", "VC-DEMO-9, CAD 168.00", "Fictional Fasteners Ltd", "CAD 168.00", "names no invoice or line"]) expect(facts).toHaveTextContent(t);
    expect(screen.getByRole("button", { name: "Choose a decision" })).toBeDisabled();
    await userEvent.click(screen.getByRole("radio", { name: /^Credited/ }));
    expect(screen.getByTestId("decision-effect")).toHaveTextContent("Credited: CAD 168.00 nets against VC-DEMO-9 and leaves the findings.");
    await userEvent.click(screen.getByRole("button", { name: "Confirm: Credited" }));
    await waitFor(() => expect(sent.at(-1)).toMatchObject({ url: "/api/v1/exceptions/e1/credit-decision", body: { decision: "credited" } }));
  });
});

describe("item 12: the total check is one line when it agrees and opens on a mismatch", () => {
  it("shows a compact line, then both amounts, the difference and the field on a mismatch", async () => {
    handler = (url) => (url.includes("/api/v1/invoices/inv1") ? { body: reviewDoc() } : { body: { items: [] } });
    wrap(<ReviewPage />, "/invoices/inv1/review", "/invoices/:invoiceId/review", "clerk");
    const check = await screen.findByTestId("total-check");
    expect(check).toHaveTextContent("Total agrees: CAD 1,000.00 = lines + tax, as printed.");
    expect(check.querySelectorAll(".k").length).toBe(0);
    fireEvent.change(screen.getByLabelText("Total", { exact: true }), { target: { value: "1,012.50" } });
    const open = screen.getByTestId("total-check");
    expect(open).toHaveTextContent("Printed on the document1,000.00");
    expect(open).toHaveTextContent("Lines + tax1,000.00");
    expect(open).toHaveTextContent("Differs by 12.50");
    expect(open).toHaveTextContent("Check the Total field, the Tax field or a line amount: the total is higher than lines + tax by 12.50.");
    expect(open).toHaveTextContent("Source: your correction");
  });
});

describe("item 13: receiving column mapping shows a value from the file", () => {
  it("puts unmatched required fields first, shows Received qty → Qty Received → 60, and folds optional ones", async () => {
    const imp = {
      id: "r1",
      state: "draft",
      source_type: "spreadsheet",
      evidence_class: "A",
      declared_complete: false,
      rows_total: 2,
      column_map: null,
      preview: { headers: ["PO Number", "Qty Received", "When", "Line"], sample_rows: [["4471", "60", "2026-10-03", "1"], ["4471", "12", "2026-10-04", "2"]], rows_total: 2 },
    };
    handler = (url) => (url.includes("/receiving/imports/r1") ? { body: imp } : url.includes("/receiving/mappings") ? { body: { items: [] } } : { body: {} });
    wrap(<ReceivingImportPage />, "/receiving/imports/r1", "/receiving/imports/:importId", "clerk");
    const qty = await screen.findByTestId("map-qty_received");
    expect(qty).toHaveTextContent("Quantity received (required)");
    expect(qty.querySelector(".map-sample")).toHaveTextContent("60");
    // "When" does not match the date guess: the required, unmatched date comes first.
    const rows = [...document.querySelectorAll(".map-rows")[0].querySelectorAll("li")].map((li) => li.getAttribute("data-testid"));
    expect(rows[0]).toBe("map-received_date");
    expect(screen.getByTestId("map-received_date")).toHaveTextContent("Choose the column");
    const optional = document.querySelector("details.map-optional") as HTMLDetailsElement;
    expect(optional.open).toBe(false);
    expect(optional.querySelector("summary")).toHaveTextContent("Optional columns (1 of 4 matched)");
    await userEvent.selectOptions(screen.getByLabelText("Received date (required)"), "When");
    expect(screen.getByTestId("map-received_date").querySelector(".map-sample")).toHaveTextContent("2026-10-03");
  });
});

describe("item 14: aliases and tolerances show a live example and the consequence of saving", () => {
  it("alias: 1 CS → 25 EA as typed, keeps the last valid example, and says which lines it affects", async () => {
    handler = (url) => {
      if (url.includes("/api/v1/exceptions")) return { body: { items: [{ id: "e1", supplier_item_code: "W-25", vendor_id: "v1", vendor_name: "Fictional Fasteners Ltd", description: "Widget case" }, { id: "e2", supplier_item_code: "W-25", vendor_id: "v1", vendor_name: "Fictional Fasteners Ltd", description: "Widget case" }] } };
      if (url.includes("/vendors")) return { body: { items: [{ id: "v1", name: "Fictional Fasteners Ltd" }] } };
      return { body: { items: [] } };
    };
    wrap(<AliasesPage />, "/aliases?vendor=v1&code=W-25", "/aliases", "clerk");
    await screen.findByText(/W-25 \(Fictional Fasteners Ltd, 2 lines\)/);
    await userEvent.type(screen.getByLabelText("Supplier unit"), "CS");
    await userEvent.type(screen.getByLabelText("Our unit"), "EA");
    const factor = screen.getByLabelText("Conversion (our units per supplier unit)");
    fireEvent.change(factor, { target: { value: "25" } });
    expect(screen.getByTestId("alias-headline")).toHaveTextContent("1 CS → 25 EA");
    expect(screen.getByTestId("alias-consequence")).toHaveTextContent("2 open lines with code W-25 from this supplier use this alias.");
    expect(screen.getByTestId("alias-consequence")).toHaveTextContent("stay in exceptions until it is approved");
    fireEvent.change(factor, { target: { value: "2,5x" } });
    expect(screen.getByTestId("alias-headline")).toHaveTextContent("1 CS → 25 EA");
    expect(screen.getByTestId("alias-headline")).toHaveTextContent("Conversion not valid; the example still shows the last valid value, 25.");
    expect(screen.getByRole("button", { name: "Confirm alias" })).toBeDisabled();
  });

  it("tolerances: an example on the values and the lines a save re-matches, beside Save", async () => {
    const tol = { id: "t1", vendor_id: null, qty_tolerance: "0", price_tol_abs: "0.10", price_tol_pct: "2.5", charge_allowance: "5.00", valid_from: "2026-10-01T00:00:00Z", valid_to: null };
    handler = (url) => {
      if (url.includes("/tolerances/preview")) return { body: { lines_rematched: 7, exceptions_cleared: 2 } };
      if (url.includes("/api/v1/tolerances")) return { body: { default: tol, vendors: [], history: [], waiver_limit: "50.00", waiver_period_cap: "500.00", receipt_note: "A missing receiving record stays an exception." } };
      return { body: { items: [] } };
    };
    wrap(<TolerancesPage />, "/settings/tolerances", "/settings/tolerances", "controller");
    expect(await screen.findByTestId("tolerance-example")).toHaveTextContent("a PO price of CAD 10.00 passes up to CAD 10.25 per unit");
    expect(await screen.findByText(/Saving re-matches 7 lines; about 2 exceptions would then pass/, {}, { timeout: 2000 })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Price tolerance (percent)"), { target: { value: "2,5" } });
    expect(screen.getByTestId("tolerance-example")).toHaveTextContent("Not valid yet");
    expect(screen.getByTestId("tolerance-example")).toHaveTextContent("up to CAD 10.25 per unit");
    expect(screen.getByTestId("tolerance-consequence")).toHaveTextContent("Fix the value marked above");
  });
});

describe("item 15: the operator console puts pending decisions first", () => {
  it("orders requests by urgency with account, controller, date and archive; account creation is secondary", async () => {
    const base = { tenant_id: "t1", reason: null, requested_by: "u9", decided_at: null, decision_note: null, delete_after: null, version: 1 };
    const items = [
      { ...base, id: "d-sched", status: "scheduled", tenant_name: "Fictional Scheduled Ltd", requested_by_name: "Sam Controller", requested_at: "2026-09-01T10:00:00Z", delete_after: "2026-12-01T10:00:00Z", archive: { state: "complete", included: 13, expected: 13, checked_at: null, acknowledged: false } },
      { ...base, id: "d-new", status: "requested", tenant_name: "Fictional Newer Ltd", requested_by_name: "Ana Controller", requested_at: "2026-11-10T10:00:00Z", archive: { state: "incomplete", included: 12, expected: 13, checked_at: null, acknowledged: true } },
      { ...base, id: "d-old", status: "requested", tenant_name: "Fictional Older Ltd", requested_by_name: "Bo Controller", requested_at: "2026-11-01T10:00:00Z", archive: { state: "none", included: null, expected: null, checked_at: null, acknowledged: true } },
      { ...base, id: "d-gone", status: "cancelled", tenant_name: "Fictional Cancelled Ltd", requested_by_name: "Cy Controller", requested_at: "2026-08-01T10:00:00Z" },
    ];
    handler = (url) => {
      if (url.includes("/operator/deletion-requests")) return { body: { items } };
      if (url.includes("/operator/operations")) return { body: { items: [] } };
      if (url.includes("/operator/tenants")) return { body: { items: [{ id: "t1", name: "Fictional Distributor", status: "active", pilot: null, usage_units: 0, active_grant: false, pending_requests: 0 }] } };
      return { body: {} };
    };
    wrap(<OperatorPage />, "/operator", "/operator/*", "controller");
    await screen.findByText("Fictional Older Ltd");
    const rows = screen.getAllByTestId("deletion-row");
    expect(rows.map((r) => r.querySelector("strong")?.textContent)).toEqual(["Fictional Older Ltd", "Fictional Newer Ltd", "Fictional Scheduled Ltd", "Fictional Cancelled Ltd"]);
    expect(rows[0]).toHaveTextContent("Needs your decision");
    expect(rows[0]).toHaveTextContent("Requested byBo Controller");
    expect(rows[1]).toHaveTextContent("Incomplete: 12/13 originals; deletion acknowledged without a complete archive");
    expect(rows[2]).toHaveTextContent("Complete: 13/13 originals");
    expect(rows[3].closest("details")?.open).toBe(false);
    const create = screen.getByText("Create a pilot account").closest("details")!;
    expect(create.open).toBe(false);
    const table = screen.getByRole("table");
    expect(table.compareDocumentPosition(create) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});

describe("item 16: report outcomes keep the scope, the three totals and a permanent row state", () => {
  it("shows the scope and totals, and a confirmed finding as a row state with its next step", async () => {
    const report = { id: "r1", status: "approved", period_start: "2026-10-01", period_end: "2026-10-31", version_no: 2 } as never;
    const f1 = { id: "f1", exception_id: "e1", section: "finding", type: "price_variance", amount: "15.00", qualifying: true, paid_status: "unpaid", snapshot: { doc_number: "INV-1", line_no: 1 } };
    const f2 = { ...f1, id: "f2", exception_id: "e2", amount: "9.00", snapshot: { doc_number: "INV-2", line_no: 1 } };
    handler = (url) =>
      url.endsWith("/outcomes")
        ? {
            body: {
              is_governing: true,
              totals: { flagged: { count: 2, amount: "24.00" }, controller_confirmed: { count: 1, amount: "12.00" }, credit_recovered: { count: 0, amount: "0.00" } },
              by_finding: { f1: { controller_confirmed: { amount: "12.00", recorded_by_name: "Dana Controller", recorded_at: "2026-11-12T10:00:00Z" } } },
            },
          }
        : { body: { items: [] } };
    wrap(<OutcomesSection report={report} flagged={[f1, f2] as never} />);
    const scope = await screen.findByTestId("outcome-scope");
    expect(scope).toHaveTextContent("1 Oct 2026 to 31 Oct 2026, version 2, the governing version");
    expect(scope).toHaveTextContent("FlaggedCAD 24.00");
    expect(scope).toHaveTextContent("Confirmed by the controllerCAD 12.00");
    expect(scope).toHaveTextContent("Credit recoveredCAD 0.00");
    const row1 = screen.getByTestId("outcome-row-f1");
    expect(row1).toHaveClass("outcome-confirmed");
    expect(row1).toHaveTextContent("Confirmed overcharge");
    expect(row1).toHaveTextContent("Next: record the credit when the supplier issues it.");
    expect(screen.getByTestId("outcome-row-f2")).toHaveTextContent("Next: record the controller's confirmation");
  });

  it("toasts sit at the top under the header, not over the lower-right content", () => {
    const css = readFileSync(resolve(process.cwd(), "src/styles/app.css"), "utf8");
    const rule = /\.toasts \{[^}]*\}/.exec(css)![0];
    expect(rule).toContain("top: calc(var(--topbar-h)");
    expect(rule).not.toContain("bottom:");
    expect(MAX_TOASTS).toBe(2);
  });
});
