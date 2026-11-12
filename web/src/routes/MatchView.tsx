import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, errorText, get, send } from "../api/client";
import type { ExceptionItem, ExceptionPage, InvoiceDetail, InvoiceLine } from "../api/types";
import { useSession } from "../app/session";
import { Banner, ErrorState, Loading, NarrowNote, StatusChip, toast, usePageTitle } from "../components/ui";
import { cad, compareDecimal, money, price, qty, subtract, toCents } from "../lib/decimal";
import { day, safePath } from "../lib/format";
import { CONTROLLER_ONLY_CODES, RESOLUTION_CODES, RESOLUTION_HINTS, SUB_REASONS, typeWord, zeroCounted } from "../lib/words";
import { chipFor } from "./Exceptions";
import { ChevronLeft, ChevronRight, ClipboardList, Paperclip, PenLine } from "lucide-react";

const PdfViewer = lazy(() => import("../components/PdfViewer"));

const ABSENT_TEXT: Record<string, (amount: string) => string> = {
  not_received: (a) =>
    `Your receiving log covers this order and shows nothing for this line. ${cad(a)} was invoiced. This is listed as "not received" unless you attach receiving evidence or tie a credit note.`,
  no_evidence: () =>
    "No receiving evidence covers this purchase order. MatchDesk cannot say whether the goods arrived. Attach a warehouse record or a delivery document your receiver signed. If you know the goods never came, your controller can confirm that.",
  supplier_slip_only: () =>
    "This packing slip comes from the supplier and has no receiver's signature or count. It is shown for reference and is not counted as a receipt.",
};

function lineChip(l: InvoiceLine, excs: ExceptionItem[]) {
  if (l.stale) return <StatusChip status="stale" />;
  const mine = excs.filter((e) => e.invoice_line_id === l.id && e.status !== "auto_closed");
  if (mine.some((e) => e.type === "receipt_absent" && e.status === "open")) return <StatusChip status="receipt_absent" />;
  if (mine.some((e) => e.status === "open")) return <StatusChip status="exception" />;
  if (mine.some((e) => e.status === "pending_approval")) return <StatusChip status="pending_approval" />;
  if (l.status === "matched") return <StatusChip status="matched" />;
  if (mine.some((e) => e.status === "waived")) return <StatusChip status="waived" />;
  return <StatusChip status={l.status ?? "not_evaluated"} />;
}

function chipWord(e: ExceptionItem): string {
  return e.status === "waived" ? "waived" : `resolved: ${(RESOLUTION_CODES[e.resolution_code ?? ""] ?? "resolved").toLowerCase()}`;
}

/** Order of the queue the user came from, so "Resolve and next" follows it (App-flow S-09). */
function queueOrder(items: ExceptionItem[], from: URLSearchParams): ExceptionItem[] {
  const type = from.get("type");
  const sort = from.get("sort") ?? "value";
  const v = (e: ExceptionItem) => e.reported_amount ?? e.variance_amount ?? "0";
  return items
    .filter((e) => !type || e.type === type)
    .sort((a, b) => (sort === "age" ? (a.raised_at ?? "").localeCompare(b.raised_at ?? "") : sort === "vendor" ? (a.vendor_name ?? "").localeCompare(b.vendor_name ?? "") : compareDecimal(v(b), v(a))) || a.id.localeCompare(b.id));
}

