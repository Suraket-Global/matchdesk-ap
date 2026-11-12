// B7 screens (web): weekly summary S-14, support access on S-16, operator console S-18, email intake.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { setLastInput } from "./api/client";
import { SessionProvider } from "./app/session";
import { WeeklyPage } from "./routes/Weekly";
import { UsersPage } from "./routes/Settings";
import { OperatorPage } from "./routes/Operator";
import { IntakeListPage } from "./routes/Intake";

HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
  this.setAttribute("open", "");
};
HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) {
  this.removeAttribute("open");
};

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
});

const me = (role: string, operator = false) => ({
  user: { id: "u1", email: "u@example.invalid", display_name: "Synthetic user", is_operator: operator },
  memberships: operator ? [] : [{ tenant_id: "t1", role, tenant_name: "Fictional Distributor" }],
  active_tenant_id: operator ? null : "t1",
  role: operator ? null : role,
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

const WEEK = {
  week_start: "2026-10-05",
  week_end: "2026-10-11",
  suppliers: [
    { vendor_id: "v1", vendor_name: "Fictional Fasteners Ltd", documents: 2, lines: 4, lines_matched: 3, pass_rate_pct: "75.0", open_count: 1, open_value: "15.00", flagged_amount: "15.00" },
  ],
  total: { documents: 2, lines: 4, lines_matched: 3, pass_rate_pct: "75.0", open_count: 1, open_value: "15.00", flagged_amount: "15.00" },
  sent: [],
};

describe("S-14 weekly summary", () => {
  it("shows the week by supplier and lets a controller email it", async () => {
    handler = (url) => (url.includes("/send") ? { body: { recipients: 1 } } : { body: WEEK });
    wrap(<WeeklyPage />, me("controller"), "/reports/weekly?week=2026-10-07");
    const table = await screen.findByRole("table", { name: "Weekly summary by supplier" });
    expect(within(table).getByText("Fictional Fasteners Ltd")).toBeInTheDocument();
    expect(calls[0].url).toContain("week_start=2026-10-05"); // any day picks its Monday
    await userEvent.click(screen.getByRole("button", { name: "Email this week now" }));
    await userEvent.click(screen.getByRole("button", { name: "Email now" }));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/weekly-summary/send") && c.init?.method === "POST")).toBe(true));
  });
  it("offers no send button to a clerk", async () => {
    handler = () => ({ body: WEEK });
    wrap(<WeeklyPage />, me("clerk"), "/reports/weekly");
    await screen.findByRole("table", { name: "Weekly summary by supplier" });
    expect(screen.queryByRole("button", { name: "Email this week now" })).toBeNull();
  });
});

describe("S-16 support access", () => {
  it("lets the controller grant a request after saying what it allows", async () => {
    const grant = { id: "g1", tenant_id: "t1", status: "requested", reason: "October back-test", hours_requested: 24, requested_by_name: "Demo Operator", requested_at: "2026-11-13T10:00:00Z", granted_by_name: null, starts_at: null, ends_at: null, ended_early_at: null };
    handler = (url) =>
      url.includes("/support-grants/g1/decision")
        ? { body: { ...grant, status: "active", ends_at: "2026-11-14T10:00:00Z" } }
        : url.includes("/support-grants")
          ? { body: { items: [grant] } }
          : { body: { items: [] } };
    wrap(<UsersPage />, me("controller"), "/settings/users");
    await userEvent.click(await screen.findByRole("button", { name: "Grant 1 day" }));
    expect(screen.getByRole("dialog")).toHaveTextContent("cannot change anything");
    await userEvent.click(screen.getByRole("button", { name: "Grant access" }));
    await waitFor(() => expect(calls.some((c) => c.url.includes("/decision") && String(c.init?.body).includes('"grant"'))).toBe(true));
  });
});

describe("S-18 operator console", () => {
  it("lists accounts with pilot and units but no documents", async () => {
    handler = () => ({
      body: {
        items: [{ id: "t1", name: "Fictional Distributor", status: "pilot", created_at: "2026-10-01T00:00:00Z", intake_address: null, pilot: null, usage_units: 13, active_grant: false, pending_requests: 1 }],
      },
    });
    wrap(<OperatorPage />, me("", true), "/operator/tenants", "/operator/tenants/*");
    expect(await screen.findByRole("link", { name: "Fictional Distributor" })).toBeInTheDocument();
    expect(screen.getByText("Requested")).toBeInTheDocument();
    expect(screen.getByText("13")).toBeInTheDocument();
  });
});

describe("S-06 email intake", () => {
  it("shows the address, allowed senders and releases a held email", async () => {
    const email = {
      address: "demo-invoices@intake.matchdesk.invalid",
      provider: "local",
      senders: [{ id: "s1", address_or_domain: "@fictional-fasteners.example" }],
      messages: [{ id: "m1", from_address: "accounts@unknown-supplier.example", subject: "Invoice", attachment_count: 1, received_at: "2026-11-13T10:00:00Z", status: "held", batch_id: null }],
    };
    handler = (url) => (url.includes("/intake/email") ? { body: email } : url.includes("/decision") ? { body: { status: "processed", batch_id: "b1" } } : { body: { items: [] } });
    wrap(<IntakeListPage />, me("clerk"), "/intake");
    expect(await screen.findByText("demo-invoices@intake.matchdesk.invalid")).toBeInTheDocument();
    expect(screen.queryByLabelText("Allow an address or a whole domain")).toBeNull(); // controller only
    await userEvent.click(screen.getByRole("button", { name: "Release into a batch" }));
    await waitFor(() => expect(calls.some((c) => c.url.includes("/intake/messages/m1/decision"))).toBe(true));
  });
});
