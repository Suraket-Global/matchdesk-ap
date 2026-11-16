import type { HistoryDoc, InvoiceDetail } from "../api/types";

/** S-10: the QuickBooks bills and vendor credits with no uploaded document on one PO line, each
 * once (every invoice detail of the PO lists the same ones). The match view counts them as billed;
 * the purchase-order page did not, so the two screens disagreed (B14, acceptance m8). */
export function qboHistory(details: InvoiceDetail[], poLineId: string): HistoryDoc[] {
  const seen = new Map<string, HistoryDoc>();
  for (const d of details)
    for (const l of d.lines)
      if (l.purchase_order?.line_id === poLineId)
        for (const h of l.history ?? [])
          if (h.source === "qbo_bill") seen.set(`${h.doc_type}|${h.doc_number ?? ""}|${h.doc_date ?? ""}|${h.qty ?? ""}`, h);
  return [...seen.values()];
}

/** A quantity without its sign (a vendor credit's quantity is listed under "Credited"). */
export function unsigned(q: string | null | undefined): string {
  return (q ?? "0").replace(/^[-−]/, "");
}