/** S-09: invoice, purchase order, receipts and history, with the calculation in words. */
export function MatchViewPage() {
  const { invoiceId } = useParams();
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { can, role } = useSession();
  // Only a path inside the app: never a full URL or javascript: (review W1, same rule as ?next=).
  const fromUrl = safePath(params.get("from"), "/exceptions");
  const fromParams = new URLSearchParams(fromUrl.split("?")[1] ?? "");
  const q = useQuery({
    queryKey: ["invoice", invoiceId],
    queryFn: () => get<InvoiceDetail>(`/api/v1/invoices/${invoiceId}`),
    refetchInterval: (query) => (query.state.data?.stale ? 3000 : false),
  });
  const queueQuery = new URLSearchParams({ limit: "200", status: fromParams.get("status") ?? "open" });
  if (fromParams.get("vendor")) queueQuery.set("vendor_id", fromParams.get("vendor")!);
  const queue = useQuery({
    queryKey: ["exceptions", "queue-order", queueQuery.toString()],
    queryFn: () => get<ExceptionPage>(`/api/v1/exceptions?${queueQuery}`),
  });
  const tol = useQuery({ queryKey: ["tolerances"], queryFn: () => get<{ waiver_limit: string }>("/api/v1/tolerances") });
  const inv = q.data;
  usePageTitle("Match view", inv?.doc_number);
  const lineId = params.get("line") || inv?.lines.find((l) => inv.exceptions.some((e) => e.invoice_line_id === l.id && e.status === "open"))?.id || inv?.lines[0]?.id;
  const line = inv?.lines.find((l) => l.id === lineId);
  const lineExcs = (inv?.exceptions ?? []).filter((e) => e.invoice_line_id === lineId && e.status !== "auto_closed");
  const docExcs = (inv?.exceptions ?? []).filter((e) => !e.invoice_line_id && e.status !== "auto_closed");
  const excId = params.get("exc");
  const current =
    lineExcs.find((e) => e.id === excId) ??
    lineExcs.find((e) => e.status === "open" || e.status === "pending_approval") ??
    docExcs.find((e) => e.id === excId) ??
    lineExcs[0] ??
    docExcs.find((e) => e.status === "open");

  const heading = useRef<HTMLHeadingElement>(null);
  const [code, setCode] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: "warn" | "error" | "ok"; text: string } | null>(null);
  useEffect(() => {
    setCode("");
    setNote(""); // a note typed for one exception never carries to the next (review, minor)
    setMsg(null);
  }, [current?.id]);
  const loadedId = q.data?.id;
  useEffect(() => {
    // "Resolve and next" and route changes put focus on the exception's heading.
    if (loadedId) heading.current?.focus();
  }, [loadedId, lineId]);

  const order = useMemo(() => queueOrder(queue.data?.items ?? [], fromParams), [queue.data, fromUrl]); // eslint-disable-line react-hooks/exhaustive-deps
  const idx = current ? order.findIndex((e) => e.id === current.id) : -1;
  const go = (e: ExceptionItem | undefined) => {
    if (!e) {
      navigate(`${fromUrl.split("?")[0]}?${new URLSearchParams([...fromParams.entries()].filter(([k]) => k !== "sel"))}`);
      window.setTimeout(() => toast("That was the last exception in this queue."), 50);
      return;
    }
    navigate(`/invoices/${e.invoice_id}?line=${e.invoice_line_id ?? ""}&exc=${e.id}&from=${encodeURIComponent(fromUrl)}`);
  };
  const nextAfter = () => order.filter((e) => e.id !== current?.id)[Math.max(0, idx)] ?? undefined;

  async function resolve() {
    if (!current || !code) return;
    if (code === "waived" && !note.trim()) {
      setMsg({ tone: "error", text: "A waiver needs a note saying why." });
      return;
    }
    setBusy(true);
    setMsg(null);
    try {
      const r = await send<ExceptionItem & { result: string }>(
        "POST",
        `/api/v1/exceptions/${current.id}/resolutions`,
        { code, note: note || null },
        { ifMatch: current.version },
      );
      qc.invalidateQueries({ queryKey: ["exceptions"] });
      qc.invalidateQueries({ queryKey: ["invoice", invoiceId] });
      qc.invalidateQueries({ queryKey: ["approvals"] });
      toast(r.result === "pending_approval" ? "Sent to your controller for approval." : `Resolved: ${RESOLUTION_CODES[code] ?? code}.`);
      setNote("");
      const next = nextAfter();
      go(next && next.id !== current.id ? next : undefined);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        const cur = err.current as ExceptionItem | undefined;
        setMsg({
          tone: "warn",
          text: `Someone resolved this exception a moment ago${cur?.resolution_code ? ` as "${RESOLUTION_CODES[cur.resolution_code] ?? cur.resolution_code}"` : ""}. Your note is kept below if you want to add it.`,
        });
        q.refetch();
      } else setMsg({ tone: "error", text: errorText(err) });
    } finally {
      setBusy(false);
    }
  }

  async function act(path: "withdraw" | "reopen") {
    if (!current) return;
    setBusy(true);
    try {
      await send("POST", `/api/v1/exceptions/${current.id}/${path}`, undefined, { ifMatch: current.version });
      qc.invalidateQueries({ queryKey: ["exceptions"] });
      await q.refetch();
      toast(path === "withdraw" ? "Request withdrawn. The exception is open again." : "Reopened. History is kept.");
    } catch (err) {
      setMsg({ tone: "error", text: errorText(err) });
    } finally {
      setBusy(false);
    }
  }

  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorState error={q.error} retry={() => q.refetch()} />;
  if (!inv) return null;
  const m = line?.match;
  const po = line?.purchase_order;
  const codes = (current?.allowed_codes ?? []).filter((c) => role === "controller" || !CONTROLLER_ONLY_CODES.has(c));
  const amount = current?.reported_amount ?? current?.variance_amount ?? null;
  const needsApproval = code === "waived" && role !== "controller" && tol.data && (toCents(amount) ?? 0n) > (toCents(tol.data.waiver_limit) ?? 0n);
  const absent = current?.type === "receipt_absent";
  const passed = line?.status === "matched";
  const delta = (a: string | null | undefined, b: string | null | undefined) => (a && b ? subtract(a, b) : "");
  const qtyOver = m ? delta(m.qty_invoiced_cum_net, m.qty_received_cum || "0") : "";
  const orderedOver = m ? delta(m.qty_invoiced_cum_net, m.qty_ordered) : "";
  const priceOver = m ? delta(m.invoice_unit_price_po_uom, m.po_unit_price) : "";
  const tone = (d: string) => (!d ? "" : d.startsWith("-") || d === "0" ? "good" : "bad");
  const signed = (d: string, f: (v: string) => string = qty) => (!d ? "—" : d === "0" ? "0" : d.startsWith("-") ? `−${f(d.slice(1))}` : `+${f(d)}`);
  const uom = po?.uom ?? line?.uom ?? "";
  return (
    <>
      <div className="page-head">
        <div>
          <nav className="crumbs" aria-label="Breadcrumb">
            <ol>
              <li>
                <Link to={fromUrl}>Exception queue</Link>
              </li>
              <li>
                <ChevronRight size={14} aria-hidden="true" />
                <Link to="/invoices">Invoices</Link>
              </li>
            </ol>
          </nav>
          <h1 ref={heading} tabIndex={-1}>
            {inv.doc_type === "credit_note" ? "Credit note" : "Invoice"} {inv.doc_number ?? "without number"}
            {line ? ` · line ${line.line_no}` : ""}
          </h1>
          <p className="lede">
            {inv.vendor_name ?? "Supplier not identified"} · {day(inv.doc_date)} · total <span className="money">{cad(inv.total)}</span> ·{" "}
            {inv.qbo_bill ? `QuickBooks bill ${inv.qbo_bill.doc_number}: ${inv.qbo_bill.paid_status}` : "no QuickBooks bill found"}
          </p>
        </div>
        <div className="actions">
          {can("correct_extraction") && (
            <Link className="btn" to={`/invoices/${inv.id}/review`}>
              <PenLine size={16} aria-hidden="true" />
              Edit extraction
            </Link>
          )}
          {inv.purchase_order_id && (
            <Link className="btn" to={`/purchase-orders/${inv.purchase_order_id}`}>
              <ClipboardList size={16} aria-hidden="true" />
              Open purchase order
            </Link>
          )}
          <span className="pager">
            <button className="btn" disabled={idx <= 0} onClick={() => go(order[idx - 1])}>
              <ChevronLeft size={16} aria-hidden="true" />
              Previous exception
            </button>
            <button className="btn" disabled={idx < 0 || idx >= order.length - 1} onClick={() => go(order[idx + 1])}>
              Next exception
              <ChevronRight size={16} aria-hidden="true" />
            </button>
          </span>
        </div>
      </div>
      <NarrowNote />
      {inv.stale && (
        <Banner tone="draft" role="status">
          Matching… Inputs changed since the last result; the new result appears here without a reload.
        </Banner>
      )}
      {inv.verification_status === "failed" && (
        <Banner tone="draft">
          This document is waiting for extraction review. <Link to={`/invoices/${inv.id}/review`}>Review the extraction</Link>
        </Banner>
      )}
      {docExcs.length > 0 && !inv.stale && (
        <Banner tone="warn">
          {docExcs.map((e) => (
            <p key={e.id}>
              {typeWord(e.type)}
              {money(e.reported_amount ?? e.variance_amount) ? ` (${cad(e.reported_amount ?? e.variance_amount)})` : ""} {chipFor(e)}
            </p>
          ))}
        </Banner>
      )}
      <div className="lines-tabs" role="group" aria-label="Invoice lines">
        {inv.lines.map((l) => (
          <button
            key={l.id}
            aria-pressed={l.id === lineId}
            onClick={() => {
              const p = new URLSearchParams(params);
              p.set("line", l.id);
              p.delete("exc");
              setParams(p, { replace: true });
            }}
          >
            Line {l.line_no} {l.supplier_item_code ?? l.description ?? ""} {lineChip(l, inv.exceptions)}
          </button>
        ))}
      </div>
      <div className="match-grid">
        <section className="pane-doc panel" aria-labelledby="doc-h">
          <div className="panel-head">
            <h2 id="doc-h">Invoice document</h2>
            <span className="muted small">{inv.vendor_name}</span>
          </div>
          <div className="panel-body">
            <Suspense fallback={<Loading label="Loading document" />}>
              <PdfViewer documentId={inv.document_id} label={`Invoice ${inv.doc_number ?? ""}`} />
            </Suspense>
          </div>
        </section>

        <div className="pane-mid">
          <section className={`workings ${passed ? "ok" : ""}`} aria-labelledby="calc-h">
            <h2 id="calc-h" className="sr-only">
              Calculation
            </h2>
            {line && (
              <div className="w-head">
                {lineChip(line, inv.exceptions)}
                {lineExcs.map((e) => (
                  <span key={e.id} className="muted">
                    {typeWord(e.type)}{" "}
                    {e.status === "resolved" && e.resolution_code === "resolved_by_credit"
                      ? `(by ${qty(e.variance_qty)}, cleared by ${e.label ? "a QuickBooks vendor credit" : "a credit note"})`
                      : e.status === "resolved" || e.status === "waived"
                        ? `(${chipWord(e)})`
                        : zeroCounted(e)
                          ? `(by ${qty(e.variance_qty)})`
                          : money(e.reported_amount ?? e.variance_amount) && `(${cad(e.reported_amount ?? e.variance_amount)})`}
                  </span>
                ))}
              </div>
            )}
            <p className="sentence">{m ? m.calculation : "This line has no match result yet."}</p>
            {lineExcs.some(zeroCounted) && (
              <p className="small muted">
                The line&apos;s amount is counted once, under {typeWord(lineExcs.find((e) => !zeroCounted(e))?.type ?? "").toLowerCase() || "another exception"}; the other exceptions on
                it are listed with their quantity and add nothing to the total.
              </p>
            )}
            {absent && current?.sub_reason && <p>{ABSENT_TEXT[current.sub_reason]?.(amount ?? "0") ?? SUB_REASONS[current.sub_reason]}</p>}
            <p className="small muted" style={{ margin: 0 }}>
              Rule set v1. {line?.tolerance?.is_default_rule_set ? "Default tolerances." : "Account tolerances."}
            </p>
          </section>

          {m && line?.line_kind === "item" && (
            <section className="panel" aria-labelledby="cmp-h">
              <div className="panel-head">
                <h2 id="cmp-h">Line comparison</h2>
                <span className="muted small">Quantities in {uom || "PO units"}, to date across every document on this PO line</span>
              </div>
              <div className="table-wrap">
                <table className="compare">
                  <thead>
                    <tr>
                      <th scope="col">
                        <span className="sr-only">Measure</span>
                      </th>
                      <th scope="col" className="num">
                        Invoiced
                      </th>
                      <th scope="col" className="num">
                        Ordered
                      </th>
                      <th scope="col" className="num">
                        Received
                      </th>
                      <th scope="col" className="num">
                        Difference
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <th scope="row">Qty vs received</th>
                      <td className="num">{qty(m.qty_invoiced_cum_net)}</td>
                      <td className="num">{qty(m.qty_ordered)}</td>
                      <td className="num">{qty(m.qty_received_cum) || "0"}</td>
                      <td className={`num delta ${tone(qtyOver)}`}>{signed(qtyOver)}</td>
                    </tr>
                    <tr>
                      <th scope="row">Qty vs ordered</th>
                      <td className="num">{qty(m.qty_invoiced_cum_net)}</td>
                      <td className="num">{qty(m.qty_ordered)}</td>
                      <td className="num muted">—</td>
                      <td className={`num delta ${tone(orderedOver)}`}>{signed(orderedOver)}</td>
                    </tr>
                    <tr>
                      <th scope="row">Unit price</th>
                      <td className="num">{price(m.invoice_unit_price_po_uom)}</td>
                      <td className="num">{price(m.po_unit_price)}</td>
                      <td className="num muted">—</td>
                      <td className={`num delta ${tone(priceOver)}`}>{signed(priceOver, price)}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </section>
          )}

          <section className="panel" aria-labelledby="rec-h">
            <div className="panel-head">
              <h2 id="rec-h">Receipts and history</h2>
              {can("upload") && (
                <Link className="btn small" to="/receiving">
                  <Paperclip size={14} aria-hidden="true" />
                  Attach receiving record
                </Link>
              )}
            </div>
            <div className="table-wrap">
              <table className="compact">
                <caption className="sr-only">Receipts counted for this PO line</caption>
                <thead>
                  <tr>
                    <th scope="col">Date</th>
                    <th scope="col" className="num">
                      Qty
                    </th>
                    <th scope="col">Source</th>
                  </tr>
                </thead>
                <tbody>
                  {(line?.receipts ?? []).map((r) => (
                    <tr key={r.id} className={r.counts ? "" : "greyed"}>
                      <td>{day(r.received_date)}</td>
                      <td className="num">{qty(r.qty)}</td>
                      <td>
                        <Link to={`/receiving/imports/${r.receiving_import_id}`}>
                          {r.source_file} row {r.source_row}
                        </Link>
                        <span className="cell-sub">
                          Class {r.evidence_class} · {r.evidence_words}
                          {r.not_counted_reason ? `. ${r.not_counted_reason}` : ""}
                        </span>
                      </td>
                    </tr>
                  ))}
                  {(line?.receipts ?? []).length === 0 && (
                    <tr>
                      <td colSpan={3} className="muted">
                        No receiving record for this PO line.
                      </td>
                    </tr>
                  )}
                  {po?.qbo_billed_qty && (
                    <tr className="greyed">
                      <td colSpan={3}>Billed against PO in QuickBooks: {qty(po.qbo_billed_qty)}. Not counted as a receipt.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            {(line?.history ?? []).length > 0 && (
              <div className="panel-body" style={{ borderTop: "1px solid var(--border)" }}>
                <h3 style={{ marginBottom: 6 }}>Other documents on this PO line</h3>
                <ul style={{ margin: 0, paddingLeft: 18 }}>
                  {line!.history!.map((h, i) => (
                    <li key={i}>
                      {h.source === "qbo_bill" ? (
                        `QuickBooks ${h.doc_type === "credit_note" ? "vendor credit" : "bill"} ${h.doc_number ?? ""}, no document · ${qty(h.qty)}`
                      ) : (
                        <Link to={`/invoices/${h.invoice_id}`}>
                          {h.doc_type === "credit_note" ? "Credit note" : "Invoice"} {h.doc_number}
                        </Link>
                      )}{" "}
                      {h.source !== "qbo_bill" && `· ${day(h.doc_date)} · ${qty(h.qty)}`}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </section>
        </div>

        <aside className="pane-act" aria-label="Actions">
          {current && (
            <section className="panel action-panel resolution-bar" role="region" aria-label="Resolution">
              <div className="panel-head">
                <h2>{typeWord(current.type)}</h2>
                {chipFor(current)}
              </div>
              <div className="panel-body">
                <div>
                  <div className="muted small">{zeroCounted(current) ? "Adds nothing" : "Value"}</div>
                  <div className="amount">{zeroCounted(current) ? "CAD 0.00" : amount ? cad(amount) : "—"}</div>
                  {zeroCounted(current) && <div className="small muted">The line&apos;s amount is counted under another exception.</div>}
                </div>
                {msg && (
                  <p className={msg.tone === "error" ? "error-text" : "muted"} role="alert" style={{ margin: 0 }}>
                    {msg.text}
                  </p>
                )}
                {current.status === "open" && can("resolve") && (
                  <>
                    <div className="field">
                      <label htmlFor="res-code">Resolve as</label>
                      <select id="res-code" value={code} onChange={(e) => setCode(e.target.value)}>
                        <option value="">Choose…</option>
                        {codes.map((c) => (
                          <option key={c} value={c}>
                            {RESOLUTION_CODES[c] ?? c}
                          </option>
                        ))}
                      </select>
                      {code && <span className="hint">{needsApproval ? "Needs controller approval: the value is above your waiver limit." : RESOLUTION_HINTS[code]}</span>}
                    </div>
                    <div className="field">
                      <label htmlFor="res-note">Note{code === "waived" ? " (required)" : " (optional)"}</label>
                      <textarea id="res-note" rows={3} value={note} onChange={(e) => setNote(e.target.value)} />
                    </div>
                    <button className="btn primary block" disabled={!code || busy} onClick={resolve} title={!code ? "Choose how to resolve first" : undefined}>
                      {busy ? "Resolving…" : "Resolve and next"}
                    </button>
                    {!code && <span className="small muted">Choose how to resolve to continue.</span>}
                  </>
                )}
                {current.status === "open" && !can("resolve") && <p className="muted small">Your role can read this exception but not resolve it.</p>}
                {current.status === "pending_approval" && (
                  <>
                    <p style={{ margin: 0 }}>Waiting for controller.</p>
                    {can("resolve") && (
                      <button className="btn" disabled={busy} onClick={() => act("withdraw")}>
                        Withdraw request
                      </button>
                    )}
                  </>
                )}
                {(current.status === "resolved" || current.status === "waived") && (
                  <>
                    <p style={{ margin: 0 }}>
                      {current.status === "waived" ? "Waived" : `Resolved as ${RESOLUTION_CODES[current.resolution_code ?? ""] ?? current.resolution_code}`}
                      {current.resolution_note ? `: "${current.resolution_note}"` : ""}
                    </p>
                    {can("reopen") && (
                      <button className="btn" disabled={busy} onClick={() => act("reopen")}>
                        Reopen
                      </button>
                    )}
                  </>
                )}
              </div>
            </section>
          )}
          <section className="panel" aria-labelledby="po-h">
            <div className="panel-head">
              <h2 id="po-h">{po ? `PO ${po.po_number} · line ${po.line_no ?? ""}` : "Purchase order"}</h2>
            </div>
            <div className="panel-body">
              {line && (
                <dl className="facts" aria-label={`Values read for line ${line.line_no}`} style={{ marginBottom: 12 }}>
                  <dt>Supplier code</dt>
                  <dd>{line.supplier_item_code ?? "None"}</dd>
                  <dt>Description</dt>
                  <dd>{line.description ?? "None"}</dd>
                  <dt>Invoice qty</dt>
                  <dd>
                    {qty(line.qty)} {line.uom}
                  </dd>
                  <dt>Invoice price</dt>
                  <dd>{price(line.unit_price)}</dd>
                  <dt>Amount</dt>
                  <dd>{cad(line.amount)}</dd>
                </dl>
              )}
              {po ? (
                <dl className="facts">
                  <dt>Ordered</dt>
                  <dd>
                    {qty(po.qty_ordered)} {po.uom}
                  </dd>
                  <dt>PO price</dt>
                  <dd>{price(po.unit_price)}</dd>
                  <dt>Our item</dt>
                  <dd>{[po.item_sku, po.item_name].filter(Boolean).join(" · ") || po.description}</dd>
                  <dt>Alias</dt>
                  <dd>
                    {line?.alias
                      ? `${line.alias.supplier_item_code} → ${po.item_sku ?? "item"}, ${line.alias.supplier_uom ?? ""} 1:${qty(line.alias.conversion_factor)} ${line.alias.item_uom ?? ""}`.replace(/\s+/g, " ")
                      : "None"}
                    {line?.alias && line.alias.status !== "active" && <div className="muted small">Alias {line.alias.status.replace(/_/g, " ")}</div>}
                  </dd>
                </dl>
              ) : (
                <p className="muted">
                  {line?.line_kind !== "item" ? "A charge line (freight or fee): checked against the charge allowance." : "No purchase-order line was matched to this invoice line."}
                </p>
              )}
              <div className="actions" style={{ marginTop: 12 }}>
                {po && <Link to={`/purchase-orders/${po.id}`}>Open purchase order</Link>}
                {can("edit_alias") && line?.supplier_item_code && inv.vendor_id && (
                  <Link to={`/aliases?vendor=${inv.vendor_id}&code=${encodeURIComponent(line.supplier_item_code)}&description=${encodeURIComponent(line.description ?? "")}`}>
                    Add or fix alias
                  </Link>
                )}
              </div>
            </div>
          </section>
        </aside>
      </div>
    </>
  );
}
