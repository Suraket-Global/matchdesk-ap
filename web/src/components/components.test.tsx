import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

afterEach(cleanup);
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StatusChip } from "./ui";
import { WorkedExample } from "../routes/Aliases";
import { TotalsBar } from "../routes/Intake";
import { EmailForm } from "../routes/Login";
import { SessionProvider } from "../app/session";

describe("status chip (DD-03)", () => {
  it("always shows a word beside its icon and colour", () => {
    render(<StatusChip status="receipt_absent" />);
    const chip = screen.getByText("Receipt absent");
    expect(chip).toHaveClass("chip", "absent");
    expect(chip.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
  });
  it("never shows receipt absent in the green family", () => {
    render(<StatusChip status="receipt_absent" />);
    expect(screen.getByText("Receipt absent")).not.toHaveClass("matched");
  });
});

describe("worked example (DD-12)", () => {
  it("recomputes with the user's numbers without floats", () => {
    render(<WorkedExample factor="12" supUom="CS" itemUom="EA" exQty="5" exPrice="50.40" />);
    expect(screen.getByText("5 CS × 12 = 60 EA; 50.40 per CS = 4.20 per EA")).toBeInTheDocument();
  });
  it("shows nothing for a conversion that is not a positive number", () => {
    const { container } = render(<WorkedExample factor="0" supUom="CS" itemUom="EA" exQty="5" exPrice="50.40" />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("batch totals (DD-08)", () => {
  it("shows six counts as text that add up to the file count", () => {
    render(<TotalsBar totals={{ queued: 1, processing: 2, ready: 5, "needs review": 2, failed: 1, "duplicate file": 1, file_count: 12 }} />);
    const group = screen.getByRole("group", { name: "Files: 12" });
    const numbers = [...group.querySelectorAll(".n")].map((n) => Number(n.textContent));
    expect(numbers.reduce((a, b) => a + b, 0)).toBe(12);
  });
});

describe("sign-in form (S-01)", () => {
  it("asks for a valid address before sending and shows the local Mailpit note in development", async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    globalThis.fetch = (async () => new Response(null, { status: 401 })) as typeof fetch;
    render(
      <QueryClientProvider client={qc}>
        <SessionProvider>
          <MemoryRouter>
            <EmailForm />
          </MemoryRouter>
        </SessionProvider>
      </QueryClientProvider>,
    );
    await userEvent.type(screen.getByLabelText("Work email"), "not-an-address");
    await userEvent.click(screen.getByRole("button", { name: "Email me a sign-in link" }));
    expect(screen.getByText(/Enter your work email address/)).toBeInTheDocument();
    expect(screen.getByText(/Local development: open Mailpit to get your link/)).toBeInTheDocument();
  });
});
