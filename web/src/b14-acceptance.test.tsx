// B14 (2026-11-17, web): the findings of the independent acceptance test that live in the screens.
// M1 the exception named in the address is the one shown; M3 refused files stay visible and a batch
// never claims every file was read; M5 the operator invites an account's first controller.
// All data synthetic.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { setLastInput } from "./api/client";
import type { BatchTotals, ExceptionItem, InvoiceDetail } from "./api/types";
import { SessionProvider } from "./app/session";
import { pickException } from "./lib/matchview";
import { RefusedFiles, TotalsBar, batchVerdict, sentence } from "./routes/Intake";
import { FirstControllerPanel } from "./routes/Operator";

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

function wrap(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  qc.setQueryData(["me"], {
    user: { id: "o1", email: "op@example.invalid", display_name: "Synthetic operator", is_operator: true },
    memberships: [],
    active_tenant_id: null,
    role: "operator",
    csrf_token: "x",
  });
  render(
    <QueryClientProvider client={qc}>
      <SessionProvider>
        <MemoryRouter>
          <Routes>
            <Route path="*" element={ui} />
          </Routes>
        </MemoryRouter>
      </SessionProvider>
    </QueryClientProvider>,
  );
}

const exc = (over: Partial<ExceptionItem>): ExceptionItem =>
  ({ id: "e", type: "qty_over_received", status: "open", invoice_line_id: "l1", version: 1, reported_amount: "105.00", variance_amount: "105.00", ...over }) as ExceptionItem;

describe("M1: the match view shows the exception named in the address", () => {
  // FF-1010 of the acceptance test: a possible duplicate (whole document) and a line exception.
  const inv = {
    lines: [{ id: "l1" }, { id: "l2" }],
    exceptions: [
      exc({ id: "line-over", type: "qty_over_ordered" }),
      exc({ id: "dup", type: "possible_duplicate", invoice_line_id: null, reported_amount: "0.00" }),
      exc({ id: "l2-price", type: "price_variance", invoice_line_id: "l2" }),
      exc({ id: "gone", type: "no_po", invoice_line_id: null, status: "auto_closed" }),
    ],
  } as unknown as InvoiceDetail;

  it("opens the possible duplicate, not the line exception of the same invoice", () => {
    // The queue's Review link: line empty, exc set to the document exception.
    const got = pickException(inv, "", "dup");
    expect(got.current?.id).toBe("dup");
    expect(got.current?.type).toBe("possible_duplicate");
  });

  it("keeps the named exception even when the address also names a line", () => {
    expect(pickException(inv, "l1", "dup").current?.id).toBe("dup");
  });

  it("goes to the line of a named line exception", () => {
    const got = pickException(inv, null, "l2-price");
    expect(got.lineId).toBe("l2");
    expect(got.current?.id).toBe("l2-price");
  });

  it("without a name, shows the line's waiting exception, then a document one", () => {
    expect(pickException(inv, null, null).current?.id).toBe("line-over");
    const onlyDoc = { lines: [{ id: "l1" }], exceptions: [inv.exceptions[1]] } as unknown as InvoiceDetail;
    expect(pickException(onlyDoc, null, null).current?.id).toBe("dup");
  });

  it("never shows an exception a re-match closed, even when named", () => {
    expect(pickException(inv, null, "gone").current?.id).toBe("line-over");
  });
});

const totals = (over: Partial<BatchTotals>): BatchTotals => ({ queued: 0, processing: 0, ready: 0, "needs review": 0, failed: 0, "duplicate file": 0, file_count: 0, ...over });

