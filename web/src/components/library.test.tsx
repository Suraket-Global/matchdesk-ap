import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import {
  Badge,
  Breadcrumbs,
  Button,
  Card,
  Checkbox,
  DataTable,
  Dialog,
  Drawer,
  EmptyState,
  FileDropzone,
  IconButton,
  Input,
  PageHeader,
  Pagination,
  Select,
  StatCard,
  StatusPill,
  Stepper,
  Tabs,
  ToastHost,
  Tooltip,
  toast,
  type Column,
} from "./index";
import { subtract } from "../lib/decimal";

afterEach(cleanup);

// jsdom has no modal dialog; the browser behaviour itself is covered by Playwright.
if (!HTMLDialogElement.prototype.showModal) {
  HTMLDialogElement.prototype.showModal = function (this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function (this: HTMLDialogElement) {
    this.removeAttribute("open");
  };
}

describe("Button and IconButton", () => {
  it("renders variants and sizes as classes and is a plain button by default", () => {
    render(
      <Button variant="primary" size="sm">
        Save changes
      </Button>,
    );
    const b = screen.getByRole("button", { name: "Save changes" });
    expect(b).toHaveClass("btn", "primary", "sm");
    expect(b).toHaveAttribute("type", "button");
  });
  it("is disabled while loading and says why it is disabled", () => {
    render(
      <Button loading disabledReason="Choose a resolution first">
        Resolve
      </Button>,
    );
    const b = screen.getByRole("button", { name: "Resolve" });
    expect(b).toBeDisabled();
    expect(b).toHaveAttribute("aria-busy", "true");
    expect(b).toHaveAttribute("title", "Choose a resolution first");
  });
  it("gives an icon-only button its label as name and tooltip", async () => {
    render(<IconButton label="Zoom in" icon={<svg aria-hidden="true" />} />);
    const b = screen.getByRole("button", { name: "Zoom in" });
    await userEvent.hover(b);
    expect(screen.getByRole("tooltip")).toHaveTextContent("Zoom in");
  });
});

describe("form controls", () => {
  it("wires label, hint and error to the input", () => {
    render(<Input label="Work email" hint="Your company address" error="Enter an address" />);
    const input = screen.getByLabelText("Work email");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input.getAttribute("aria-describedby")?.split(" ")).toHaveLength(2);
    expect(screen.getByText("Enter an address")).toHaveClass("error");
  });
  it("renders a labelled select with its options and a checkbox", async () => {
    const onChange = vi.fn();
    render(
      <>
        <Select label="Sort" options={[["value", "Highest value first"], ["age", "Oldest first"]]} defaultValue="age" />
        <Checkbox label="I have reviewed the waived items" onChange={onChange} />
      </>,
    );
    expect(screen.getByLabelText("Sort")).toHaveValue("age");
    await userEvent.click(screen.getByLabelText("I have reviewed the waived items"));
    expect(onChange).toHaveBeenCalled();
  });
});

describe("badges and status pills", () => {
  it("never relies on colour alone", () => {
    render(
      <>
        <Badge tone="warning">Unverified</Badge>
        <StatusPill status="matched" />
      </>,
    );
    expect(screen.getByText("Unverified")).toHaveClass("badge", "warning");
    expect(screen.getByText("Matched")).toHaveClass("chip", "matched");
  });
});

describe("cards", () => {
  it("shows a stat with label, value and qualifier", () => {
    render(<StatCard label="Flagged discrepancies" value="CAD 926.00" sub="4 items" tone="danger" />);
    expect(screen.getByText("CAD 926.00")).toHaveClass("v");
    expect(screen.getByText("Flagged discrepancies").closest(".stat")).toHaveClass("tone-danger");
  });
  it("labels a card region by its title", () => {
    render(
      <Card title="Receipts" titleId="rc">
        body
      </Card>,
    );
    expect(screen.getByRole("region", { name: "Receipts" })).toBeInTheDocument();
  });
});

interface Row {
  id: string;
  supplier: string;
  amount: string;
}
const ROWS: Row[] = [
  { id: "a", supplier: "Synthetic Supply Co", amount: "18.00" },
  { id: "b", supplier: "Fictional Fasteners Ltd", amount: "740.00" },
  { id: "c", supplier: "Imaginary Packaging Inc", amount: "220.00" },
];
const COLS: Column<Row>[] = [
  { key: "supplier", header: "Supplier", cell: (r) => r.supplier, sortValue: (r) => r.supplier },
  { key: "amount", header: "Value (CAD)", numeric: true, cell: (r) => r.amount, sortValue: (r) => BigInt(r.amount.replace(".", "")) },
];

