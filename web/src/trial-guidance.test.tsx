// Trial guidance (owner, 2026-11-19): the guided tour, the trial banner's next step and setup call,
// the "?" help tips and the operator's view of each trial. Synthetic data.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { setLastInput } from "./api/client";
import type { TrialState } from "./api/types";
import { SessionProvider } from "./app/session";
import { SampleBanner } from "./app/App";
import { HelpTip, Tour, TourProvider, tourSteps } from "./components/Tour";
import { OperatorPage } from "./routes/Operator";

type Handler = (url: string, init?: RequestInit) => { status?: number; body?: unknown };
let handler: Handler = () => ({ body: {} });
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

const trial = (over: Partial<TrialState> = {}): TrialState => ({
  ends_at: "2026-11-26T06:00:00Z",
  ended: false,
  day: 2,
  days: 7,
  invoices_used: 0,
  invoice_limit: 100,
  progress: {
    qbo_connected: true,
    receiving_loaded: false,
    invoices: 0,
    to_review: 0,
    findings: 0,
    findings_amount: "0.00",
    next_step: "load_receiving",
    steps_done: 1,
  },
  ...over,
});

const me = (role: string, extra: object = {}) => ({
  user: { id: "u1", email: "u@example.invalid", display_name: "Synthetic user", is_operator: false },
  memberships: [{ tenant_id: "t1", role, tenant_name: "Fictional Distributor" }],
  active_tenant_id: "t1",
  role,
  csrf_token: "x",
  ...extra,
});

function wrap(ui: React.ReactNode, who: object | null, path = "/", route = "*") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  if (who) qc.setQueryData(["me"], who);
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

