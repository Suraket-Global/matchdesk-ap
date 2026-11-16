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