describe("DataTable", () => {
  it("right-aligns money, sorts by a column and announces the sort", async () => {
    render(<DataTable rows={ROWS} columns={COLS} rowKey={(r) => r.id} initialSort={{ key: "amount", dir: "desc" }} />);
    const cells = () => screen.getAllByRole("row").slice(1).map((r) => within(r).getAllByRole("cell")[1].textContent);
    expect(cells()).toEqual(["740.00", "220.00", "18.00"]);
    expect(screen.getByRole("columnheader", { name: /Value/ })).toHaveAttribute("aria-sort", "descending");
    expect(screen.getAllByRole("cell")[1]).toHaveClass("num");
    await userEvent.click(screen.getByRole("button", { name: /Value/ }));
    expect(cells()).toEqual(["18.00", "220.00", "740.00"]);
  });
  it("selects rows and all rows", async () => {
    const onSel = vi.fn();
    const { rerender } = render(<DataTable rows={ROWS} columns={COLS} rowKey={(r) => r.id} selected={new Set()} onSelectedChange={onSel} rowLabel={(r) => r.supplier} />);
    await userEvent.click(screen.getByLabelText("Select Synthetic Supply Co"));
    expect([...onSel.mock.calls[0][0]]).toEqual(["a"]);
    await userEvent.click(screen.getByLabelText("Select all rows"));
    expect([...onSel.mock.calls[1][0]].sort()).toEqual(["a", "b", "c"]);
    rerender(<DataTable rows={ROWS} columns={COLS} rowKey={(r) => r.id} selected={new Set(["b"])} onSelectedChange={onSel} />);
    expect(screen.getAllByRole("row")[1]).toHaveAttribute("aria-selected", "false");
    expect(screen.getAllByRole("row").find((r) => r.getAttribute("aria-selected") === "true")).toHaveClass("selected");
  });
  it("shows the empty state and the loading skeleton", () => {
    const { rerender } = render(<DataTable rows={[]} columns={COLS} rowKey={(r) => r.id} empty={<EmptyState title="No exceptions" />} />);
    expect(screen.getByRole("heading", { name: "No exceptions" })).toBeInTheDocument();
    rerender(<DataTable rows={undefined} columns={COLS} rowKey={(r) => r.id} loading />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading");
  });
});

describe("Tabs", () => {
  it("marks the selected tab and moves with the arrow keys", async () => {
    const onChange = vi.fn();
    render(<Tabs label="Report sections" value="a" onChange={onChange} items={[{ id: "a", label: "Findings" }, { id: "b", label: "Waived", count: 2 }]} />);
    const tab = screen.getByRole("tab", { name: "Findings" });
    expect(tab).toHaveAttribute("aria-selected", "true");
    tab.focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(onChange).toHaveBeenCalledWith("b");
  });
});

describe("Dialog and Drawer", () => {
  it("opens modally with focus on the safe button and closes on Escape", () => {
    const onClose = vi.fn();
    render(
      <Dialog open title="Approve version 1" onClose={onClose} footer={<button data-safe>Cancel</button>}>
        Approved figures cannot be changed.
      </Dialog>,
    );
    expect(screen.getByRole("dialog", { name: "Approve version 1" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
    fireEvent(screen.getByRole("dialog"), new Event("cancel", { cancelable: true }));
    expect(onClose).toHaveBeenCalled();
  });
  it("has a close button in a drawer", async () => {
    const onClose = vi.fn();
    render(
      <Drawer open title="Exception detail" onClose={onClose} footer={null}>
        detail
      </Drawer>,
    );
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalled();
  });
});

describe("Toast", () => {
  it("announces a result politely and removes it after six seconds", () => {
    vi.useFakeTimers();
    render(<ToastHost />);
    act(() => toast("Resolved: price agreed.", "success"));
    expect(screen.getByRole("status")).toHaveTextContent("Resolved: price agreed.");
    act(() => {
      vi.advanceTimersByTime(6100);
    });
    expect(screen.getByRole("status")).not.toHaveTextContent("Resolved");
    vi.useRealTimers();
  });
});

describe("Tooltip", () => {
  it("appears on keyboard focus and describes the trigger", () => {
    render(
      <Tooltip text="Fit to width">
        <button>100%</button>
      </Tooltip>,
    );
    fireEvent.focus(screen.getByRole("button"));
    const tip = screen.getByRole("tooltip");
    expect(screen.getByRole("button")).toHaveAttribute("aria-describedby", tip.id);
  });
});

describe("page furniture", () => {
  it("renders breadcrumbs with the current page unlinked", () => {
    render(
      <MemoryRouter>
        <Breadcrumbs items={[{ to: "/reports", label: "Back-test reports" }, { label: "October 2026" }]} />
      </MemoryRouter>,
    );
    expect(screen.getByRole("link", { name: "Back-test reports" })).toHaveAttribute("href", "/reports");
    expect(screen.getByText("October 2026")).toHaveAttribute("aria-current", "page");
  });
  it("renders the page header with its actions", () => {
    render(
      <MemoryRouter>
        <PageHeader title="Exception queue" lede="Highest value first." actions={<button>Back-test report</button>} />
      </MemoryRouter>,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Exception queue" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Back-test report" })).toBeInTheDocument();
  });
  it("paginates with a range sentence and disabled ends", async () => {
    const onPage = vi.fn();
    render(<Pagination page={1} pageSize={50} total={120} onPage={onPage} />);
    expect(screen.getByText("1–50 of 120")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Previous/ })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: /Next/ }));
    expect(onPage).toHaveBeenCalledWith(2);
  });
  it("shows stepper progress and marks the current step", () => {
    render(<Stepper current={1} steps={[{ label: "Connect", done: true }, { label: "Choose month", done: false }, { label: "Upload", done: false }]} />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "1");
    expect(screen.getByText("Choose month").closest("li")).toHaveAttribute("aria-current", "step");
  });
});

describe("FileDropzone", () => {
  it("passes chosen and dropped files on", async () => {
    const onFiles = vi.fn();
    const { container } = render(<FileDropzone title="Drop invoice files here" onFiles={onFiles} />);
    const file = new File(["%PDF-1.4"], "FF-1001.pdf", { type: "application/pdf" });
    await userEvent.upload(screen.getByLabelText("Choose files"), file);
    expect(onFiles).toHaveBeenCalledWith([file]);
    const zone = container.querySelector(".dropzone")!;
    fireEvent.drop(zone, { dataTransfer: { files: [file] } });
    expect(onFiles).toHaveBeenCalledTimes(2);
  });
});

describe("exact decimal difference for the match view", () => {
  it("subtracts without floats", () => {
    expect(subtract("100", "60")).toBe("40");
    expect(subtract("18.50", "18.5")).toBe("0");
    expect(subtract("4.20", "4.215")).toBe("-0.015");
    expect(subtract("0.1", "0.3")).toBe("-0.2");
  });
});