describe("the guided tour", () => {
  it("walks forward and back, and finishing records it on the server", async () => {
    const done = vi.fn();
    const skip = vi.fn();
    render(<Tour steps={tourSteps(true)} onDone={done} onSkip={skip} />);
    expect(screen.getByText("Step 1 of 9")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Welcome to your 7-day free trial" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Start the tour" }));
    expect(screen.getByText("Step 2 of 9")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByText("Step 1 of 9")).toBeInTheDocument();
    for (let n = 0; n < 8; n++) await userEvent.click(screen.getByRole("button", { name: n === 0 ? "Start the tour" : "Next" }));
    expect(screen.getByRole("heading", { name: "Help is one click away" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Finish" }));
    expect(done).toHaveBeenCalledOnce();
    expect(skip).not.toHaveBeenCalled();
  });

  it("shows an example finding and the sample files on the way", async () => {
    render(<Tour steps={tourSteps(true)} onDone={() => undefined} onSkip={() => undefined} />);
    await userEvent.click(screen.getByRole("button", { name: "Start the tour" }));
    await userEvent.click(screen.getByRole("button", { name: "Next" })); // QuickBooks
    await userEvent.click(screen.getByRole("button", { name: "Next" })); // receiving
    expect(screen.getByRole("link", { name: "Download a sample receiving file" })).toHaveAttribute("href", "/samples/receiving-log-sample.csv");
    await userEvent.click(screen.getByRole("button", { name: "Next" })); // intake
    expect(screen.getByRole("link", { name: "See a sample invoice" })).toHaveAttribute("href", "/samples/sample-invoice.pdf");
    await userEvent.click(screen.getByRole("button", { name: "Next" })); // findings
    expect(screen.getByLabelText("Example finding")).toHaveTextContent("CAD 42.00");
  });

  it("leaves the QuickBooks step out for someone who cannot connect it", () => {
    expect(tourSteps(true).map((s) => s.id)).toContain("quickbooks");
    expect(tourSteps(false).map((s) => s.id)).not.toContain("quickbooks");
  });

  it("is offered once on a free trial and skipping is saved", async () => {
    handler = (url) => (url.endsWith("/api/v1/me") ? { body: me("controller", { sample: trial(), tour_state: "skipped" }) } : { body: {} });
    wrap(<TourProvider>page</TourProvider>, me("controller", { sample: trial(), tour_state: null }));
    expect(await screen.findByTestId("tour")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Skip tour" }));
    await waitFor(() => {
      const put = calls.find((c) => c.url.endsWith("/api/v1/me/tour"));
      expect(put && JSON.parse(String(put.init?.body))).toEqual({ state: "skipped" });
    });
    expect(screen.queryByTestId("tour")).toBeNull();
  });

  it("is not offered again after it was finished, nor outside a trial", () => {
    wrap(<TourProvider>page</TourProvider>, me("controller", { sample: trial(), tour_state: "done" }));
    expect(screen.queryByTestId("tour")).toBeNull();
    cleanup();
    wrap(<TourProvider>page</TourProvider>, me("controller", { sample: null, tour_state: null }));
    expect(screen.queryByTestId("tour")).toBeNull();
  });

  it("closes on Escape as a skip", async () => {
    const skip = vi.fn();
    render(<Tour steps={tourSteps(false)} onDone={() => undefined} onSkip={skip} />);
    await userEvent.keyboard("{Escape}");
    expect(skip).toHaveBeenCalledOnce();
  });
});

describe("the trial banner", () => {
  it("names the day, the one next step with a button, and offers a setup call", () => {
    wrap(<SampleBanner sample={trial({ invoices_used: 12 })} />, me("controller"));
    const b = screen.getByTestId("sample-banner");
    expect(b).toHaveTextContent("7-day free trial, day 2 of 7.");
    expect(b).toHaveTextContent("Next: load your receiving record.");
    expect(b).toHaveTextContent("12 of 100 invoices used (88 left)");
    expect(screen.getByRole("link", { name: "Load receiving file" })).toHaveAttribute("href", "/receiving");
    expect(screen.getByRole("link", { name: "Book a setup call" }).getAttribute("href")).toMatch(/^mailto:matchdesk@bitloomix\.io\?subject=Setup%20call/);
  });

  it("points at the findings once everything is loaded", () => {
    const p = { ...trial().progress!, receiving_loaded: true, invoices: 40, next_step: "read_findings" as const, steps_done: 4 };
    wrap(<SampleBanner sample={trial({ progress: p })} />, me("controller"));
    expect(screen.getByRole("link", { name: "See findings" })).toHaveAttribute("href", "/exceptions");
  });
});

describe("help tips", () => {
  it("open in place and close on Escape", async () => {
    render(<HelpTip label="what a receiving file is">The record your warehouse keeps.</HelpTip>);
    const btn = screen.getByRole("button", { name: "Help: what a receiving file is" });
    expect(btn).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(btn);
    expect(screen.getByRole("note")).toHaveTextContent("The record your warehouse keeps.");
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("note")).toBeNull();
  });
});

describe("the operator's view of each trial", () => {
  it("shows the day, the steps done and what the account is stuck on", async () => {
    const t = trial({ day: 3, invoices_used: 0, progress: { ...trial().progress!, qbo_connected: false, next_step: "connect_qbo", steps_done: 0 } });
    handler = (url) =>
      url.includes("/api/v1/operator/tenants")
        ? { body: { items: [{ id: "t1", name: "Fictional Trialco", status: "sample", created_at: "2026-11-17T00:00:00Z", intake_address: null, currency: "CAD", pilot: null, usage_units: 0, active_grant: false, pending_requests: 0, sample_ends_at: t.ends_at, trial: t }] } }
        : { body: { items: [] } };
    wrap(<OperatorPage />, { ...me(""), memberships: [], active_tenant_id: null, role: null, user: { id: "u1", email: "op@example.invalid", display_name: "Op", is_operator: true } }, "/operator/tenants", "/operator/tenants/*");
    const row = await screen.findByTestId("trial-progress");
    expect(row).toHaveTextContent("Day 3 of 7 · 0 of 4 steps · next: connect QuickBooks · 0 invoices · QuickBooks not connected");
  });
});
