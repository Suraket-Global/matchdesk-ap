// B16 (2026-11-17): the pilot fee and the refund threshold in the account's currency. A CAD account
// keeps CAD 500; any other currency has no default, so the operator enters the fee on S-18; the
// threshold is the fee; a report and a pilot in two currencies are never compared. Synthetic data.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { setLastInput } from "./api/client";
import type { Pilot, Report } from "./api/types";
import { SessionProvider } from "./app/session";
import { OperatorPage } from "./routes/Operator";
import { PilotCard, PilotSection } from "./routes/Pilot";
import { inCurrency, setCurrency } from "./lib/decimal";

type Handler = (url: string, init?: RequestInit) => { status?: number; body?: unknown };
let handler: Handler = () => ({ status: 404 });
const calls: { url: string; init?: RequestInit }[] = [];
beforeEach(() => {
  calls.length = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, init });
      const r = handler(url, init);
      return new Response(JSON.stringify(r.body ?? {}), { status: r.status ?? 200, headers: { "Content-Type": "application/json" } });
    }),
  );
  setLastInput(Date.now());
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  setCurrency("CAD");
});

const me = (operator: boolean) => ({
  user: { id: "u1", email: "u@example.invalid", display_name: "Synthetic user", is_operator: operator },
  memberships: operator ? [] : [{ tenant_id: "t1", role: "controller", tenant_name: "Fictional Distributor" }],
  active_tenant_id: operator ? null : "t1",
  role: operator ? null : "controller",
  csrf_token: "x",
});

function wrap(ui: React.ReactNode, who: object, path = "/", route = "*") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  qc.setQueryData(["me"], who);
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

const pilot = (over: Partial<Pilot> = {}): Pilot => ({
  id: "p1",
  price: "400.00",
  currency: "USD",
  period_start: "2026-10-01",
  period_end: "2026-10-31",
  refund_condition: "Refunded in full if the governing approved back-test report finds qualifying discrepancies below the refund threshold.",
  refund_threshold: "400.00",
  signed_terms_ref: "PT-SYN-1",
  signed_by_name: null,
  signed_by_role: null,
  delivery_mode: "application",
  governing_report_id: null,
  refund_determined_at: null,
  refund_qualifying_amount: null,
  refund_due: null,
  payment_status: "unpaid",
  outcome: null,
  version: 1,
  ...over,
});

const account = (currency: string, p: Pilot | null) => ({
  id: "t1",
  name: "Fictional Distributor",
  status: "pilot",
  created_at: "2026-10-01T00:00:00Z",
  intake_address: null,
  currency,
  pilot: p,
  usage_units: 0,
  active_grant: false,
  pending_requests: 0,
  usage: [],
  grants: [],
  first_controller: { has_controller: true, invitations: [] },
});

function operatorOn(acct: object) {
  handler = (url, init) => {
    if (url.endsWith("/api/v1/operator/tenants/t1") && (!init?.method || init.method === "GET")) return { body: acct };
    if (url.endsWith("/api/v1/operator/tenants/t1/pilot")) return { body: pilot() };
    return { status: 404 };
  };
  wrap(<OperatorPage />, me(true), "/operator/tenants/t1", "/operator/tenants/*");
}

describe("S-18 pilot fee in the account's currency", () => {
  it("asks for the fee of a USD account, with no default, and never sends a threshold apart", async () => {
    operatorOn(account("USD", null));
    const fee = (await screen.findByLabelText("Pilot fee (USD)")) as HTMLInputElement;
    expect(fee.value).toBe("");
    expect(screen.queryByLabelText(/\(CAD\)/)).toBeNull();
    expect(screen.getAllByText("Enter the pilot fee in USD").length).toBeGreaterThan(0);
    const create = screen.getByRole("button", { name: "Create pilot record" }) as HTMLButtonElement;
    expect(create.disabled).toBe(true);
    await userEvent.type(fee, "0");
    expect(screen.getAllByText("The pilot fee must be more than 0").length).toBeGreaterThan(0);
    await userEvent.clear(fee);
    await userEvent.type(fee, "400.123");
    expect(create.disabled).toBe(true);
    await userEvent.clear(fee);
    await userEvent.type(fee, "400");
    expect(screen.getByTestId("pilot-threshold").textContent).toBe("USD 400.00");
    await userEvent.type(screen.getByLabelText("Pilot starts"), "2026-10-01");
    await userEvent.type(screen.getByLabelText("Pilot ends"), "2026-10-31");
    expect(create.disabled).toBe(false);
    await userEvent.click(create);
    await waitFor(() => expect(calls.some((c) => c.init?.method === "PUT")).toBe(true));
    const body = JSON.parse(String(calls.find((c) => c.init?.method === "PUT")!.init!.body));
    expect(body.price).toBe("400");
    expect("refund_threshold" in body).toBe(false);
  });

  it("keeps CAD 500 as the default of a CAD account", async () => {
    operatorOn(account("CAD", null));
    const fee = (await screen.findByLabelText("Pilot fee (CAD)")) as HTMLInputElement;
    expect(fee.value).toBe("500.00");
    expect(screen.getByTestId("pilot-threshold").textContent).toBe("CAD 500.00");
  });

  it("asks for the fee again when a CAD record sits on a USD account, never converting it", async () => {
    operatorOn(account("USD", pilot({ currency: "CAD", price: "500.00", refund_threshold: "500.00" })));
    const fee = (await screen.findByLabelText("Pilot fee (USD)")) as HTMLInputElement;
    expect(fee.value).toBe("");
    expect(screen.getByTestId("pilot-restate").textContent).toContain("This record is in CAD (CAD 500.00) and the account is in USD");
    expect((screen.getByRole("button", { name: "Save pilot record" }) as HTMLButtonElement).disabled).toBe(true);
  });
});

describe("S-03 and S-13 pilot terms in the pilot currency", () => {
  it("shows a USD pilot in USD on S-03", async () => {
    handler = (url) => (url.endsWith("/api/v1/pilot") ? { body: { pilot: pilot(), governing: null } } : { status: 404 });
    wrap(<PilotCard />, me(false));
    expect(await screen.findByText(/USD 400.00 for/)).toBeTruthy();
    expect(screen.getByText(/Threshold: USD 400.00, the pilot fee/)).toBeTruthy();
    expect(screen.queryByText(/CAD/)).toBeNull();
  });

  it("says a USD report cannot be decided against CAD terms and offers no governing choice", async () => {
    setCurrency("USD");
    const report = { id: "r1", status: "approved", version_no: 1, qualifying_amount: "15.00", currency: "USD", period_start: "2026-10-01", period_end: "2026-10-31" } as unknown as Report;
    handler = (url) =>
      url.endsWith("/api/v1/pilot") ? { body: { pilot: pilot({ currency: "CAD", price: "500.00", refund_threshold: "500.00" }), governing: null } } : { status: 404 };
    wrap(<PilotSection r={report} />, me(false));
    expect((await screen.findByTestId("pilot-currency-mismatch")).textContent).toContain("This report is in USD and the pilot terms are in CAD");
    expect(screen.queryByRole("button", { name: /governing version/ })).toBeNull();
  });

  it("names the currency it is given", () => {
    expect(inCurrency("1234.5", "usd")).toBe("USD 1,234.50");
    expect(inCurrency(null, "USD")).toBe("");
  });
});
