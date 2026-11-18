// Free sample check (owner, 2026-11-18): the account's banner, the operator's offer choice and the
// start of the pilot. Synthetic data.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { setLastInput } from "./api/client";
import type { Pilot } from "./api/types";
import { SessionProvider } from "./app/session";
import { OperatorPage } from "./routes/Operator";
import { SampleBanner } from "./app/App";
import { setCurrency } from "./lib/decimal";

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


describe("free sample check (2026-11-18)", () => {
  it("shows the account how much of the sample is used and what the pilot adds", () => {
    render(<SampleBanner sample={{ ends_at: "2026-11-25T06:00:00Z", ended: false, invoices_used: 40, invoice_limit: 100 }} />);
    const b = screen.getByTestId("sample-banner");
    expect(b).toHaveTextContent("40 of 100 invoices used (60 left)");
    expect(b).toHaveTextContent("come with the paid pilot");
  });

  it("says when the sample has ended", () => {
    render(<SampleBanner sample={{ ends_at: "2026-11-18T06:00:00Z", ended: true, invoices_used: 100, invoice_limit: 100 }} />);
    expect(screen.getByTestId("sample-banner")).toHaveTextContent("It has ended");
  });

  it("creates a free sample by default and starts the pilot from the account page", async () => {
    handler = (url, init) => {
      if (url.endsWith("/api/v1/operator/tenants/t1/start-pilot")) return { body: { ...account("CAD", null), status: "pilot" } };
      if (url.endsWith("/api/v1/operator/tenants/t1") && (!init?.method || init.method === "GET"))
        return { body: { ...account("CAD", null), status: "sample", sample_ends_at: "2026-11-25T06:00:00Z" } };
      return { status: 404 };
    };
    wrap(<OperatorPage />, me(true), "/operator/tenants/t1", "/operator/tenants/*");
    expect(await screen.findByTestId("sample-account")).toHaveTextContent("up to 100 invoices");
    await userEvent.click(screen.getByRole("button", { name: "Start the pilot" }));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/start-pilot") && c.init?.method === "POST")).toBe(true));
  });

  it("sends the chosen offer when the operator creates an account", async () => {
    handler = (url, init) => {
      if (url.endsWith("/api/v1/operator/tenants") && init?.method === "POST") return { status: 201, body: { ...account("CAD", null), id: "t9" } };
      if (url.endsWith("/api/v1/operator/tenants/t9")) return { body: { ...account("CAD", null), id: "t9", status: "sample" } };
      if (url.includes("/api/v1/operator/tenants")) return { body: { items: [] } };
      return { body: { items: [] } };
    };
    wrap(<OperatorPage />, me(true), "/operator/tenants", "/operator/tenants/*");
    const offer = (await screen.findByLabelText("Start with")) as HTMLSelectElement;
    expect(offer.value).toBe("sample");
    await userEvent.type(screen.getByLabelText("Company name"), "Fictional Sampleco");
    await userEvent.type(screen.getByLabelText("First controller's email"), "c@fictional.example");
    await userEvent.click(screen.getByRole("button", { name: "Create account and invite" }));
    await waitFor(() => {
      const post = calls.find((c) => c.url.endsWith("/api/v1/operator/tenants") && c.init?.method === "POST");
      expect(post && JSON.parse(String(post.init?.body)).offer).toBe("sample");
    });
  });
});