describe("M3: refused files stay visible and the batch never claims too much", () => {
  it("counts the files chosen and names the refused ones in the sentence", () => {
    const t = totals({ ready: 1, file_count: 1, refused: 2 });
    expect(sentence(t)).toBe("3 files chosen: 2 refused and not read. 1 file read: 1 ready, 0 need review, 0 failed.");
    expect(sentence(totals({ ready: 2, file_count: 2 }))).toBe("2 files read: 2 ready, 0 need review, 0 failed.");
  });

  it("says every file is read only when none was refused and something was read", () => {
    expect(batchVerdict(totals({ ready: 2, file_count: 2 }))).toEqual({ tone: "ok", text: "Every file in this batch is read. Nothing needs review." });
    const mixed = batchVerdict(totals({ ready: 1, file_count: 1, refused: 1 }));
    expect(mixed?.tone).toBe("warn");
    expect(mixed?.text).toMatch(/^1 file refused and not read/);
    expect(mixed?.text).not.toMatch(/Every file/);
    const none = batchVerdict(totals({ refused: 2 }));
    expect(none?.text).toMatch(/^No file in this batch could be read: 2 files refused/);
    expect(batchVerdict(totals({}))).toBeNull(); // an empty batch claims nothing
  });

  it("lists each refused file with its reason, and the bar adds up to the files chosen", () => {
    render(
      <>
        <TotalsBar totals={totals({ ready: 1, file_count: 1, refused: 2 })} />
        <RefusedFiles
          files={[
            { name: "junk.pdf", reason: "not_supported", reason_words: "Not a PDF, PNG or JPEG file", byte_size: 24, at: null },
            { name: "empty.pdf", reason: "empty", reason_words: "The file is empty", byte_size: 0, at: null },
          ]}
        />
      </>,
    );
    expect(screen.getByRole("group", { name: "Files: 3" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "2 files refused" })).toBeTruthy();
    expect(screen.getByText("junk.pdf")).toBeTruthy();
    expect(screen.getByText("Not a PDF, PNG or JPEG file")).toBeTruthy();
    expect(screen.getByText("The file is empty")).toBeTruthy();
    expect(screen.getAllByText("Refused").length).toBeGreaterThanOrEqual(2);
  });
});

