import { lazy, Suspense, useEffect, useRef, useState, type ReactNode } from "react";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, errorText, get, send } from "../api/client";
import type { ExceptionItem, InvoiceDetail, InvoiceLine, Neighbour, Neighbours, Page, Vendor } from "../api/types";
import { usePeriod } from "../app/period";
import { apiQuery, describeScope, readScope } from "../lib/queue";
import { useSession } from "../app/session";
import { Banner, ErrorState, Loading, StatusChip, toast, usePageTitle } from "../components/ui";
import { cad, money, price, qty, subtract, toCents } from "../lib/decimal";
import { day, safePath } from "../lib/format";
import { CONTROLLER_ONLY_CODES, RESOLUTION_CODES, RESOLUTION_HINTS, SUB_REASONS, typeWord, zeroCounted } from "../lib/words";
import { chipFor } from "./Exceptions";
import { Assignee, ControllerDecision, decidedByController, useExceptionDetail } from "./MatchDecisions";
import { ArrowLeft, ChevronLeft, ChevronRight, ClipboardList, Paperclip, PenLine } from "lucide-react";

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

/** What a resolution does to the report and the queue, in words, before it is submitted (B8). */
function consequence(code: string, amount: string | null, needsApproval: boolean): string {
  const a = amount && amount !== "0.00" ? cad(amount) : "The amount";
  switch (code) {
    case "confirmed_overbilling":
      return `${a} stays in the back-test report as a finding the supplier owes. The exception closes for the queue.`;
    case "confirmed_short_shipment":
      return `${a} stays in the report as a finding: fewer goods came than were invoiced.`;
    case "source_corrected":
      return "The exception closes and nothing is reported. Correct the document or the receiving record too, or the next match raises it again.";
    case "waived":
      return needsApproval
        ? `${a} is above your waiver limit, so this goes to your controller. The exception stays in the queue as pending approval until they decide.`
        : `${a} is accepted and listed under waived items in the report. A waiver never lowers the refund calculation.`;
    case "confirmed_not_received":
      return `${a} is reported as not received.`;
    case "resolved_by_credit":
      return "Closes against a credit note. Nothing is reported for this line.";
    case "confirmed_duplicate":
      return `This invoice is reported as a duplicate; ${a.toLowerCase() === "the amount" ? "its amount" : a} is a finding.`;
    case "not_a_duplicate":
      return "Both invoices stay and are matched as separate documents.";
    default:
      return RESOLUTION_HINTS[code] ?? "";
  }
}

/** The calculation of one exception as a ledger line, each figure from the stored match result, the
 * received figure linked to the exact receiving row (B8; FF-1003 is the acceptance example). */
function Ledger({ line, exc, here }: { line: InvoiceLine; exc: ExceptionItem; here: string }) {
  const m = line.match!;
  const po = line.purchase_order;
  const unit = po?.uom ?? line.uom ?? "";
  const amount = exc.reported_amount ?? exc.variance_amount;
  const counting = (line.receipts ?? []).filter((r) => r.counts);
  const rowLink = (r: (typeof counting)[number]) => `/receiving/imports/${r.receiving_import_id}?row=${r.source_row}&from=${encodeURIComponent(here)}`;
  const received = m.qty_received_cum || "0";
  const cells: { k: string; v: string; note?: ReactNode; tone?: string; op?: string }[] = [];
  const u = (v: string | null | undefined) => `${qty(v) || "0"}${unit ? ` ${unit}` : ""}`;
  if (exc.type === "qty_over_received" && m.qty_invoiced_cum_net) {
    cells.push({ k: "Billed to date", v: u(m.qty_invoiced_cum_net) });
    cells.push({
      k: "Received",
      v: u(received),
      op: "−",
      note:
        counting.length === 1 ? (
          <Link to={rowLink(counting[0])}>
            {counting[0].source_file} row {counting[0].source_row}
          </Link>
        ) : counting.length > 1 ? (
          <a href="#rec-h">{counting.length} receiving rows</a>
        ) : null,
    });
    cells.push({ k: "Excess", v: u(subtract(m.qty_invoiced_cum_net, received)), op: "=", tone: "bad" });
    cells.push({ k: "Unit price", v: cad(m.po_unit_price), op: "×" });
  } else if (exc.type === "qty_over_ordered" && m.qty_invoiced_cum_net && m.qty_ordered) {
    cells.push({ k: "Billed to date", v: u(m.qty_invoiced_cum_net) });
    cells.push({ k: "Ordered", v: u(m.qty_ordered), op: "−", note: po ? `PO ${po.po_number} line ${po.line_no ?? ""}` : null });
    cells.push({ k: "Above the order", v: u(subtract(m.qty_invoiced_cum_net, m.qty_ordered)), op: "=", tone: "bad" });
  } else if (exc.type === "price_variance" && m.invoice_unit_price_po_uom && m.po_unit_price) {
    cells.push({ k: "Invoice price", v: price(m.invoice_unit_price_po_uom) });
    cells.push({ k: "PO price", v: price(m.po_unit_price), op: "−", note: po ? `PO ${po.po_number}` : null });
    cells.push({ k: "Difference", v: price(subtract(m.invoice_unit_price_po_uom, m.po_unit_price)), op: "=", tone: "bad" });
    cells.push({ k: "Quantity", v: u(line.qty), op: "×" });
  } else if (exc.type === "receipt_absent") {
    cells.push({ k: "Billed to date", v: u(m.qty_invoiced_cum_net ?? line.qty) });
    cells.push({ k: "Received", v: u("0"), op: "−", note: "No counting receiving record", tone: "warn" });
  } else return null;
  return (
    <section className="ledger" aria-label="Calculation in figures">
      {cells.map((c) => (
        <div key={c.k} className={`l-cell ${c.tone ?? ""}`}>
          {c.op && (
            <span className="op" aria-hidden="true">
              {c.op}
            </span>
          )}
          <span className="k">{c.k}</span>
          <span className="v num">{c.v}</span>
          {c.note && <span className="n">{c.note}</span>}
        </div>
      ))}
      <div className={`l-cell total ${zeroCounted(exc) ? "" : "bad"}`}>
        <span className="op" aria-hidden="true">
          =
        </span>
        <span className="k">{zeroCounted(exc) ? "Adds nothing" : "Exposure"}</span>
        <span className="v num">{zeroCounted(exc) ? "CAD 0.00" : cad(amount)}</span>
        <span className="n">{typeWord(exc.type)}</span>
      </div>
    </section>
  );
}

