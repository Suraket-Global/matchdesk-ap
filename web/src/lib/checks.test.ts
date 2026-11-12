import { describe, expect, it } from "vitest";
import { failedChecks } from "./checks";
import { cad, compareDecimal, divide, formatCents, money, multiply, qty, sumCents, toCents } from "./decimal";

describe("decimal helpers never use floats", () => {
  it("parses and formats cents exactly", () => {
    expect(toCents("1234.5")).toBe(123450n);
    expect(toCents("0.1")! + toCents("0.2")!).toBe(30n);
    expect(toCents("4.205")).toBe(421n);
    expect(formatCents(-123456n)).toBe("-1,234.56");
    expect(money("168")).toBe("168.00");
    expect(cad("1912.4")).toBe("CAD 1,912.40");
    expect(sumCents(["0.10", "0.20", null, "1.05"])).toBe(135n);
  });
  it("multiplies and divides for worked examples", () => {
    expect(multiply("5", "12", 0)).toBe("60");
    expect(divide("50.40", "12", 2)).toBe("4.20");
    expect(multiply("12", "18.50")).toBe("222.00");
    expect(qty("60.0000")).toBe("60");
    expect(compareDecimal("4.20", "4.2")).toBe(0);
    expect(compareDecimal("10", "9.99")).toBe(1);
  });
});

describe("extraction checks in words (S-07)", () => {
  const header = { vendor_id: "v", doc_number: "INV-1", doc_date: "2026-10-01", subtotal: "", tax_total: "0", total: "222.00" };
  it("passes a document that adds up", () => {
    expect(failedChecks(header, [{ line_no: 1, qty: "12", unit_price: "18.50", amount: "222.00", line_kind: "item" }])).toEqual([]);
  });
  it("names the line and the total that do not add up", () => {
    const out = failedChecks({ ...header, total: "1248.50", tax_total: "0" }, [
      { line_no: 3, qty: "12", unit_price: "18.50", amount: "220.00", line_kind: "item" },
    ]);
    expect(out).toContain("Line 3: 12 × 18.50 = 222.00, document shows 220.00");
    expect(out).toContain("Lines + tax = 220.00, document total 1,248.50");
  });
  it("asks for the supplier when none is identified", () => {
    expect(failedChecks({ ...header, vendor_id: "" }, [{ line_no: 1, qty: "", unit_price: "", amount: "222.00", line_kind: "item" }])[0]).toMatch(
      /Supplier not identified/,
    );
  });
});
