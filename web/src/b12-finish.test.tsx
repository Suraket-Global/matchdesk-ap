// B12 (web): deleting one document (S-06, S-07), the controller's usage (S-16) and resizable S-09
// panes (keyboard, double-click reset, sessionStorage per tab). All data synthetic.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRef } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { setLastInput } from "./api/client";
import { SessionProvider } from "./app/session";
import { DeleteDocument } from "./routes/DeleteDocument";
import { UsagePanel, UsageTable } from "./routes/Usage";
import { TotalsBar } from "./routes/Intake";
import {
  DEFAULT_WIDTHS,
  MIN_WIDTHS,
  PaneSeparator,
  STORAGE_KEY,
  movePane,
  parseWidths,
  usePaneWidths,
} from "./components/PaneSplitter";

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
  window.sessionStorage.clear();
});

const meFor = (role: string) => ({
  user: { id: "u1", email: "u@example.invalid", display_name: "Synthetic user", is_operator: false },
  memberships: [{ tenant_id: "t1", role, tenant_name: "Fictional Distributor" }],
  active_tenant_id: "t1",
  role,
  csrf_token: "x",
});

function wrap(ui: React.ReactNode, role = "controller") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  qc.setQueryData(["me"], meFor(role));
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

const rule = (accepted: boolean, blocked: string | null = null) => ({
  accepted,
  needs_controller: accepted,
  reason_required: accepted,
  blocked,
  removed_at: null,
  removed_reason: null,
});

const done = {
  document_id: "d1",
  removed_at: "2026-11-13T10:00:00Z",
  reason: "Uploaded twice",
  invoice_ids: ["i1"],
  results_retired: 1,
  exceptions_closed: 1,
  approvals_withdrawn: 0,
  match_run_id: "r1",
};

describe("Delete document (B12, S-06 and S-07)", () => {
  it("lets a clerk delete a document no one accepted, without a reason", async () => {
    handler = (url, init) => {
      if (url.endsWith("/documents/d1/deletion")) return { body: rule(false) };
      if (url.endsWith("/documents/d1/deletion-requests") && init?.method === "POST") return { body: { ...done, reason: null } };
    };
    const onDeleted = vi.fn();
    wrap(<DeleteDocument documentId="d1" name="INV-1" onDeleted={onDeleted} />, "clerk");
    await userEvent.click(screen.getByRole("button", { name: /delete document/i }));
    expect(await screen.findByText(/An approved report that included it does not change/)).toBeTruthy();
    expect(screen.getByLabelText("Reason (optional)")).toBeTruthy();
    const buttons = screen.getAllByRole("button", { name: "Delete document" });
    await userEvent.click(buttons[buttons.length - 1]);
    await waitFor(() => expect(onDeleted).toHaveBeenCalled());
    expect(sent).toEqual([{ url: "/api/v1/documents/d1/deletion-requests", method: "POST", body: { reason: null } }]);
  });

  it("asks the controller for a reason on an accepted document and sends it", async () => {
    handler = (url, init) => {
      if (url.endsWith("/documents/d1/deletion")) return { body: rule(true) };
      if (url.endsWith("/deletion-requests") && init?.method === "POST") return { body: done };
    };
    wrap(<DeleteDocument documentId="d1" name="INV-1" />);
    await userEvent.click(screen.getByRole("button", { name: /delete document/i }));
    expect(await screen.findByText(/Say why it is being deleted/)).toBeTruthy();
    const confirm = () => screen.getAllByRole("button", { name: "Delete document" }).at(-1) as HTMLButtonElement;
    expect(confirm().disabled).toBe(true);
    await userEvent.type(screen.getByLabelText("Reason"), "Uploaded twice");
    expect(confirm().disabled).toBe(false);
    await userEvent.click(confirm());
    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0].body).toEqual({ reason: "Uploaded twice" });
  });

  it("tells a clerk that an accepted document is the controller's to delete", async () => {
    handler = (url) => (url.endsWith("/documents/d1/deletion") ? { body: rule(true) } : undefined);
    wrap(<DeleteDocument documentId="d1" name="INV-1" />, "clerk");
    await userEvent.click(screen.getByRole("button", { name: /delete document/i }));
    expect(await screen.findByText(/only your controller can delete it/)).toBeTruthy();
    expect(screen.queryByLabelText(/Reason/)).toBeNull();
    expect((screen.getAllByRole("button", { name: "Delete document" }).at(-1) as HTMLButtonElement).disabled).toBe(true);
  });

  it("says why a document cannot be deleted yet", async () => {
    handler = (url) =>
      url.endsWith("/documents/d1/deletion") ? { body: rule(false, "this document is still being read; try again when it is ready") } : undefined;
    wrap(<DeleteDocument documentId="d1" name="INV-1" />);
    await userEvent.click(screen.getByRole("button", { name: /delete document/i }));
    expect(await screen.findByText(/still being read/)).toBeTruthy();
  });

  it("is not offered to a viewer", () => {
    wrap(<DeleteDocument documentId="d1" name="INV-1" />, "viewer");
    expect(screen.queryByRole("button", { name: /delete document/i })).toBeNull();
  });
});