describe("M5: the operator invites an account's first controller", () => {
  it("says nobody can sign in, sends the invitation and names it", async () => {
    handler = (url, init) => (url.endsWith("/controller-invitations") && init?.method === "POST" ? { status: 201, body: { has_controller: false, invitations: [] } } : undefined);
    wrap(<FirstControllerPanel tenantId="t9" state={{ has_controller: false, invitations: [] }} />);
    expect(screen.getByText(/Nobody can sign in to this account yet/)).toBeTruthy();
    const button = screen.getByRole("button", { name: "Send invitation" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    await userEvent.type(screen.getByLabelText("First controller's email"), "first@example.invalid");
    expect(button.disabled).toBe(false);
    await userEvent.click(button);
    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]).toEqual({ url: "/api/v1/operator/tenants/t9/controller-invitations", method: "POST", body: { email: "first@example.invalid" } });
  });

  it("shows an invitation already sent, and only a statement once a controller exists", () => {
    wrap(<FirstControllerPanel tenantId="t9" state={{ has_controller: false, invitations: [{ email: "first@example.invalid", expires_at: "2026-11-24T10:00:00Z" }] }} />);
    expect(screen.getByText("first@example.invalid")).toBeTruthy();
    expect(screen.getByLabelText("Send a new invitation to")).toBeTruthy();
    cleanup();
    wrap(<FirstControllerPanel tenantId="t9" state={{ has_controller: true, invitations: [] }} />);
    expect(screen.getByText(/This account has a controller/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Send invitation" })).toBeNull();
  });
});

// --- Minors ------------------------------------------------------------------------------------
import { fireEvent } from "@testing-library/react";
import { SupportBanner } from "./app/App";
import { day, today } from "./lib/format";
import { qboHistory, unsigned } from "./lib/po";
import { ValueFilter } from "./routes/Exceptions";
import { ledgerTotal, staleMessage } from "./routes/MatchView";
import { REJECT_WORDS, WarningRows } from "./routes/Receiving";
import { creditNotesFor } from "./routes/ReportOutcomes";
import { DeletedAfterApprovalList, pct } from "./routes/Reports";
import type { InvoiceSummary } from "./api/types";

describe("m2: a stale tab says what really happened", () => {
  it("does not call an assignment a resolution", () => {
    expect(staleMessage({ status: "open", resolution_code: null })).toMatch(/still open/);
    expect(staleMessage({ status: "open", resolution_code: null })).not.toMatch(/resolved this exception/);
    expect(staleMessage({ status: "resolved", resolution_code: "source_corrected" })).toBe(
      'Someone resolved this exception a moment ago as "Source corrected". Your note is kept below if you want to add it.',
    );
    expect(staleMessage({ status: "waived", resolution_code: "waived" })).toMatch(/^Someone waived this exception/);
  });
});

describe("m3: dates are the reader's day, not the UTC day", () => {
  it("gives today's local date and shows one moment as one day", () => {
    // 23:30 local on 16 Nov is already 17 Nov in UTC for anyone west of Greenwich.
    expect(today(new Date(2026, 10, 16, 23, 30))).toBe("2026-11-16");
    const moment = new Date(2026, 11, 16, 23, 30); // local
    expect(day(moment.toISOString())).toBe("16 Dec 2026"); // the day `when` shows, whatever the UTC date
    expect(day("2026-12-17")).toBe("17 Dec 2026"); // a plain date is never shifted
  });
});

describe("m4: receiving reasons in words and rows to check", () => {
  it("has words for every reason the server gives", () => {
    for (const code of ["po_not_found", "po_ambiguous", "po_line_not_found", "po_line_ambiguous", "qty_unreadable", "qty_zero", "uom_differs_from_po", "date_unreadable"])
      expect(REJECT_WORDS[code], code).toBeTruthy();
    expect(REJECT_WORDS.qty_zero).toBe("Quantity is zero");
  });
  it("points out a negative quantity and a future date without rejecting them", () => {
    render(<WarningRows rows={[{ row: 3, reason: "negative_quantity", value: "-5" }, { row: 4, reason: "future_date", value: "2099-01-01" }]} />);
    expect(screen.getByText(/2 valid rows to check before importing/)).toBeTruthy();
    expect(screen.getByText(/Negative quantity: counted as a return/)).toBeTruthy();
    expect(screen.getByText("Dated after today")).toBeTruthy();
  });
});

describe("m5 and m6: the report page", () => {
  it("lists documents deleted after approval", () => {
    render(<DeletedAfterApprovalList docs={[{ doc_number: "FF-1004", vendor_name: "Fictional Fasteners", reason: "uploaded twice", approved_versions: [3] }]} />);
    expect(screen.getByText(/Deleted after approval\./)).toBeTruthy();
    expect(screen.getByText(/FF-1004 \(Fictional Fasteners\), in approved version 3/)).toBeTruthy();
    cleanup();
    const { container } = render(<DeletedAfterApprovalList docs={[]} />);
    expect(container.textContent).toBe("");
  });
  it("never shows a bare percent sign", () => {
    expect(pct(null)).toBe("Not measured");
    expect(pct(undefined)).toBe("Not measured");
    expect(pct("66.67")).toBe("66.67%");
    expect(pct("100.00")).toBe("100%");
  });
});

describe("m7: only the same supplier's credit notes are offered", () => {
  it("leaves out another supplier's credit note", () => {
    const items = [
      { id: "1", doc_type: "credit_note", doc_number: "CN-77", vendor_name: "Synthetic Supply Co" },
      { id: "2", doc_type: "credit_note", doc_number: "CN-12", vendor_name: "Fictional Fasteners" },
      { id: "3", doc_type: "invoice", doc_number: "FF-1", vendor_name: "Fictional Fasteners" },
    ] as unknown as InvoiceSummary[];
    expect(creditNotesFor(items, "Fictional Fasteners").map((i) => i.doc_number)).toEqual(["CN-12"]);
    expect(creditNotesFor(items, null)).toEqual([]);
  });
});

describe("m8: figures agree between screens and keep their label", () => {
  it("says Credited after a credit decision, not Exposure CAD 0.00", () => {
    const credited = ledgerTotal(exc({ status: "resolved", resolution_code: "resolved_by_credit", reported_amount: "0.00", variance_amount: "168.00" }));
    expect(credited).toEqual({ label: "Credited", value: "CAD 168.00", open: false });
    expect(ledgerTotal(exc({ reported_amount: "168.00", variance_amount: "168.00" }))).toEqual({ label: "Exposure", value: "CAD 168.00", open: true });
    expect(ledgerTotal(exc({ reported_amount: "0.00", variance_amount: "84.00" })).label).toBe("Adds nothing");
  });
  it("counts a QuickBooks bill with no document on the purchase-order page, once", () => {
    const bill = { invoice_id: null, doc_type: "invoice", doc_number: "FF-0899", doc_date: "2026-09-02", qty: "500", source: "qbo_bill" };
    const credit = { invoice_id: null, doc_type: "credit_note", doc_number: "VC-1", doc_date: "2026-09-20", qty: "-20", source: "qbo_bill" };
    const doc = { invoice_id: "i0", doc_type: "invoice", doc_number: "FF-0900", doc_date: "2026-09-03", qty: "250", source: "document" };
    const details = [
      { lines: [{ purchase_order: { line_id: "pl1" }, history: [bill, credit, doc] }] },
      { lines: [{ purchase_order: { line_id: "pl1" }, history: [bill, credit] }, { purchase_order: { line_id: "pl2" }, history: [] }] },
    ] as unknown as InvoiceDetail[];
    expect(qboHistory(details, "pl1").map((h) => h.doc_number)).toEqual(["FF-0899", "VC-1"]);
    expect(qboHistory(details, "pl2")).toEqual([]);
    expect(unsigned("-20")).toBe("20");
  });
});

describe("m10: the queue's value filter applies on Enter", () => {
  it("applies a typed amount when Enter is pressed, and refuses one it cannot read", async () => {
    const onValue = vi.fn();
    render(<ValueFilter id="min" placeholder="Min" value="" onValue={onValue} />);
    const input = screen.getByPlaceholderText("Min");
    await userEvent.type(input, "1,000");
    expect(onValue).not.toHaveBeenCalled();
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onValue).toHaveBeenCalledWith("1000");
    await userEvent.clear(input);
    await userEvent.type(input, "12a");
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onValue).toHaveBeenCalledTimes(1);
  });
});

