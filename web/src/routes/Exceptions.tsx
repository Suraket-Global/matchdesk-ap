import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { errorText, get, send } from "../api/client";
import type { Batch, Coverage, ExceptionItem, ExceptionPage, Page, Vendor } from "../api/types";
import { useSession } from "../app/session";
import { useKeys } from "../app/shortcuts";
import { Dialog, Empty, ErrorState, Loading, NarrowNote, PageHead, StatusChip, usePageTitle } from "../components/ui";
import { cad, cadCents, compareDecimal, formatCents, money, qty, sumCents, toCents } from "../lib/decimal";
import { ageDays, ageText, lastMonth, monthName, monthRange, plural } from "../lib/format";
import { EXCEPTION_STATUS, RESOLUTION_CODES, RESOLUTION_HINTS, SUB_REASONS, typeWord, zeroCounted } from "../lib/words";

const STATUS_OPTIONS: [string, string][] = [
  ["open,pending_approval", "Open and pending approval"],
  ["open", "Open"],
  ["pending_approval", "Pending approval"],
  ["resolved", "Resolved"],
  ["waived", "Waived"],
  ["auto_closed", "Closed by a re-match"],
  ["open,pending_approval,resolved,waived,auto_closed", "All"],
];

export function chipFor(e: ExceptionItem) {
  if (e.status === "pending_approval") return <StatusChip status="pending_approval" />;
  if (e.status === "waived") return <StatusChip status="waived" />;
  if (e.status === "resolved") return <StatusChip status="resolved" word={RESOLUTION_CODES[e.resolution_code ?? ""] ? `Resolved: ${RESOLUTION_CODES[e.resolution_code ?? ""].toLowerCase()}` : "Resolved"} />;
  if (e.status === "auto_closed") return <StatusChip status="auto_closed" />;
  if (e.type === "receipt_absent") return <StatusChip status="receipt_absent" />;
  return <StatusChip status="exception" word={EXCEPTION_STATUS[e.status] ?? "Exception"} />;
}

function value(e: ExceptionItem): string | null {
  return e.reported_amount ?? e.variance_amount;
}

