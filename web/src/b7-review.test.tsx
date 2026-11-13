// B6 A-to-Z review (2026-11-13), web regressions: audit words (M7), toasts that always leave and focus
// returned after a dialog unmounts (minors).
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
import { useState } from "react";
import { Dialog, ToastHost, toast } from "./components/index";
import { actionWord, changes, entityWord, valueWord } from "./lib/audit";

afterEach(cleanup);

if (!HTMLDialogElement.prototype.showModal) {
  HTMLDialogElement.prototype.showModal = function (this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function (this: HTMLDialogElement) {
    this.removeAttribute("open");
  };
}

describe("M7: audit log in words", () => {
  it("counts records instead of showing identifiers and names records and actions", () => {
    const ids = ["0b8e2f8e-1d1c-4f7a-9a51-1d7c5d1c9e01", "5c1e9a8e-2b3c-4d5e-8f90-123456789abc"];
    expect(valueWord(ids)).toBe("2 records");
    expect(valueWord(ids[0])).toBe("a record");
    expect(valueWord(true)).toBe("Yes");
    expect(valueWord({ a: 1, b: 2 })).toBe("2 values");
    expect(valueWord("human_confirmed")).toBe("human confirmed");
    expect(entityWord("backtest_report")).toBe("Back-test report");
    expect(actionWord("invoice.confirmed")).toBe("Extraction confirmed");
    expect(actionWord("something.new")).toBe("Something new");
  });
  it("lists only what changed, before and after side by side", () => {
    const cs = changes({ status: "open", note: "x" }, { status: "waived", note: "x", amount: "5.00" });
    expect(cs.map((c) => [c.label, c.before, c.after])).toEqual([
      ["Status", "open", "waived"],
      ["Amount", null, "5.00"],
    ]);
  });
});

describe("Toast leaves even when the host re-renders", () => {
  it("removes each toast after six seconds", () => {
    vi.useFakeTimers();
    const { rerender } = render(<ToastHost />);
    act(() => toast("Confirmed.", "success"));
    rerender(<ToastHost />);
    act(() => {
      vi.advanceTimersByTime(3000);
    });
    act(() => toast("Second.", "success"));
    act(() => {
      vi.advanceTimersByTime(3100);
    });
    expect(screen.getByRole("status")).not.toHaveTextContent("Confirmed.");
    expect(screen.getByRole("status")).toHaveTextContent("Second.");
    vi.useRealTimers();
  });
});

describe("Focus returns after a dialog that unmounts", () => {
  it("puts focus back on the opener", async () => {
    vi.useFakeTimers();
    function Host() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button onClick={() => setOpen(true)}>Open it</button>
          {open && (
            <Dialog open title="T" onClose={() => setOpen(false)} footer={<button data-safe onClick={() => setOpen(false)}>Cancel</button>}>
              body
            </Dialog>
          )}
        </>
      );
    }
    render(<Host />);
    const opener = screen.getByText("Open it");
    opener.focus();
    act(() => opener.click());
    expect(document.activeElement).toHaveTextContent("Cancel");
    act(() => (screen.getByText("Cancel") as HTMLButtonElement).click());
    act(() => {
      vi.runAllTimers();
    });
    expect(document.activeElement).toBe(opener);
    vi.useRealTimers();
  });
});