function crumbFor(path: string): string {
  if (path.startsWith("/invoices")) return "Invoices";
  if (path.startsWith("/intake")) return "Intake batch";
  if (path.startsWith("/reports")) return "Back-test report";
  if (path.startsWith("/purchase-orders")) return "Purchase order";
  return "Exception queue";
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

  const detail = useExceptionDetail(current?.id);
  // B8: previous and next come from the server, over the same scope and order as the queue opened.
  const { month } = usePeriod();
  const fromQueue = fromUrl.startsWith("/exceptions");
  const scope = readScope(fromParams);
  const scopeQuery = apiQuery(scope, month).toString();
  const near = useQuery({
    queryKey: ["exceptions", "neighbours", current?.id, scopeQuery],
    queryFn: () => get<Neighbours>(`/api/v1/exceptions/${current!.id}/neighbours?${scopeQuery}`),
    enabled: !!current && fromQueue,
  });
  const vendors = useQuery({ queryKey: ["vendors"], queryFn: () => get<Page<Vendor>>("/api/v1/vendors"), enabled: fromQueue && !!scope.vendor });
  const scopeWords = fromQueue ? describeScope(scope, month, (vendors.data?.items ?? []).find((v) => v.id === scope.vendor)?.name) : "";
  const location = useLocation();
  const here = location.pathname + location.search;
  const submitting = useRef(false);
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

  const go = (e: Neighbour | null | undefined) => {
    if (!e) {
      navigate(fromUrl);
      window.setTimeout(() => toast("That was the last exception in this queue."), 50);
      return;
    }
    navigate(`/invoices/${e.invoice_id}?line=${e.invoice_line_id ?? ""}&exc=${e.id}&from=${encodeURIComponent(fromUrl)}`);
  };
  async function resolve() {
    if (!current || !code || submitting.current) return; // one decision per click (B8)
    if (code === "waived" && !note.trim()) {
      setMsg({ tone: "error", text: "A waiver needs a note saying why." });
      return;
    }
    submitting.current = true;
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
      if (!fromQueue) {
        await q.refetch();
        return;
      }
      // The next exception after this one's place in the order, even though it has left the set.
      const after = await get<Neighbours>(`/api/v1/exceptions/${current.id}/neighbours?${scopeQuery}`).catch(() => null);
      go(after?.next);
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
      submitting.current = false;
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
      <div className="page-head match-head">
        <div>
          <nav className="crumbs" aria-label="Breadcrumb">
            <ol>
              <li>
                {/* The list the person came from, named with its scope so they can tell which queue (B8). */}
                <Link to={fromUrl} className="back-link">
                  <ArrowLeft size={14} aria-hidden="true" />
                  <span>
                    {crumbFor(fromUrl)}
                    {scopeWords && <span className="muted">{`: ${scopeWords}`}</span>}
                  </span>
                </Link>
              </li>
            </ol>
          </nav>
          <h1 ref={heading} tabIndex={-1}>
            {inv.doc_type === "credit_note" ? "Credit note" : "Invoice"} {inv.doc_number ?? "without number"}
            {line ? <span className="h-sub"> line {line.line_no}</span> : null}
          </h1>
          <p className="lede">
            {inv.vendor_name ?? "Supplier not identified"}, dated {day(inv.doc_date)}, total <span className="money">{cad(inv.total)}</span>.{" "}
            {inv.qbo_bill ? `QuickBooks bill ${inv.qbo_bill.doc_number}: ${inv.qbo_bill.paid_status}.` : "No QuickBooks bill found."}
          </p>
        </div>
        <div className="actions">
          {fromQueue && current && (
            <span className="pager" role="group" aria-label="Move through the queue">
              <button className="btn" disabled={!near.data?.previous} onClick={() => go(near.data?.previous)}>
                <ChevronLeft size={16} aria-hidden="true" />
                Previous<span className="pager-word"> exception</span>
              </button>
              <span className="pos small muted" aria-live="polite">
                {near.data?.position ? `${near.data.position} of ${near.data.total}` : near.data ? `${near.data.total} left` : ""}
              </span>
              <button className="btn" disabled={!near.data?.next} onClick={() => go(near.data?.next)}>
                Next<span className="pager-word"> exception</span>
                <ChevronRight size={16} aria-hidden="true" />
              </button>
            </span>
          )}
        </div>
      </div>
      {line && m && current && <Ledger line={line} exc={current} here={here} />}
      {inv.stale && (
        <Banner tone="draft" role="status">
          {inv.lines.every((l) => l.result_status === null)
            ? "Matching… The result appears here without a reload."
            : "Matching… Inputs changed since the last result; the new result appears here without a reload."}
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
              <PdfViewer documentId={inv.document_id} label={`Invoice ${inv.doc_number ?? ""}`} initialPage={line?.page_no ?? 1} />
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
                {lineExcs.map((e) => (
                  <span key={e.id} className="muted">
                    {typeWord(e.type)}{" "}
                    {e.status === "resolved" && e.resolution_code === "resolved_by_credit"
                      ? e.label?.includes("decided by the controller")
                        ? `(${e.label})`
                        : `(by ${qty(e.variance_qty)}, cleared by ${e.label ? "a QuickBooks vendor credit" : "a credit note"})`
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

          {m && line?.line_kind === "item" && m.qty_invoiced_cum_net && (
            <section className="panel" aria-labelledby="cmp-h">
              <div className="panel-head">
                <h2 id="cmp-h">Line comparison</h2>
                <span className="muted small">Quantities in {uom || "PO units"}, to date across every document on this PO line</span>
              </div>
              <div className="table-wrap" tabIndex={0} role="region" aria-label="Line comparison table">
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
            <div className="table-wrap" tabIndex={0} role="region" aria-label="Receipts table">
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
                        <Link to={`/receiving/imports/${r.receiving_import_id}?row=${r.source_row}&from=${encodeURIComponent(here)}`}>
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
                {current.status !== "open" && chipFor(current)}
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
                {(current.status === "open" || current.status === "pending_approval") && (
                  <Assignee exc={current} detail={detail.data} />
                )}
                {decidedByController(current) && <ControllerDecision exc={current} detail={detail.data} onDone={() => void q.refetch()} />}
                {current.status === "open" && can("resolve") && !decidedByController(current) && (
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
                    {code && (
                      <div className="consequence" role="note" aria-label="What this decision does">
                        <strong>What happens</strong>
                        <p>{consequence(code, amount, !!needsApproval)}</p>
                      </div>
                    )}
                    <button className="btn primary block" disabled={!code || busy} onClick={resolve} title={!code ? "Choose how to resolve first" : undefined}>
                      {busy ? "Resolving…" : fromQueue ? (near.data && !near.data.next ? "Resolve and return to the queue" : "Resolve and next") : "Resolve"}
                    </button>
                    {!code && <span className="small muted">Choose how to resolve to continue.</span>}
                  </>
                )}
                {current.status === "open" && !can("resolve") && !decidedByController(current) && <p className="muted small">Your role can read this exception but not resolve it.</p>}
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
                    {current.label && current.resolution_code === "resolved_by_credit" && <p className="muted small" style={{ margin: 0 }}>{current.label}</p>}
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
          {inv.review?.inconsistent_note && (
            <Banner tone="warn">
              <p>
                Confirmed as not adding up: <q>{inv.review.inconsistent_note}</q>
              </p>
            </Banner>
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
                {po && (
                  <Link to={`/purchase-orders/${po.id}`}>
                    <ClipboardList size={14} aria-hidden="true" /> Open purchase order
                  </Link>
                )}
                {can("correct_extraction") && (
                  <Link to={`/invoices/${inv.id}/review`}>
                    <PenLine size={14} aria-hidden="true" /> Edit extraction
                  </Link>
                )}
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
