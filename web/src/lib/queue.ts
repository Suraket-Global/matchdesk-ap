// B8: the exception queue's scope, read from and written to the address bar, so opening a case, Next
// exception, browser Back, Refresh and clearing one filter all keep the same ordered set. The server
// applies every part of it before the page is cut (backend api/queue.py).
import { day, monthName, monthRange } from "./format";
import { EXCEPTION_TYPES } from "./words";

export const DEFAULT_STATUS = "open,pending_approval";

export const STATUS_WORDS: Record<string, string> = {
  "open,pending_approval": "Open and pending approval",
  open: "Open",
  pending_approval: "Pending approval",
  resolved: "Resolved",
  waived: "Waived",
  auto_closed: "Closed by a re-match",
  "open,pending_approval,resolved,waived,auto_closed": "All",
};

export interface QueueScope {
  status: string;
  type: string;
  vendor: string;
  /** Exact dates from a report or the weekly summary; empty means the top-bar test month. */
  from: string;
  to: string;
  min: string;
  max: string;
  sort: string;
  /** Where the scope came from ("weekly"), for the words on the scope bar. */
  src: string;
}

const KEYS = ["status", "type", "vendor", "from", "to", "min", "max", "sort", "src"] as const;

export function readScope(p: URLSearchParams): QueueScope {
  const get = (k: string) => p.get(k) ?? "";
  return {
    status: get("status") || DEFAULT_STATUS,
    type: get("type"),
    vendor: get("vendor"),
    from: get("from"),
    to: get("to"),
    min: get("min"),
    max: get("max"),
    sort: get("sort") || "value",
    src: get("src"),
  };
}

/** The dates the queue covers: the exact range in the address, else the test month. */
export function scopeDates(s: QueueScope, month: string): { start: string; end: string; exact: boolean } {
  if (/^\d{4}-\d{2}-\d{2}$/.test(s.from) && /^\d{4}-\d{2}-\d{2}$/.test(s.to)) return { start: s.from, end: s.to, exact: true };
  return { ...monthRange(month), exact: false };
}

/** Query string for /api/v1/exceptions and /neighbours with the same scope. */
export function apiQuery(s: QueueScope, month: string): URLSearchParams {
  const d = scopeDates(s, month);
  const q = new URLSearchParams({ status: s.status, period_start: d.start, period_end: d.end, sort: s.sort });
  if (s.type) q.set("type", s.type);
  if (s.vendor) q.set("vendor_id", s.vendor);
  if (s.min) q.set("min_value", s.min);
  if (s.max) q.set("max_value", s.max);
  return q;
}

/** Address-bar parameters for a scope (defaults left out). */
export function scopeParams(s: Partial<QueueScope>): URLSearchParams {
  const p = new URLSearchParams();
  for (const k of KEYS) {
    const v = s[k];
    if (!v) continue;
    if (k === "status" && v === DEFAULT_STATUS) continue;
    if (k === "sort" && v === "value") continue;
    p.set(k, v);
  }
  return p;
}

/** The queue for one supplier and an exact date range (S-14 and S-13 drill-down). */
export function queueLink(opts: { vendor?: string | null; from: string; to: string; status?: string; type?: string; src?: string }): string {
  const p = scopeParams({
    vendor: opts.vendor ?? "",
    from: opts.from,
    to: opts.to,
    status: opts.status ?? DEFAULT_STATUS,
    type: opts.type ?? "",
    src: opts.src ?? "",
  });
  return `/exceptions?${p}`;
}

export function dateRangeWords(start: string, end: string): string {
  if (!start || !end) return "";
  const [ys, ms] = start.split("-");
  const [ye, me] = end.split("-");
  if (ys === ye && ms === me) {
    const a = Number(start.slice(8, 10));
    const b = Number(end.slice(8, 10));
    if (a === 1 && b >= 28 && Number(end.slice(8, 10)) === new Date(Number(ye), Number(me), 0).getDate()) return monthName(`${ys}-${ms}`);
    return `${a} to ${day(end)}`;
  }
  return `${day(start)} to ${day(end)}`;
}

/** One line naming the queue, for crumbs and the match view: "Fictional Fasteners Ltd, 5 to 11 Oct 2026". */
export function describeScope(s: QueueScope, month: string, vendorName?: string | null): string {
  const d = scopeDates(s, month);
  const parts = [dateRangeWords(d.start, d.end)];
  if (s.vendor) parts.unshift(s.vendor === "none" ? "Supplier not identified" : vendorName ?? "One supplier");
  if (s.type) parts.push(EXCEPTION_TYPES[s.type] ?? s.type);
  if (s.status !== DEFAULT_STATUS) parts.push(STATUS_WORDS[s.status] ?? s.status);
  return parts.join(", ");
}

// The last queue the person opened in this tab, so "Exceptions" in the sidebar returns to it with its
// filters (B8: the navigation keeps the task's entry point). In memory only, never browser storage.
let lastQueue = "/exceptions";
export function rememberQueue(url: string): void {
  if (url.startsWith("/exceptions")) lastQueue = url;
}
export function lastQueueUrl(): string {
  return lastQueue;
}
