import type { ExceptionItem, InvoiceDetail } from "../api/types";

type Inv = Pick<InvoiceDetail, "lines" | "exceptions">;
const live = (e: ExceptionItem) => e.status !== "auto_closed";
const waiting = (e: ExceptionItem) => e.status === "open" || e.status === "pending_approval";

/** S-09: which line and which exception the match view shows.
 *
 * The exception named in the address (`exc=`) always wins, whether it is on a line or on the whole
 * document (B14, acceptance M1: a possible duplicate opened from the queue showed the action panel of
 * a line exception of the same invoice, so a person could resolve a different exception from the one
 * they opened). Without one: the line's first exception still waiting, then a document exception
 * still waiting, then the line's first exception of any status. */
export function pickException(inv: Inv | undefined, lineParam: string | null, excParam: string | null) {
  const all = (inv?.exceptions ?? []).filter(live);
  const named = excParam ? all.find((e) => e.id === excParam) : undefined;
  const lineId =
    lineParam ||
    named?.invoice_line_id ||
    inv?.lines.find((l) => all.some((e) => e.invoice_line_id === l.id && e.status === "open"))?.id ||
    inv?.lines[0]?.id;
  const lineExcs = all.filter((e) => e.invoice_line_id === lineId);
  const docExcs = all.filter((e) => !e.invoice_line_id);
  const current = named ?? lineExcs.find(waiting) ?? docExcs.find(waiting) ?? lineExcs[0] ?? docExcs[0];
  return { lineId, lineExcs, docExcs, current };
}
