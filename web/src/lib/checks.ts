import { formatCents, multiply, sumCents, toCents } from "./decimal";

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
export function failedChecks(h: HeaderValues, lines: LineValues[]): string[] {
  const out: string[] = [];
  if (!h.vendor_id) out.push("Supplier not identified: choose the supplier.");
  if (!h.doc_number.trim() || !h.doc_date || !h.total.trim()) out.push("Document number, date and total are all needed.");
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
