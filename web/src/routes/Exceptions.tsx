import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { errorText, get, send } from "../api/client";
import type { Coverage, ExceptionItem, ExceptionPage, Member, Page, Vendor } from "../api/types";
import { FIGURE_STATES } from "../api/types";
import { useSession } from "../app/session";
import { usePeriod } from "../app/period";
import { useKeys } from "../app/shortcuts";
import { CheckCircle2, ChevronRight, FileBarChart, Inbox, Info, SlidersHorizontal, Upload, X } from "lucide-react";
import { Dialog, Empty, ErrorState, PageHead, StatusChip, toast, usePageTitle } from "../components/ui";
import { TableSkeleton } from "../components/States";
import { cad, cadCents, formatCents, money, qty, sumCents, toCents } from "../lib/decimal";
import { ageText, monthName, plural } from "../lib/format";
import { apiQuery, assigneeWords, dateRangeWords, DEFAULT_STATUS, readScope, rememberQueue, scopeDates, STATUS_WORDS } from "../lib/queue";
import { EXCEPTION_STATUS, RESOLUTION_CODES, RESOLUTION_HINTS, SUB_REASONS, typeWord, zeroCounted } from "../lib/words";

export function chipFor(e: ExceptionItem) {
  if (e.status === "pending_approval") return <StatusChip status="pending_approval" />;
  if (e.status === "waived") return <StatusChip status="waived" />;
  if (e.status === "resolved") return <StatusChip status="resolved" word={RESOLUTION_CODES[e.resolution_code ?? ""] ? `Resolved: ${RESOLUTION_CODES[e.resolution_code ?? ""].toLowerCase()}` : "Resolved"} />;
  if (e.status === "auto_closed") return <StatusChip status="auto_closed" />;
  if (e.type === "receipt_absent") return <StatusChip status="receipt_absent" />;
  return <StatusChip status="exception" word={EXCEPTION_STATUS[e.status] ?? "Exception"} />;
}

/** A status word only where it adds a decision fact: an open row is what the queue is (B8). */
function statusNote(e: ExceptionItem) {
  return e.status === "open" ? null : chipFor(e);
}

function value(e: ExceptionItem): string | null {
  return e.reported_amount ?? e.variance_amount;
}

const PAGE = 100;

/** Why a case needs a person, in one short line. */
function reason(e: ExceptionItem): string {
  const sub = e.sub_reason ? SUB_REASONS[e.sub_reason]?.split(":")[0] : "";
  const diff = e.variance_qty && e.variance_qty !== "0" ? ` by ${qty(e.variance_qty)}` : "";
  return `${typeWord(e.type)}${diff}${sub ? `. ${sub}` : ""}`;
}

/** S-08: what needs a person in one scope, most valuable first. The scope lives in the address bar
 * and the server applies it to the whole set before the page is cut (B8). */
