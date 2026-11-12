import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, errorText, get, send } from "../api/client";
import type { ExceptionItem, ExceptionPage, InvoiceDetail, InvoiceLine } from "../api/types";
import { useSession } from "../app/session";
import { Banner, ErrorState, Loading, StatusChip, toast, usePageTitle } from "../components/ui";
import { cad, compareDecimal, money, qty, toCents } from "../lib/decimal";
import { day } from "../lib/format";
import { CONTROLLER_ONLY_CODES, RESOLUTION_CODES, RESOLUTION_HINTS, SUB_REASONS, typeWord } from "../lib/words";
import { chipFor } from "./Exceptions";

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
  const fromUrl = params.get("from") ?? "/exceptions";
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
  return (
    <>
      <div className="page-head">
        <div>
          <nav className="crumbs" aria-label="Breadcrumb">
            <Link to={fromUrl}>Exception queue</Link> / <Link to="/invoices">Invoices</Link>
          </nav>
          <h1 ref={heading} tabIndex={-1}>
            {inv.doc_type === "credit_note" ? "Credit note" : "Invoice"} {inv.doc_number ?? "without number"}
            {line ? ` · line ${line.line_no}` : ""}
          </h1>
          <p className="lede">
            {inv.vendor_name ?? "Supplier not identified"} · {day(inv.doc_date)} · total {cad(inv.total)} ·{" "}
            {inv.qbo_bill ? `QuickBooks bill ${inv.qbo_bill.doc_number}: ${inv.qbo_bill.paid_status}` : "no QuickBooks bill found"}
          </p>
        </div>
        <div className="actions">
          {can("correct_extraction") && (
            <Link className="btn" to={`/invoices/${inv.id}/review`}>
              Edit extraction
            </Link>
          )}
          {inv.purchase_order_id && (
            <Link className="btn" to={`/purchase-orders/${inv.purchase_order_id}`}>
              Open purchase order
            </Link>
          )}
          <button className="btn" disabled={idx <= 0} onClick={() => go(order[idx - 1])}>
            Previous exception
          </button>
          <button className="btn" disabled={idx < 0 || idx >= order.length - 1} onClick={() => go(order[idx + 1])}>
            Next exception
          </button>
        </div>
      </div>
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
      {docExcs.length > 0 && (
        <Banner tone="warn">
          {docExcs.map((e) => (
            <p key={e.id}>
              {typeWord(e.type)}: {chipFor(e)}
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
            <h2 id="doc-h">Invoice</h2>
          </div>
          <div className="panel-body stack">
            {line && (
              <dl className="facts" aria-label={`Values read for line ${line.line_no}`}>
                <dt>Supplier code</dt>
                <dd>{line.supplier_item_code ?? "None"}</dd>
                <dt>Description</dt>
                <dd>{line.description ?? "None"}</dd>
                <dt>Quantity</dt>
                <dd className="num" style={{ textAlign: "left" }}>
                  {qty(line.qty)} {line.uom}
                </dd>
                <dt>Unit price</dt>
                <dd>{qty(line.unit_price)}</dd>
                <dt>Amount</dt>
                <dd>{cad(line.amount)}</dd>
              </dl>
            )}
            <Suspense fallback={<Loading label="Loading document" />}>
              <PdfViewer documentId={inv.document_id} label={`Invoice ${inv.doc_number ?? ""}`} />
            </Suspense>
          </div>
        </section>

        <section className="pane-po panel" aria-labelledby="po-h">
          <div className="panel-head">
            <h2 id="po-h">{po ? `PO ${po.po_number} · line ${po.line_no ?? ""}` : "Purchase order"}</h2>
          </div>
          <div className="panel-body">
            {po ? (
              <dl className="facts">
                <dt>Ordered</dt>
                <dd>
                  {qty(po.qty_ordered)} {po.uom}
                </dd>
                <dt>PO price</dt>
                <dd>{qty(po.unit_price)}</dd>
                <dt>Our item</dt>
                <dd>{[po.item_sku, po.item_name].filter(Boolean).join(" · ") || po.description}</dd>
                <dt>Alias</dt>
                <dd>
                  {line?.alias
                    ? `${line.alias.supplier_item_code} → ${po.item_sku ?? "item"}, ${line.alias.supplier_uom ?? ""} 1:${qty(line.alias.conversion_factor)} ${line.alias.item_uom ?? ""}`.replace(/\s+/g, " ")
                    : "None"}
                  {line?.alias && line.alias.status !== "active" && <div className="muted small">Alias {line.alias.status.replace(/_/g, " ")}</div>}
                </dd>
                <dt>Supplier</dt>
                <dd>{inv.vendor_name}</dd>
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

        <section className="pane-rec panel" aria-labelledby="rec-h">
          <div className="panel-head">
            <h2 id="rec-h">Receipts and history</h2>
          </div>
          <div className="table-wrap" style={{ border: 0 }}>
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
                      <div className="small muted">
                        {r.evidence_class} · {r.evidence_words}
                        {r.not_counted_reason ? `. ${r.not_counted_reason}` : ""}
                      </div>
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
            <div className="panel-body">
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
          {can("upload") && (
            <div className="panel-body" style={{ paddingTop: 0 }}>
              <Link to="/receiving">Attach receiving record</Link>
            </div>
          )}
        </section>

        <section className="pane-calc" aria-labelledby="calc-h">
          <div className={`workings ${passed ? "ok" : ""}`}>
            <h2 id="calc-h" className="sr-only">
              Calculation
            </h2>
            {line && (
              <div style={{ marginBottom: 8 }}>
                {lineChip(line, inv.exceptions)}{" "}
                {lineExcs.map((e) => (
                  <span key={e.id} style={{ marginLeft: 6 }}>
                    {typeWord(e.type)} {money(e.reported_amount ?? e.variance_amount) && `(${cad(e.reported_amount ?? e.variance_amount)})`}
                  </span>
                ))}
              </div>
            )}
            <p className="sentence">{m ? m.calculation : "This line has no match result yet."}</p>
            {absent && current?.sub_reason && <p>{ABSENT_TEXT[current.sub_reason]?.(amount ?? "0") ?? SUB_REASONS[current.sub_reason]}</p>}
            {m && (
              <dl className="ledger">
                <div>
                  <dt>Received to date</dt>
                  <dd>{qty(m.qty_received_cum) || "0"}</dd>
                </div>
                <div>
                  <dt>Invoiced to date</dt>
                  <dd>{qty(m.qty_invoiced_cum_net)}</dd>
                </div>
                <div>
                  <dt>Ordered</dt>
                  <dd>{qty(m.qty_ordered)}</dd>
                </div>
                <div>
                  <dt>PO price</dt>
                  <dd>{qty(m.po_unit_price)}</dd>
                </div>
                <div>
                  <dt>Invoice price</dt>
                  <dd>{qty(m.invoice_unit_price_po_uom)}</dd>
                </div>
              </dl>
            )}
            <p className="small muted" style={{ marginTop: 8 }}>
              Rule set v1. {line?.tolerance?.is_default_rule_set ? "Default tolerances." : "Account tolerances."}
            </p>
          </div>
        </section>
      </div>

      {current && (
        <div className="resolution-bar" role="region" aria-label="Resolution">
          <div className="inner">
            <div style={{ minWidth: 220 }}>
              <strong>{typeWord(current.type)}</strong> {chipFor(current)}
              <div className="small muted">{amount ? `Value ${cad(amount)}` : ""}</div>
            </div>
            {msg && (
              <p className={msg.tone === "error" ? "error-text" : "muted"} role="alert" style={{ flexBasis: "100%", margin: 0 }}>
                {msg.text}
              </p>
            )}
            {current.status === "open" && can("resolve") && (
              <>
                <div className="field" style={{ margin: 0 }}>
                  <label htmlFor="res-code">Resolve as</label>
                  <select id="res-code" value={code} onChange={(e) => setCode(e.target.value)}>
                    <option value="">Choose…</option>
                    {codes.map((c) => (
                      <option key={c} value={c}>
                        {RESOLUTION_CODES[c] ?? c}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="field" style={{ margin: 0, flex: 1, minWidth: 220 }}>
                  <label htmlFor="res-note">Note{code === "waived" ? " (required)" : ""}</label>
                  <input id="res-note" type="text" value={note} onChange={(e) => setNote(e.target.value)} />
                </div>
                <div>
                  {code && <div className="small muted">{needsApproval ? "Needs controller approval: the value is above your waiver limit." : RESOLUTION_HINTS[code]}</div>}
                  <button className="btn primary" disabled={!code || busy} onClick={resolve}>
                    {busy ? "Resolving…" : "Resolve and next"}
                  </button>
                </div>
              </>
            )}
            {current.status === "pending_approval" && (
              <>
                <span>Waiting for controller.</span>
                {can("resolve") && (
                  <button className="btn" disabled={busy} onClick={() => act("withdraw")}>
                    Withdraw request
                  </button>
                )}
              </>
            )}
            {(current.status === "resolved" || current.status === "waived") && (
              <>
                <span>
                  {current.status === "waived" ? "Waived" : `Resolved as ${RESOLUTION_CODES[current.resolution_code ?? ""] ?? current.resolution_code}`}
                  {current.resolution_note ? `: "${current.resolution_note}"` : ""}
                </span>
                {can("reopen") && (
                  <button className="btn" disabled={busy} onClick={() => act("reopen")}>
                    Reopen
                  </button>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </>
  );
}
