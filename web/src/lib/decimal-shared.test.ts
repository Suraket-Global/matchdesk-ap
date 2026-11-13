// B10 (2026-11-13), outside QA items 3 and 4: the same expected values as pytest
// (backend/fixtures/decimal_cases.json), the typed-number parser and half-up rounding of negatives.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { failedChecks } from "./checks";
import { formatCents, MONEY_INPUT, multiply, parseNumberInput, QTY_INPUT, toCents } from "./decimal";

interface Cases {
  line_amount: { qty: string; unit_price: string; amount: string; why: string }[];
  round_cents: { value: string; cents: string }[];
  money_input: { input: string; value?: string; error?: boolean }[];
}
const cases = JSON.parse(readFileSync(resolve(process.cwd(), "../backend/fixtures/decimal_cases.json"), "utf8")) as Cases;

describe("shared fixture: line amounts round half up, away from zero", () => {
  it.each(cases.line_amount)("$qty × $unit_price = $amount ($why)", (c) => {
    expect(multiply(c.qty, c.unit_price, 2)).toBe(c.amount);
  });
  it.each(cases.round_cents)("cents of $value = $cents", (c) => {
    expect(formatCents(toCents(c.value)!)).toBe(c.cents);
  });
});

describe("shared fixture: typed money", () => {
  it.each(cases.money_input)("reads %j", (c) => {
    const p = parseNumberInput(c.input, MONEY_INPUT);
    if (c.error) {
      expect(p.ok).toBe(false);
      if (!p.ok) expect(p.error.length).toBeGreaterThan(10); // an actionable reason, not a code
    } else expect(p).toEqual({ ok: true, value: c.value });
  });
});

describe("the parser and the checks never throw on what is typed", () => {
  it("refuses a negative where none is allowed and too many decimals for a quantity", () => {
    expect(parseNumberInput("-5", { places: 2, whole: 12 })).toMatchObject({ ok: false });
    expect(parseNumberInput("1.23456", QTY_INPUT)).toMatchObject({ ok: false, error: "At most 4 decimal places." });
  });
  it("runs the review checks on pasted 1,000 and on nonsense without an exception", () => {
    const h = { vendor_id: "v", doc_number: "INV-1", doc_date: "2026-10-01", subtotal: "", tax_total: "0", total: "1,000.00" };
    expect(failedChecks(h, [{ line_no: 1, qty: "1,000", unit_price: "1", amount: "1,000.00", line_kind: "item" }])).toEqual([]);
    const bad = failedChecks(h, [{ line_no: 1, qty: "1.000,5", unit_price: "abc", amount: "-", line_kind: "item" }]);
    expect(bad.some((c) => c.startsWith("Line 1 Qty: Use a dot for decimals"))).toBe(true);
    expect(bad.some((c) => c.startsWith("Line 1 Unit price:"))).toBe(true);
    expect(bad.some((c) => c.startsWith("Line 1 Amount:"))).toBe(true);
  });
});