export function ExceptionsPage() {
  usePageTitle("Exception queue");
  const { can } = useSession();
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const location = useLocation();
  const { month } = usePeriod();
  const scope = readScope(params);
  const sel = params.get("sel");
  useEffect(() => rememberQueue(location.pathname + location.search), [location.pathname, location.search]);
  const dates = scopeDates(scope, month);
  const query = apiQuery(scope, month);
  query.set("limit", String(PAGE));
  const list = useInfiniteQuery({
    queryKey: ["exceptions", "queue", query.toString()],
    queryFn: ({ pageParam }) => get<ExceptionPage>(`/api/v1/exceptions?${query}${pageParam ? `&cursor=${encodeURIComponent(pageParam)}` : ""}`),
    initialPageParam: "",
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    refetchInterval: 15_000,
  });
  const vendors = useQuery({ queryKey: ["vendors"], queryFn: () => get<Page<Vendor>>("/api/v1/vendors") });
  const members = useQuery({ queryKey: ["members"], queryFn: () => get<{ items: Member[]; me: string }>("/api/v1/members") });
  const period = `period_start=${dates.start}&period_end=${dates.end}`;
  // Live coverage for the same dates, from the current results; secondary to the work list.
  const coverage = useQuery({ queryKey: ["coverage", dates.start, dates.end], queryFn: () => get<Coverage>(`/api/v1/coverage?${period}`), refetchInterval: 15_000 });
  const absent = (sub: string) => `/api/v1/exceptions?limit=1&type=receipt_absent&status=open,pending_approval,resolved&sub_reason=${sub}&${period}`;
  const notReceived = useQuery({ queryKey: ["exceptions", "absent", "nr", period], queryFn: () => get<ExceptionPage>(absent("not_received")) });
  const unverified = useQuery({ queryKey: ["exceptions", "absent", "uv", period], queryFn: () => get<ExceptionPage>(absent("no_evidence,supplier_slip_only")) });

  const rows = useMemo(() => (list.data?.pages ?? []).flatMap((p) => p.items), [list.data]);
  const first = list.data?.pages[0];
  const counters = first?.type_counters ?? {};
  const vendorName = (vendors.data?.items ?? []).find((v) => v.id === scope.vendor)?.name;
  const assigneeName = (members.data?.items ?? []).find((m) => m.user_id === scope.assignee)?.name;
  const set = (patch: Record<string, string>) => {
    const p = new URLSearchParams(params);
    for (const [k, v] of Object.entries(patch)) {
      if (v) p.set(k, v);
      else p.delete(k);
    }
    p.delete("sel");
    setParams(p);
  };

  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [focus, setFocus] = useState(-1);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const rowRefs = useRef<(HTMLTableRowElement | null)[]>([]);
  useEffect(() => {
    // Returning from the match view: the same row is selected and has the keyboard focus again.
    if (!sel || !rows.length) return;
    const i = rows.findIndex((r) => r.id === sel);
    if (i >= 0) {
      setFocus(i);
      window.setTimeout(() => rowRefs.current[i]?.focus(), 0);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sel, rows.length]);
  const hrefFor = (e: ExceptionItem) => {
    const p = new URLSearchParams(params);
    p.set("sel", e.id);
    return `/invoices/${e.invoice_id}?line=${e.invoice_line_id ?? ""}&exc=${e.id}&from=${encodeURIComponent(`/exceptions?${p}`)}`;
  };
  const open = (e: ExceptionItem) => {
    const p = new URLSearchParams(params);
    p.set("sel", e.id);
    setParams(p, { replace: true });
    navigate(hrefFor(e));
  };
  const toggle = (id: string) =>
    setSelected((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  const move = (d: number) => {
    const i = Math.max(0, Math.min(rows.length - 1, focus + d));
    setFocus(i);
    rowRefs.current[i]?.focus();
  };
  useKeys(
    useMemo(
      () => ({
        j: () => move(1),
        k: () => move(-1),
        x: () => rows[focus] && can("resolve") && toggle(rows[focus].id),
      }),
      // eslint-disable-next-line react-hooks/exhaustive-deps
      [rows, focus],
    ),
  );
  const [bulkOpen, setBulkOpen] = useState(false);
  const chosen = rows.filter((r) => selected.has(r.id));
  const chosenTypes = new Set(chosen.map((c) => c.type));

  const cov = coverage.data;
  const measured = (cov?.state && FIGURE_STATES.includes(cov.state)) || (cov && cov.state === undefined && cov.item_lines > 0);
  const declared = cov?.state === "no_receiving_records" ? cov.no_receiving_declaration : null;
  const pctText = (v: string | null | undefined) => (v ? `${money(v).replace(/\.00$/, "")}%` : "Not measured");
  const viaA = measured && cov ? formatCents((toCents(cov.receipt_coverage_pct) ?? 0n) - (toCents(cov.coverage_class_b_pct) ?? 0n)) : "0";
  const stateWords: Record<string, string> = {
    awaiting_invoices: "Not measured: no invoices dated in these dates yet.",
    processing: "Not measured yet: documents are still being read or matched.",
    awaiting_receiving: "Not measured: no receiving file has been imported, so every line is receipt absent.",
    unavailable: "Not measured: no invoice line could be compared with a purchase-order line.",
  };
  const filtered = !!(scope.type || scope.vendor || scope.min || scope.max || scope.assignee || dates.exact || scope.status !== DEFAULT_STATUS);
  const clearAll = () => setParams(new URLSearchParams());
  const total = first?.total_count ?? rows.length;
  const colCount = can("resolve") ? 8 : 7;
  const datesWords = dateRangeWords(dates.start, dates.end);

  return (
    <>
      <PageHead
        title="Exception queue"
        actions={
          <Link className="btn" to="/reports">
            <FileBarChart size={16} aria-hidden="true" />
            Back-test report
          </Link>
        }
      />
      {/* Scope: what this list covers, each part removable on its own. */}
      <div className="scope-bar" role="group" aria-label="Queue scope">
        <span className="scope-chip dates">
          <span className="k">Dates</span> {datesWords}
          {dates.exact ? (
            <>
              {scope.src === "weekly" && <span className="muted"> (weekly summary)</span>}
              <button type="button" className="chip-x" aria-label={`Remove the dates ${datesWords}; show ${monthName(month)}`} onClick={() => set({ from: "", to: "", src: "" })}>
                <X size={14} aria-hidden="true" />
              </button>
            </>
          ) : (
            <span className="muted"> (test month in the top bar)</span>
          )}
        </span>
        {scope.vendor && (
          <span className="scope-chip">
            <span className="k">Supplier</span> {scope.vendor === "none" ? "Not identified" : vendorName ?? "One supplier"}
            <button type="button" className="chip-x" aria-label="Remove the supplier filter" onClick={() => set({ vendor: "" })}>
              <X size={14} aria-hidden="true" />
            </button>
          </span>
        )}
        {scope.type && (
          <span className="scope-chip">
            <span className="k">Type</span> {typeWord(scope.type)}
            <button type="button" className="chip-x" aria-label="Remove the type filter" onClick={() => set({ type: "" })}>
              <X size={14} aria-hidden="true" />
            </button>
          </span>
        )}
        <span className="scope-chip">
          <span className="k">Status</span> {STATUS_WORDS[scope.status] ?? scope.status}
          {scope.status !== DEFAULT_STATUS && (
            <button type="button" className="chip-x" aria-label="Back to open and pending approval" onClick={() => set({ status: "" })}>
              <X size={14} aria-hidden="true" />
            </button>
          )}
        </span>
        {scope.assignee && (
          <span className="scope-chip">
            <span className="k">Assignee</span> {assigneeWords(scope.assignee, assigneeName).replace(/^Assigned to /, "")}
            <button type="button" className="chip-x" aria-label="Remove the assignee filter" onClick={() => set({ assignee: "" })}>
              <X size={14} aria-hidden="true" />
            </button>
          </span>
        )}
        {(scope.min || scope.max) && (
          <span className="scope-chip">
            <span className="k">Value</span> {scope.min ? cad(scope.min) : "any"} to {scope.max ? cad(scope.max) : "any"}
            <button type="button" className="chip-x" aria-label="Remove the value filter" onClick={() => set({ min: "", max: "" })}>
              <X size={14} aria-hidden="true" />
            </button>
          </span>
        )}
        <button type="button" className="btn ghost small filters-toggle" aria-expanded={filtersOpen} aria-controls="queue-filters" onClick={() => setFiltersOpen((o) => !o)}>
          <SlidersHorizontal size={14} aria-hidden="true" />
          Filters
        </button>
        {filtered && (
          <button type="button" className="btn ghost small" onClick={clearAll}>
            Clear all
          </button>
        )}
      </div>

      <form id="queue-filters" className={`toolbar queue-filters ${filtersOpen ? "open" : ""}`} onSubmit={(e) => e.preventDefault()} aria-label="Filters">
        <div className="field">
          <label htmlFor="f-status">Status</label>
          <select id="f-status" value={scope.status} onChange={(e) => set({ status: e.target.value === DEFAULT_STATUS ? "" : e.target.value })}>
            {Object.entries(STATUS_WORDS).map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="f-vendor">Supplier</label>
          <select id="f-vendor" value={scope.vendor} onChange={(e) => set({ vendor: e.target.value })}>
            <option value="">All suppliers</option>
            {(vendors.data?.items ?? []).map((v) => (
              <option key={v.id} value={v.id}>
                {v.name}
              </option>
            ))}
            <option value="none">Supplier not identified</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="f-assignee">Assigned to</label>
          <select id="f-assignee" value={scope.assignee} onChange={(e) => set({ assignee: e.target.value })}>
            <option value="">Everyone</option>
            <option value="me">Me</option>
            <option value="none">Nobody (unassigned)</option>
            {(members.data?.items ?? [])
              .filter((m) => m.user_id !== members.data?.me)
              .map((m) => (
                <option key={m.user_id} value={m.user_id}>
                  {m.name ?? "Member"}
                </option>
              ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="f-min">Value from (CAD)</label>
          <input id="f-min" key={`min-${scope.min}`} inputMode="decimal" size={8} placeholder="0.00" defaultValue={scope.min} onBlur={(e) => e.target.value.trim() !== scope.min && set({ min: e.target.value.trim() })} />
        </div>
        <div className="field">
          <label htmlFor="f-max">Value to (CAD)</label>
          <input id="f-max" key={`max-${scope.max}`} inputMode="decimal" size={8} placeholder="Any" defaultValue={scope.max} onBlur={(e) => e.target.value.trim() !== scope.max && set({ max: e.target.value.trim() })} />
        </div>
        <div className="field">
          <label htmlFor="f-sort">Sort</label>
          <select id="f-sort" value={scope.sort} onChange={(e) => set({ sort: e.target.value === "value" ? "" : e.target.value })}>
            <option value="value">Highest value first</option>
            <option value="age">Oldest first</option>
            <option value="vendor">Supplier</option>
          </select>
        </div>
        {can("resolve") && (
          <span className="keyhints" aria-hidden="true">
            <span>
              <kbd>J</kbd>
              <kbd>K</kbd> move
            </span>
            <span>
              <kbd>Enter</kbd> open
            </span>
            <span>
              <kbd>X</kbd> select
            </span>
          </span>
        )}
      </form>

      <div className="type-tabs" role="group" aria-label="Exceptions by type">
        <button className="type-tab" aria-pressed={!scope.type} onClick={() => set({ type: "" })}>
          All <span className="n">{Object.values(counters).reduce((a, b) => a + b, 0)}</span>
        </button>
        {Object.entries({ ...(scope.type ? { [scope.type]: 0 } : {}), ...counters })
          .sort((a, b) => b[1] - a[1])
          .map(([t, n]) => (
            <button key={t} className="type-tab" aria-pressed={scope.type === t} onClick={() => set({ type: scope.type === t ? "" : t })}>
              {typeWord(t)} <span className="n">{n}</span>
            </button>
          ))}
      </div>

      {can("resolve") && chosen.length > 0 && (
        <div className="bulkbar" role="region" aria-label="Bulk actions">
          <span>
            <strong>{chosen.length}</strong> selected · <strong>{cadCents(sumCents(chosen.map(value)))}</strong>
          </span>
          <button type="button" className="btn primary" disabled={chosenTypes.size !== 1} onClick={() => setBulkOpen(true)}>
            Resolve {plural(chosen.length, "item")} as…
          </button>
          <button type="button" className="btn ghost" onClick={() => setSelected(new Set())}>
            Clear selection
          </button>
          {can("assign_exception") && <BulkAssign chosen={chosen} members={members.data?.items ?? []} me={members.data?.me ?? ""} onDone={() => setSelected(new Set())} />}
          {chosenTypes.size > 1 && <span className="note">Bulk resolve works on one type at a time.</span>}
        </div>
      )}
      <p className="sr-only" role="status" aria-live="polite">
        {list.isFetching || !first ? "" : `${plural(total, "exception")} in this scope, ${cad(first.total_value ?? "0")}.`}
      </p>
      {list.isLoading && <TableSkeleton label="Loading exceptions" />}
      {list.error && <ErrorState error={list.error} retry={() => list.refetch()} />}
      {list.data && rows.length === 0 && (
        <div className="panel">
          {!filtered && cov?.state && !FIGURE_STATES.includes(cov.state) && cov.state !== "unavailable" ? (
            <Empty
              title={
                cov.state === "awaiting_invoices"
                  ? `No invoices dated in ${datesWords} yet`
                  : cov.state === "processing"
                    ? "Matching is still running"
                    : "Waiting for receiving evidence"
              }
              icon={<Inbox size={22} />}
              action={
                cov.state === "awaiting_invoices" && can("upload") ? (
                  <Link className="btn primary" to="/intake">
                    <Upload size={16} aria-hidden="true" />
                    Upload invoices
                  </Link>
                ) : cov.state === "awaiting_receiving" && can("upload") ? (
                  <Link className="btn primary" to="/receiving">
                    Load the receiving file
                  </Link>
                ) : undefined
              }
            >
              <p>
                {cov.state === "awaiting_invoices"
                  ? "Nothing has been checked for these dates, so there is nothing to clear. Exceptions appear here as each invoice is matched."
                  : cov.state === "processing"
                    ? "Exceptions appear here as each invoice is matched. This list refreshes by itself."
                    : "Invoices are matched, but without a receiving file no line can pass. Import the warehouse receiving file first."}
              </p>
            </Empty>
          ) : (
            <Empty
              icon={<CheckCircle2 size={22} />}
              title={scope.type ? `No ${scope.status.startsWith("open") ? "open " : ""}exceptions of type "${typeWord(scope.type)}".` : !filtered ? `No open exceptions for ${datesWords}.` : "No exceptions match these filters."}
              action={
                filtered ? (
                  <button type="button" className="btn" onClick={clearAll}>
                    Clear the filters
                  </button>
                ) : (
                  <Link className="btn primary" to="/reports">
                    Open the back-test report
                  </Link>
                )
              }
            />
          )}
        </div>
      )}
      {rows.length > 0 && (
        <>
          {/* Phone layout: one case per block, its review control inside it (B8). */}
          <ul className="case-list" aria-label="Exceptions">
            {rows.map((e) => (
              <li key={e.id} className={`case ${sel === e.id ? "selected" : ""}`}>
                <div className="case-top">
                  <span className="case-doc">
                    {e.doc_number ?? "No number"}
                    {e.line_no ? <span className="muted"> line {e.line_no}</span> : null}
                  </span>
                  <span className="case-amt money">{zeroCounted(e) ? "CAD 0.00" : cad(value(e))}</span>
                </div>
                <div className="case-why">{reason(e)}</div>
                <div className="case-sup">
                  {e.vendor_name ?? "Supplier not identified"}
                  {e.po_number ? ` · PO ${e.po_number}` : ""}
                </div>
                {e.assigned_to && <div className="case-sup">Assigned to {e.assigned_to === members.data?.me ? "you" : e.assigned_to_name ?? "a member"}</div>}
                <div className="case-foot">
                  {statusNote(e) ?? <span className="muted small">{ageText(e.raised_at)}</span>}
                  <Link className="btn small primary" to={hrefFor(e)} onClick={(ev) => { ev.preventDefault(); open(e); }} aria-label={`Review ${e.doc_number ?? "document"} ${typeWord(e.type)}`}>
                    Review
                    <ChevronRight size={14} aria-hidden="true" />
                  </Link>
                </div>
              </li>
            ))}
          </ul>
          <div className="table-wrap sticky queue-wrap">
            <table className="queue-table">
              <caption className="sr-only">Exceptions</caption>
              <thead>
                <tr>
                  {can("resolve") && (
                    <th scope="col" className="check">
                      <input
                        type="checkbox"
                        aria-label="Select all shown"
                        checked={rows.length > 0 && rows.every((r) => selected.has(r.id))}
                        onChange={(e) => setSelected(e.target.checked ? new Set(rows.map((r) => r.id)) : new Set())}
                      />
                    </th>
                  )}
                  <th scope="col">Invoice and supplier</th>
                  <th scope="col">Why it needs you</th>
                  <th scope="col">PO and item</th>
                  <th scope="col" className="num">
                    Qty difference
                  </th>
                  <th scope="col" className="num" aria-sort={scope.sort === "value" ? "descending" : "none"}>
                    Amount (CAD)
                  </th>
                  <th scope="col" aria-sort={scope.sort === "age" ? "ascending" : "none"}>
                    Age
                  </th>
                  <th scope="col">
                    <span className="sr-only">Action</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((e, i) => (
                  <tr
                    key={e.id}
                    ref={(el) => (rowRefs.current[i] = el)}
                    tabIndex={0}
                    className={`row-link ${selected.has(e.id) || sel === e.id ? "selected" : ""} ${focus === i ? "focused" : ""}`}
                    aria-selected={selected.has(e.id)}
                    onFocus={() => setFocus(i)}
                    onClick={(ev) => {
                      if ((ev.target as HTMLElement).closest("input,a,button")) return;
                      open(e);
                    }}
                    onKeyDown={(ev) => {
                      if (ev.key === "Enter" && ev.target === ev.currentTarget) open(e);
                    }}
                  >
                    {can("resolve") && (
                      <td className="check">
                        <input type="checkbox" aria-label={`Select ${typeWord(e.type)} on ${e.doc_number}`} checked={selected.has(e.id)} onChange={() => toggle(e.id)} />
                      </td>
                    )}
                    <td className="doc-cell">
                      <span className="cell-main">
                        {e.doc_number ?? "No number"}
                        {e.line_no ? <span className="muted"> · line {e.line_no}</span> : null}
                      </span>
                      <span className="cell-sub wrap-name">{e.vendor_name ?? "Supplier not identified"}</span>
                      {e.assigned_to && <span className="cell-sub assignee">Assigned to {e.assigned_to === members.data?.me ? "you" : e.assigned_to_name ?? "a member"}</span>}
                    </td>
                    <td>
                      <span className="cell-main">{typeWord(e.type)}</span>
                      {e.sub_reason && <span className="cell-sub">{SUB_REASONS[e.sub_reason] ?? e.sub_reason}</span>}
                      {statusNote(e)}
                    </td>
                    <td className="nowrap">
                      <span className="cell-main">{e.po_number ? `PO ${e.po_number}` : <span className="muted">No PO</span>}</span>
                      <span className="cell-sub">{e.supplier_item_code}</span>
                    </td>
                    <td className="num">{e.variance_qty && e.variance_qty !== "0" ? `+${qty(e.variance_qty)}` : ""}</td>
                    <td className="num">
                      <span className="cell-main">{money(value(e))}</span>
                      {zeroCounted(e) && <span className="cell-sub">counted under another exception</span>}
                    </td>
                    <td className="nowrap muted">{ageText(e.raised_at)}</td>
                    <td className="action-cell">
                      <Link to={hrefFor(e)} onClick={(ev) => { ev.preventDefault(); open(e); }} aria-label={`Review ${e.doc_number ?? "document"} ${typeWord(e.type)}`}>
                        Review
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <td colSpan={colCount - 3}>
                    {rows.length < total ? `Showing ${rows.length} of ${plural(total, "exception")}` : plural(total, "exception")} in this scope
                  </td>
                  <td className="num" data-queue-total>
                    {first ? money(first.total_value) : ""}
                  </td>
                  <td colSpan={2} />
                </tr>
              </tfoot>
            </table>
          </div>
          <p className="queue-total-line">
            <strong>{plural(total, "exception")}</strong>, <strong className="money">{cad(first?.total_value)}</strong> in this scope
            {rows.length < total ? ` (${rows.length} shown)` : ""}.
          </p>
        </>
      )}
      {list.hasNextPage && (
        <button className="btn" style={{ marginTop: 12 }} onClick={() => list.fetchNextPage()} disabled={list.isFetchingNextPage}>
          Show the next {Math.min(PAGE, total - rows.length)}
        </button>
      )}

      <details className="count-notes">
        <summary>
          <Info size={14} aria-hidden="true" />
          Why counts differ between screens
        </summary>
        <ul>
          <li>
            <strong>This list</strong>: every exception in the scope above ({datesWords}, {STATUS_WORDS[scope.status]?.toLowerCase() ?? scope.status}), by the date of its document.
          </li>
          <li>
            <strong>Sidebar</strong>: open exceptions of every period, waiting for a person now; pending approval is not counted there.
          </li>
          <li>
            <strong>Back-test report</strong>: the month as frozen at the draft&apos;s data cut-off; later resolutions change the live list, not an approved version.
          </li>
          <li>
            <strong>Weekly summary</strong>: documents dated Monday to Sunday, open and pending approval. Its counts open here with the same dates and supplier.
          </li>
        </ul>
      </details>

      <details className="coverage-details">
        <summary>
          <span className="k">Receipt coverage, {datesWords}</span>
          <span className="v">{measured ? pctText(cov?.receipt_coverage_pct) : "Not measured"}</span>
          {measured && (
            <span className="s">
              Not received {cad(notReceived.data?.total_value ?? "0")} · Unverified {cad(unverified.data?.total_value ?? "0")}
            </span>
          )}
        </summary>
        {declared && (
          <p className="declared-note" data-testid="queue-no-receiving">
            No warehouse receiving records: declared by {declared.declared_by_name ?? "the controller"}. Every line is receipt
            absent with no receiving evidence (unverified); price, ordered-quantity and duplicate checks
            still run. The report is a two-way match.
          </p>
        )}
        {!measured ? (
          <p className="muted">{stateWords[cov?.state ?? ""] ?? "Not measured yet."}</p>
        ) : (
          <div className="coverage" role="note" aria-label="Receipt coverage">
            <div>
              <span className="k">Receipt coverage </span>
              <span className="v">{pctText(cov?.receipt_coverage_pct)}</span>
              <span className="s">
                {" "}
                of invoiced PO lines (warehouse log {pctText(viaA)}, signed delivery documents {pctText(cov?.coverage_class_b_pct)})
              </span>
            </div>
            <div>
              <span className="k">Not received </span>
              <span className={`v ${notReceived.data?.total_count ? "danger" : ""}`}>{cad(notReceived.data?.total_value ?? "0")}</span>
              <span className="s"> {plural(notReceived.data?.total_count ?? 0, "line")}: the log covers the order and shows nothing</span>
            </div>
            <div>
              <span className="k">Unverified </span>
              <span className={`v ${unverified.data?.total_count ? "warn" : ""}`}>{cad(unverified.data?.total_value ?? "0")}</span>
              <span className="s"> {plural(unverified.data?.total_count ?? 0, "line")} with no receiving evidence</span>
            </div>
            <div>
              <span className="k">Complete warehouse log </span>
              <span className="v">{pctText(cov?.coverage_class_a_pct)}</span>
              <span className="s">
                {" "}
                of lines are inside a log you declared complete; it counts lines the log shows as not received too. <Link to="/receiving">Receiving imports</Link>
              </span>
            </div>
          </div>
        )}
      </details>
      {bulkOpen && <BulkDialog items={chosen} onClose={(done) => { setBulkOpen(false); if (done) setSelected(new Set()); }} />}
    </>
  );
}

interface BulkResult {
  id: string;
  result: string;
  reason?: string;
}

export function BulkDialog({ items: chosenNow, onClose }: { items: ExceptionItem[]; onClose: (done: boolean) => void }) {
  // The rows as chosen when the dialog opened: after the run they leave the open queue, and the
  // per-item results must still name them (review W6).
  const [items] = useState(chosenNow);
  const qc = useQueryClient();
  const { role } = useSession();
  const t = items[0]?.type;
  const codes = (items[0]?.allowed_codes ?? []).filter((c) => !(t === "receipt_absent" && c === "waived")).filter((c) => role === "controller" || c !== "confirmed_not_received");
  // Nothing chosen until the person chooses (B6 review minor).
  const [code, setCode] = useState("");
  const [note, setNote] = useState("");
  const total = sumCents(items.map(value));
  const tol = useQuery({ queryKey: ["tolerances"], queryFn: () => get<{ waiver_limit: string; waiver_period_cap: string }>("/api/v1/tolerances") });
  const overCap = code === "waived" && tol.data && total > (toCents(tol.data.waiver_period_cap) ?? 0n);
  const run = useMutation({
    mutationFn: () =>
      send<{ results: BulkResult[] }>("POST", "/api/v1/exceptions/bulk-resolutions", {
        items: items.map((i) => ({ id: i.id, version: i.version })),
        code,
        note: note || null,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["exceptions"] }),
  });
  const res = run.data?.results;
  const count = (k: string) => res?.filter((r) => r.result === k).length ?? 0;
  const byId = new Map(items.map((i) => [i.id, i]));
  return (
    <Dialog
      open
      title={res ? "Bulk resolution result" : `Resolve ${plural(items.length, "item")} as…`}
      onClose={() => onClose(!!res)}
      footer={
        res ? (
          <button className="btn primary" data-safe onClick={() => onClose(true)}>
            Close
          </button>
        ) : (
          <>
            <button className="btn" data-safe onClick={() => onClose(false)}>
              Cancel
            </button>
            <button className="btn primary" disabled={!code || (code === "waived" && !note.trim()) || run.isPending} onClick={() => run.mutate()}>
              Resolve {plural(items.length, "item")}
            </button>
          </>
        )
      }
    >
      {!res && (
        <>
          <p>
            {plural(items.length, "item")} of type <strong>{typeWord(t)}</strong>, total value <strong>{cadCents(total)}</strong>.
          </p>
          {t === "receipt_absent" && <p className="muted">A receipt-absent exception cannot be waived in bulk.</p>}
          <fieldset>
            <legend>Resolve as</legend>
            {codes.map((c) => (
              <label className="choice" key={c}>
                <input type="radio" name="bulk-code" checked={code === c} onChange={() => setCode(c)} />
                <span>
                  {RESOLUTION_CODES[c] ?? c}
                  <br />
                  <span className="muted small">{RESOLUTION_HINTS[c]}</span>
                </span>
              </label>
            ))}
          </fieldset>
          <div className="field">
            <label htmlFor="bulk-note">Note{code === "waived" ? " (required for a waiver)" : ""}</label>
            <textarea id="bulk-note" value={note} onChange={(e) => setNote(e.target.value)} />
          </div>
          {code === "waived" && (
            <p className={overCap ? "error-text" : "muted"}>
              {overCap
                ? `The total passes the 30-day waiver cap of ${cad(tol.data?.waiver_period_cap)}, so the whole batch goes to your controller.`
                : `Items above ${cad(tol.data?.waiver_limit)} each, or a batch that would pass the 30-day cap, go to your controller for approval.`}
            </p>
          )}
          {run.error && <p className="error-text">{errorText(run.error)}</p>}
        </>
      )}
      {res && (
        <>
          <p role="status">
            {count("resolved") + count("waived")} resolved, {count("pending_approval")} sent for approval, {count("skipped")} skipped, {count("failed")} failed.
          </p>
          <ul style={{ paddingLeft: 18 }}>
            {res.map((r) => (
              <li key={r.id}>
                {byId.get(r.id)?.doc_number} {typeWord(byId.get(r.id)?.type ?? "")}: {r.result === "pending_approval" ? "sent for approval" : r.result}
                {r.reason ? ` (${r.reason === "stale version" ? "changed by someone else" : r.reason})` : ""}
              </li>
            ))}
          </ul>
        </>
      )}
    </Dialog>
  );
}

/** B9: assign the selected cases to a member, or unassign them; who works on it, never a status. */
function BulkAssign({ chosen, members, me, onDone }: { chosen: ExceptionItem[]; members: Member[]; me: string; onDone: () => void }) {
  const qc = useQueryClient();
  const assign = useMutation({
    mutationFn: async (to: string) => {
      let changed = 0;
      for (const e of chosen) {
        await send("PUT", `/api/v1/exceptions/${e.id}/assignment`, { user_id: to === "none" ? null : to }, { ifMatch: e.version });
        changed += 1;
      }
      return { changed, to };
    },
    onSuccess: ({ changed, to }) => {
      qc.invalidateQueries({ queryKey: ["exceptions"] });
      const who = to === "none" ? "nobody" : to === me ? "you" : members.find((m) => m.user_id === to)?.name ?? "a member";
      toast(`${plural(changed, "exception")} assigned to ${who}.`);
      onDone();
    },
    onError: (err) => {
      qc.invalidateQueries({ queryKey: ["exceptions"] });
      toast(`Not all were assigned: ${errorText(err)}`);
    },
  });
  return (
    <label className="bulk-assign">
      <span className="sr-only">Assign the selected exceptions</span>
      <select value="" disabled={assign.isPending} onChange={(e) => e.target.value && assign.mutate(e.target.value)}>
        <option value="">Assign to…</option>
        <option value={me}>Me</option>
        {members
          .filter((m) => m.user_id !== me)
          .map((m) => (
            <option key={m.user_id} value={m.user_id}>
              {m.name ?? "Member"}
            </option>
          ))}
        <option value="none">Nobody (unassign)</option>
      </select>
    </label>
  );
}