/** S-08: what needs a person, most valuable first. Filters, sort and selection live in the URL. */
export function ExceptionsPage() {
  usePageTitle("Exception queue");
  const { can } = useSession();
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const status = params.get("status") ?? "open,pending_approval";
  const type = params.get("type") ?? "";
  const vendor = params.get("vendor") ?? "";
  const min = params.get("min") ?? "";
  const max = params.get("max") ?? "";
  const sort = params.get("sort") ?? "value";
  const sel = params.get("sel");
  const setParam = (k: string, v: string) => {
    const p = new URLSearchParams(params);
    if (v) p.set(k, v);
    else p.delete(k);
    p.delete("sel");
    setParams(p);
  };
  const query = new URLSearchParams({ limit: "200", status });
  if (vendor) query.set("vendor_id", vendor);
  const list = useInfiniteQuery({
    queryKey: ["exceptions", "queue", status, vendor],
    queryFn: ({ pageParam }) => get<ExceptionPage>(`/api/v1/exceptions?${query}${pageParam ? `&cursor=${pageParam}` : ""}`),
    initialPageParam: "",
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    refetchInterval: 15_000,
  });
  const vendors = useQuery({ queryKey: ["vendors"], queryFn: () => get<Page<Vendor>>("/api/v1/vendors") });
  const month = lastMonth();
  // Live coverage for the test month, from the current results; no report draft needed (review W3).
  const coverage = useQuery({
    queryKey: ["coverage", month],
    queryFn: () => get<Coverage>(`/api/v1/coverage?period_start=${monthRange(month).start}&period_end=${monthRange(month).end}`),
    refetchInterval: 15_000,
  });
  const absentAll = useQuery({
    queryKey: ["exceptions", "absent"],
    queryFn: () => get<ExceptionPage>("/api/v1/exceptions?limit=200&type=receipt_absent&status=open,pending_approval,resolved"),
  });
  const batches = useQuery({ queryKey: ["batches"], queryFn: () => get<Page<Batch>>("/api/v1/intake/batches?limit=200") });

  const all = useMemo(() => (list.data?.pages ?? []).flatMap((p) => p.items), [list.data]);
  const counters = list.data?.pages[0]?.type_counters ?? {};
  const rows = useMemo(() => {
    let r = all.filter((e) => !type || e.type === type);
    if (min) r = r.filter((e) => compareDecimal(value(e) ?? "0", min) >= 0);
    if (max) r = r.filter((e) => compareDecimal(value(e) ?? "0", max) <= 0);
    const by = (a: ExceptionItem, b: ExceptionItem) =>
      sort === "age"
        ? (ageDays(b.raised_at) ?? 0) - (ageDays(a.raised_at) ?? 0)
        : sort === "vendor"
          ? (a.vendor_name ?? "").localeCompare(b.vendor_name ?? "")
          : compareDecimal(value(b) ?? "0", value(a) ?? "0");
    return [...r].sort((a, b) => by(a, b) || a.id.localeCompare(b.id));
  }, [all, type, min, max, sort]);

  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [focus, setFocus] = useState(-1);
  const rowRefs = useRef<(HTMLTableRowElement | null)[]>([]);
  useEffect(() => {
    // Returning from the match view: put focus and the selected row back.
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

  // Coverage strip (design.md 3): live figures for the test month and the open receipt-absent lines.
  // One denominator (invoiced PO item lines) for every percentage on it (review W2).
  const cov = coverage.data && coverage.data.item_lines > 0 ? coverage.data : null;
  const pctText = (v: string | null | undefined) => `${money(v).replace(/\.00$/, "")}%`;
  const viaA = cov ? formatCents((toCents(cov.receipt_coverage_pct) ?? 0n) - (toCents(cov.coverage_class_b_pct) ?? 0n)) : "0";
  const absent = (absentAll.data?.items ?? []).filter((e) => e.status !== "auto_closed");
  const notReceived = absent.filter((e) => e.sub_reason === "not_received");
  const unverified = absent.filter((e) => e.sub_reason !== "not_received");
  const processed = (batches.data?.items ?? []).reduce((n, b) => n + b.totals.ready + b.totals["needs review"], 0);

  return (
    <>
      <PageHead
        title="Exception queue"
        lede={can("resolve") ? "Keys: J and K move, Enter opens, X selects." : "Read only for your role."}
        actions={
          <Link className="btn" to="/reports">
            Back-test report
          </Link>
        }
      />
      <NarrowNote />
      <div className="coverage" role="note">
        <span>
          Receipt coverage <strong>{cov ? pctText(cov.receipt_coverage_pct) : "not measured yet"}</strong>
          {cov && ` of invoiced PO lines (warehouse log ${pctText(viaA)}, signed delivery documents ${pctText(cov.coverage_class_b_pct)})`}
        </span>
        {cov && (
          <span className="meter" aria-hidden="true">
            <span className="a" style={{ width: `${viaA}%` }} />
            <span className="b" style={{ width: `${cov.coverage_class_b_pct}%` }} />
          </span>
        )}
        {cov && <span>Complete warehouse log covers {pctText(cov.coverage_class_a_pct)}</span>}
        <span>
          Not received: <strong>{plural(notReceived.length, "line")}, {cadCents(sumCents(notReceived.map(value)))}</strong>
        </span>
        <span>
          Unverified: <strong>{plural(unverified.length, "line")}, {cadCents(sumCents(unverified.map(value)))}</strong>
        </span>
        <Link to="/receiving">Receiving imports</Link>
      </div>
      <div className="counters" role="group" aria-label="Exceptions by type">
        <button className="counter" aria-pressed={!type} onClick={() => setParam("type", "")}>
          <span className="n">{Object.values(counters).reduce((a, b) => a + b, 0)}</span>
          <span className="t">All types</span>
        </button>
        {Object.entries({ ...(type ? { [type]: 0 } : {}), ...counters })
          .sort((a, b) => b[1] - a[1])
          .map(([t, n]) => (
            <button key={t} className="counter" aria-pressed={type === t} onClick={() => setParam("type", type === t ? "" : t)}>
              <span className="n">{n}</span>
              <span className="t">{typeWord(t)}</span>
            </button>
          ))}
      </div>
      <form className="inline-form panel panel-body" style={{ marginBottom: 12 }} onSubmit={(e) => e.preventDefault()} aria-label="Filters">
        <div className="field">
          <label htmlFor="f-status">Status</label>
          <select id="f-status" value={status} onChange={(e) => setParam("status", e.target.value === "open,pending_approval" ? "" : e.target.value)}>
            {STATUS_OPTIONS.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="f-vendor">Supplier</label>
          <select id="f-vendor" value={vendor} onChange={(e) => setParam("vendor", e.target.value)}>
            <option value="">All suppliers</option>
            {(vendors.data?.items ?? []).map((v) => (
              <option key={v.id} value={v.id}>
                {v.name}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="f-min">Value from (CAD)</label>
          <input id="f-min" inputMode="decimal" size={8} defaultValue={min} onBlur={(e) => setParam("min", e.target.value.trim())} />
        </div>
        <div className="field">
          <label htmlFor="f-max">Value to (CAD)</label>
          <input id="f-max" inputMode="decimal" size={8} defaultValue={max} onBlur={(e) => setParam("max", e.target.value.trim())} />
        </div>
        <div className="field">
          <label htmlFor="f-sort">Sort</label>
          <select id="f-sort" value={sort} onChange={(e) => setParam("sort", e.target.value === "value" ? "" : e.target.value)}>
            <option value="value">Highest value first</option>
            <option value="age">Oldest first</option>
            <option value="vendor">Supplier</option>
          </select>
        </div>
        {can("resolve") && (
          <button type="button" className="btn primary" disabled={!chosen.length || chosenTypes.size !== 1} onClick={() => setBulkOpen(true)}>
            Resolve {chosen.length ? plural(chosen.length, "item") : ""} as…
          </button>
        )}
        {chosenTypes.size > 1 && <span className="error-text">Bulk resolve works on one type at a time.</span>}
      </form>
      <p className="sr-only" role="status" aria-live="polite">
        {list.isFetching ? "" : `${plural(rows.length, "exception")} shown.`}
      </p>
      {list.isLoading && <Loading label="Loading exceptions" />}
      {list.error && <ErrorState error={list.error} retry={() => list.refetch()} />}
      {list.data && rows.length === 0 && (
        <div className="panel">
          {processed === 0 ? (
            <Empty title="Nothing processed yet">
              <p>
                Upload the month's invoices first. <Link to="/intake">Go to invoice intake</Link>
              </p>
            </Empty>
          ) : (
            <Empty
              title={
                type
                  ? `No ${status.startsWith("open") ? "open " : ""}exceptions of type "${typeWord(type)}".`
                  : status.startsWith("open") && !vendor && !min && !max
                    ? `No open exceptions for ${monthName(month)}.`
                    : "No exceptions match these filters."
              }
            >
              <p>
                {type || vendor || min || max ? (
                  <button type="button" className="btn small" onClick={() => setParams(new URLSearchParams(status === "open,pending_approval" ? {} : { status }))}>
                    Clear the filters
                  </button>
                ) : (
                  <Link to="/reports">Open the back-test report</Link>
                )}
              </p>
            </Empty>
          )}
        </div>
      )}
      {rows.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                {can("resolve") && (
                  <th scope="col">
                    <span className="sr-only">Select</span>
                  </th>
                )}
                <th scope="col">Type</th>
                <th scope="col">Supplier</th>
                <th scope="col">Document</th>
                <th scope="col">PO</th>
                <th scope="col">Item</th>
                <th scope="col" className="num">
                  Variance qty
                </th>
                <th scope="col" className="num" aria-sort={sort === "value" ? "descending" : "none"}>
                  Value (CAD)
                </th>
                <th scope="col" aria-sort={sort === "age" ? "descending" : "none"}>
                  Age
                </th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((e, i) => (
                <tr
                  key={e.id}
                  ref={(el) => (rowRefs.current[i] = el)}
                  tabIndex={0}
                  className={`row-link ${selected.has(e.id) ? "selected" : ""} ${focus === i ? "focused" : ""}`}
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
                    <td>
                      <input type="checkbox" aria-label={`Select ${typeWord(e.type)} on ${e.doc_number}`} checked={selected.has(e.id)} onChange={() => toggle(e.id)} />
                    </td>
                  )}
                  <td>
                    <strong>{typeWord(e.type)}</strong>
                    {e.sub_reason && <div className="muted small">{SUB_REASONS[e.sub_reason] ?? e.sub_reason}</div>}
                  </td>
                  <td>{e.vendor_name ?? <span className="muted">Not identified</span>}</td>
                  <td>
                    <Link to={hrefFor(e)} onClick={(ev) => { ev.preventDefault(); open(e); }}>
                      {e.doc_number ?? "No number"}
                    </Link>
                    {e.line_no ? <span className="muted"> line {e.line_no}</span> : null}
                  </td>
                  <td>{e.po_number}</td>
                  <td>{e.supplier_item_code}</td>
                  <td className="num">{qty(e.variance_qty)}</td>
                  <td className="num">
                    {money(value(e))}
                    {zeroCounted(e) && <div className="small muted">counted under another exception</div>}
                  </td>
                  <td>{ageText(e.raised_at)}</td>
                  <td>{chipFor(e)}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <td colSpan={can("resolve") ? 7 : 6}>{plural(rows.length, "exception")}</td>
                <td className="num">{formatCents(sumCents(rows.map(value)))}</td>
                <td colSpan={2} />
              </tr>
            </tfoot>
          </table>
        </div>
      )}
      {list.hasNextPage && (
        <button className="btn" style={{ marginTop: 12 }} onClick={() => list.fetchNextPage()} disabled={list.isFetchingNextPage}>
          Load more
        </button>
      )}
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
  const [code, setCode] = useState(codes[0] ?? "");
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