describe("m13: the support frame ends with the access", () => {
  it("takes the operator back to the console when the account ended the access", async () => {
    const support = { tenant_id: "t1", tenant_name: "Fictional Distributor", ends_at: "2026-11-17T04:54:00Z" };
    const base = { user: { id: "o1", email: "op@example.invalid", display_name: "Synthetic operator", is_operator: true }, memberships: [], active_tenant_id: null, csrf_token: "x" };
    handler = (url) => (url.endsWith("/api/v1/me") ? { body: { ...base, role: "operator", support: null } } : undefined);
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
    qc.setQueryData(["me"], { ...base, role: "support_reader", support });
    render(
      <QueryClientProvider client={qc}>
        <SessionProvider>
          <MemoryRouter initialEntries={["/exceptions"]}>
            <Routes>
              <Route path="/exceptions" element={<SupportBanner checkEveryMs={20} />} />
              <Route path="/operator/tenants" element={<p>Operator console</p>} />
            </Routes>
          </MemoryRouter>
        </SessionProvider>
      </QueryClientProvider>,
    );
    expect(screen.getByText(/Support access, read only/)).toBeTruthy();
    expect(await screen.findByText("Operator console")).toBeTruthy();
    expect(screen.queryByText(/Support access, read only/)).toBeNull();
  });
});
