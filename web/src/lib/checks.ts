import { formatCents, MONEY_INPUT, multiply, numberError, plainNumber, PRICE_INPUT, QTY_INPUT, sumCents, toCents, type NumberRules } from "./decimal";

export interface LineValues {
  line_no: number;
  qty: string;
  unit_price: string;
  amount: string;
  line_kind: string;
}

export interface HeaderValues {
  vendor_id: string;
  doc_number: string;
  doc_date: string;
  subtotal: string;
  tax_total: string;
  total: string;
}

/** The arithmetic checks of MH-05 in words, recomputed on every keystroke (design.md 8). The
 * server re-runs the same gates on confirmation; this list is only what the clerk sees first. */
/** The input rules of each number field on S-07 (the stored column's places and size). */
export const FIELD_RULES: Record<string, NumberRules> = {
  subtotal: MONEY_INPUT,
  tax_total: MONEY_INPUT,
  total: MONEY_INPUT,
  amount: MONEY_INPUT,
  qty: QTY_INPUT,
  unit_price: PRICE_INPUT,
};

const NAMES: Record<string, string> = { subtotal: "Subtotal", tax_total: "Tax", total: "Total", qty: "Qty", unit_price: "Unit price", amount: "Amount" };

/** Number fields that cannot be read, in words ("Line 2 Qty: Use a dot for decimals…"). Shown next to
 * the field and in the summary; they block confirmation like a missing value (B10, item 3). */
export function inputErrors(h: HeaderValues, lines: LineValues[]): string[] {
  const out: string[] = [];
  for (const k of ["subtotal", "tax_total", "total"] as const) {
    const e = numberError(h[k], FIELD_RULES[k]);
    if (e) out.push(`${NAMES[k]}: ${e}`);
  }
  for (const ln of lines)
    for (const k of ["qty", "unit_price", "amount"] as const) {
      const e = numberError(ln[k], FIELD_RULES[k]);
      if (e) out.push(`Line ${ln.line_no} ${NAMES[k]}: ${e}`);
    }
  return out;
}

export function failedChecks(raw: HeaderValues, rawLines: LineValues[]): string[] {
  const out: string[] = inputErrors(raw, rawLines);
  // The checks below run on the plain values ("1,000" is 1000); a value that cannot be read is
  // reported above and counts as empty here, so nothing throws while the clerk types.
  const h = { ...raw, subtotal: plainNumber(raw.subtotal), tax_total: plainNumber(raw.tax_total), total: plainNumber(raw.total) };
  const lines = rawLines.map((l) => ({ ...l, qty: plainNumber(l.qty, QTY_INPUT), unit_price: plainNumber(l.unit_price, PRICE_INPUT), amount: plainNumber(l.amount) }));
  if (!h.vendor_id) out.push("Supplier not identified: choose the supplier.");
  if (!h.doc_number.trim() || !h.doc_date || !raw.total.trim()) out.push("Document number, date and total are all needed.");
  if (!lines.length) out.push("The document has no lines.");
  for (const ln of lines) {
    if (ln.qty.trim() && ln.unit_price.trim()) {
      const expected = multiply(ln.qty, ln.unit_price, 2);
      if (toCents(expected) !== toCents(ln.amount || "0"))
        out.push(`Line ${ln.line_no}: ${ln.qty} × ${ln.unit_price} = ${formatCents(toCents(expected) ?? 0n)}, document shows ${formatCents(toCents(ln.amount || "0") ?? 0n)}`);
    }
  }
  const linesSum = sumCents(lines.map((l) => l.amount));
  const tax = toCents(h.tax_total || "0") ?? 0n;
  const total = toCents(h.total || "0");
  if (total !== null && linesSum + tax !== total)
    out.push(`Lines + tax = ${formatCents(linesSum + tax)}, document total ${formatCents(total)}`);
  if (h.subtotal.trim() && toCents(h.subtotal) !== linesSum)
    out.push(`Lines add up to ${formatCents(linesSum)}, document subtotal ${formatCents(toCents(h.subtotal) ?? 0n)}`);
  return out;
}