describe("Batch totals with a deleted file (B12, S-06)", () => {
  it("adds a Deleted count only when there is one, and the counts add up", () => {
    render(<TotalsBar totals={{ queued: 0, processing: 0, ready: 10, "needs review": 1, failed: 0, "duplicate file": 1, deleted: 1, file_count: 13 }} />);
    expect(screen.getByText("Deleted")).toBeTruthy();
    cleanup();
    render(<TotalsBar totals={{ queued: 0, processing: 0, ready: 11, "needs review": 1, failed: 0, "duplicate file": 1, deleted: 0, file_count: 13 }} />);
    expect(screen.queryByText("Deleted")).toBeNull();
  });
});

describe("Usage (B12, S-16)", () => {
  it("shows the controller the billable units by month, without a price", async () => {
    handler = (url) =>
      url.endsWith("/api/v1/usage")
        ? {
            body: {
              items: [
                { month: "2026-09-01", invoice: 4, credit_note: 0, units: 4 },
                { month: "2026-10-01", invoice: 11, credit_note: 2, units: 13 },
              ],
              total_units: 17,
              unit: "one invoice or credit note, in the month it was first read",
            },
          }
        : undefined;
    wrap(<UsagePanel />);
    expect(await screen.findByText("17 billable units in all")).toBeTruthy();
    expect(screen.getByText("October 2026")).toBeTruthy();
    expect(screen.getByText("13")).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/CAD|\$/);
  });

  it("is the controller's only", () => {
    wrap(<UsagePanel />, "clerk");
    expect(screen.queryByText("Usage")).toBeNull();
  });

  it("says what a unit is when there is none yet", () => {
    render(<UsageTable items={[]} />);
    expect(screen.getByText(/One unit per invoice or credit note/)).toBeTruthy();
  });
});

describe("Resizable S-09 panes (B12)", () => {
  it("moves one boundary and keeps every pane above its minimum", () => {
    expect(movePane(DEFAULT_WIDTHS, 0, 4)).toEqual([40, 36, 24]);
    expect(movePane(DEFAULT_WIDTHS, 1, -6)).toEqual([36, 34, 30]);
    const shut = movePane(DEFAULT_WIDTHS, 0, -100);
    expect(shut[0]).toBe(MIN_WIDTHS[0]);
    expect(shut[0] + shut[1] + shut[2]).toBe(100);
    expect(movePane(DEFAULT_WIDTHS, 1, 100)[2]).toBe(MIN_WIDTHS[2]);
  });

  it("uses a stored value only when it is sound", () => {
    expect(parseWidths("[30,45,25]")).toEqual([30, 45, 25]);
    expect(parseWidths("[5,70,25]")).toBeNull();
    expect(parseWidths("[30,30,30]")).toBeNull();
    expect(parseWidths("not json")).toBeNull();
    expect(parseWidths(null)).toBeNull();
  });

  function Harness() {
    const grid = useRef<HTMLDivElement>(null);
    const p = usePaneWidths();
    return (
      <div ref={grid} style={p.style} data-testid="grid">
        <PaneSeparator index={0} widths={p.widths} onChange={p.update} onReset={p.reset} gridRef={grid} />
        <PaneSeparator index={1} widths={p.widths} onChange={p.update} onReset={p.reset} gridRef={grid} />
      </div>
    );
  }

  it("is a keyboard separator with values, remembered per tab, reset by a double click", async () => {
    render(<Harness />);
    const [first, second] = screen.getAllByRole("separator");
    expect(first.getAttribute("aria-orientation")).toBe("vertical");
    expect(first.getAttribute("aria-valuenow")).toBe("36");
    expect(second.getAttribute("aria-valuenow")).toBe("76");
    first.focus();
    await userEvent.keyboard("{ArrowRight}{ArrowRight}");
    expect(first.getAttribute("aria-valuenow")).toBe("40");
    expect(JSON.parse(window.sessionStorage.getItem(STORAGE_KEY) ?? "null")).toEqual([40, 36, 24]);
    await userEvent.keyboard("{Shift>}{ArrowLeft}{/Shift}");
    expect(first.getAttribute("aria-valuenow")).toBe("30");
    await userEvent.keyboard("{Home}");
    expect(first.getAttribute("aria-valuenow")).toBe(String(MIN_WIDTHS[0]));
    expect(screen.getByTestId("grid").style.getPropertyValue("--match-cols")).toContain(`minmax(0, ${MIN_WIDTHS[0]}fr)`);
    fireEvent.doubleClick(first);
    expect(first.getAttribute("aria-valuenow")).toBe("36");
    expect(window.sessionStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it("starts from the stored widths and survives blocked storage", () => {
    window.sessionStorage.setItem(STORAGE_KEY, "[30,45,25]");
    render(<Harness />);
    expect(screen.getAllByRole("separator")[0].getAttribute("aria-valuenow")).toBe("30");
    cleanup();
    const spy = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const set = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    render(<Harness />);
    const sep = screen.getAllByRole("separator")[0];
    expect(sep.getAttribute("aria-valuenow")).toBe("36");
    sep.focus();
    fireEvent.keyDown(sep, { key: "ArrowRight" });
    expect(sep.getAttribute("aria-valuenow")).toBe("38");
    spy.mockRestore();
    set.mockRestore();
  });
});
