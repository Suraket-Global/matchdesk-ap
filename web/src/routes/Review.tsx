import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, errorText, get, send } from "../api/client";
import type { FieldSource, InvoiceDetail, InvoiceSummary, Page, Review, Vendor } from "../api/types";
import { Banner, Dialog, ErrorState, Loading, PageHead, StatusChip, toast, usePageTitle } from "../components/ui";
import { failedChecks, FIELD_RULES, type LineValues } from "../lib/checks";
import { formatCents, numberError, plainNumber, sumCents, toCents } from "../lib/decimal";
import { qty } from "../lib/decimal";
import { time, when } from "../lib/format";
import { DeleteDocument } from "./DeleteDocument";
import { RemovedBanner } from "./RemovedBanner";

const PdfViewer = lazy(() => import("../components/PdfViewer"));

type Header = Record<string, string>;
type EditLine = LineValues & { supplier_item_code: string; description: string; uom: string };
const HEADER_FIELDS: { key: string; label: string; source?: string; type?: string }[] = [
  { key: "doc_type", label: "Document type" },
  { key: "vendor_id", label: "Supplier", source: "vendor_name" },
  { key: "doc_number", label: "Document number" },
  { key: "doc_date", label: "Date", type: "date" },
  { key: "po_number_read", label: "PO number", source: "po_number" },
  { key: "references_invoice_number", label: "Credit note for invoice" },
  { key: "currency", label: "Currency" },
  { key: "subtotal", label: "Subtotal" },
  { key: "tax_total", label: "Tax" },
  { key: "total", label: "Total" },
];
const LINE_FIELDS = ["supplier_item_code", "description", "qty", "uom", "unit_price", "amount"] as const;
const LINE_LABELS: Record<string, string> = {
  supplier_item_code: "Supplier code",
  description: "Description",
  qty: "Qty",
  uom: "Unit",
  unit_price: "Unit price",
  amount: "Amount",
};

function fromReview(r: Review): { header: Header; lines: EditLine[] } {
  const header: Header = {};
  for (const f of HEADER_FIELDS) header[f.key] = String(r.fields[f.key] ?? "");
  const lines = r.line_fields.map((l) => ({
    line_no: l.line_no,
    supplier_item_code: l.supplier_item_code ?? "",
    description: l.description ?? "",
    qty: qty(l.qty),
    uom: l.uom ?? "",
    unit_price: qty(l.unit_price),
    amount: l.amount ?? "",
    line_kind: l.line_kind,
  }));
  return { header, lines };
}

function Provenance({ src, changed, value, onHistory }: { src?: FieldSource; changed?: boolean; value?: string | null; onHistory: () => void }) {
  if (src?.source === "edited" || changed)
    return (
      <span>
        <span className="tag edited">edited</span>{" "}
        <button type="button" className="btn small ghost" onClick={onHistory}>
          History
        </button>
      </span>
    );
  // "read" only for a value the reader actually found (B6 review minor: an empty or unidentified
  // field said "read").
  if (src?.source === "read" && (value ?? "") !== "") return <span className="tag">read</span>;
  return <span className="tag muted">not read</span>;
}

/** B8: the printed total, the calculated total, the value in the field and the result, side by side,
 * so the clerk sees what a correction changes before confirming (FF-1006). B10 (outside QA item 12):
 * when they agree it is one compact line; on a mismatch it opens to both amounts, the exact
 * difference, the field to correct and where each amount comes from. */
function TotalCheck({ printed, edited, tax, lines }: { printed: string; edited: string; tax: string; lines: string[] }) {
  const calc = sumCents(lines.map((l) => plainNumber(l))) + (toCents(plainNumber(tax) || "0") ?? 0n);
  const field = toCents(plainNumber(edited));
  const read = toCents(plainNumber(printed));
  const agrees = field !== null && field === calc;
  const changed = field !== null && read !== null && field !== read;
  if (agrees)
    return (
      <section className="total-check compact ok" aria-label="Total check" data-testid="total-check">
        <p role="status">
          <strong>Total agrees:</strong> <span className="num">CAD {formatCents(field)}</span> = lines + tax
          {changed ? ` (you changed it from ${formatCents(read!)})` : read !== null ? ", as printed" : ""}.
        </p>
      </section>
    );
  const diff = field === null ? null : field > calc ? field - calc : calc - field;
  return (
    <section className="total-check open" aria-label="Total check" data-testid="total-check">
      <div>
        <span className="k">Printed on the document</span>
        <span className="v num">{read === null ? "Not read" : formatCents(read)}</span>
        <span className="n">Source: the document as read</span>
      </div>
      <div>
        <span className="k">Lines + tax</span>
        <span className="v num">{formatCents(calc)}</span>
        <span className="n">Source: the line amounts and the tax field below</span>
      </div>
      <div className={changed ? "edited" : ""}>
        <span className="k">Total field{changed ? " (edited)" : ""}</span>
        <span className="v num">{field === null ? "Empty" : formatCents(field)}</span>
        <span className="n">Source: {changed ? "your correction" : "the value read"}</span>
      </div>
      <div className="bad" role="status">
        <span className="k">Result</span>
        <span className="v">{field === null ? "No total" : `Differs by ${formatCents(diff!)}`}</span>
        <span className="n">
          {field === null
            ? "Fill in the Total field."
            : `Check the Total field, the Tax field or a line amount: the total is ${field > calc ? "higher" : "lower"} than lines + tax by ${formatCents(diff!)}.`}
        </span>
        {changed && <span className="n">You changed the total from {formatCents(read!)} to {formatCents(field!)}.</span>}
      </div>
    </section>
  );
}

/** S-07: the document beside the fields; failed checks in words at the top; drafts on the server. */
export function ReviewPage() {
  const { invoiceId } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["invoice", invoiceId], queryFn: () => get<InvoiceDetail>(`/api/v1/invoices/${invoiceId}`) });
  const vendors = useQuery({ queryKey: ["vendors"], queryFn: () => get<Page<Vendor>>("/api/v1/vendors") });
  const queue = useQuery({
    queryKey: ["invoices", "review"],
    queryFn: () => get<Page<InvoiceSummary>>("/api/v1/invoices?limit=200&document_state=needs_review"),
  });
  usePageTitle("Extraction review", q.data?.doc_number);
  const [header, setHeader] = useState<Header>({});
  const [lines, setLines] = useState<EditLine[]>([]);
  const [version, setVersion] = useState(0);
  const [dirty, setDirty] = useState(false);
  const [accept, setAccept] = useState(false);
  const [note, setNote] = useState("");
  const [removing, setRemoving] = useState<{ id: string; line_no: number } | null>(null);
  const [removeReason, setRemoveReason] = useState("");
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [conflict, setConflict] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<{ label: string; original: unknown } | null>(null);
  const summary = useRef<HTMLDivElement>(null);
  const loadedFor = useRef<string | null>(null);
  // Counts edits, so a draft save that finishes after more typing does not mark that typing saved
  // (review W8).
  const edits = useRef(0);

  useEffect(() => {
    const r = q.data?.review;
    if (!r || loadedFor.current === `${invoiceId}:${r.version}`) return;
    if (dirty && loadedFor.current?.startsWith(`${invoiceId}:`)) return;
    loadedFor.current = `${invoiceId}:${r.version}`;
    const base = fromReview(r);
    const draft = r.review_draft;

    const restored = (draft?.lines ?? []).map((l) => {
      const x = l as Record<string, unknown>;
      const s = (k: string) => (x[k] === null || x[k] === undefined ? "" : String(x[k]));
      return { line_no: Number(x.line_no), supplier_item_code: s("supplier_item_code"), description: s("description"), qty: s("qty"), uom: s("uom"), unit_price: s("unit_price"), amount: s("amount"), line_kind: s("line_kind") || "item" };
    });
    const draftHeader = Object.fromEntries(Object.entries(draft?.fields ?? {}).map(([k, v]) => [k, v === null || v === undefined ? "" : String(v)]));
    setHeader({ ...base.header, ...draftHeader });
    setLines(restored.length ? restored : base.lines);
    setVersion(r.version);
    if (draft) setSavedAt((draft as { saved_at?: string }).saved_at ?? null);
  }, [q.data, invoiceId, dirty]);

  const checks = useMemo(
    () =>
      failedChecks(
        {
          vendor_id: header.vendor_id ?? "",
          doc_number: header.doc_number ?? "",
          doc_date: header.doc_date ?? "",
          subtotal: header.subtotal ?? "",
          tax_total: header.tax_total ?? "",
          total: header.total ?? "",
        },
        lines,
      ),
    [header, lines],
  );

  // Number fields are sent as plain decimals ("1,000" -> "1000"); one that cannot be read is sent
  // as typed only in a draft, and confirmation is blocked until it is fixed (B10, item 3).
  const payload = useCallback(
    (draft: boolean) => {
      const plain = (k: string, v: string) => {
        if (v === "") return null;
        const rules = FIELD_RULES[k];
        if (!rules) return v;
        return plainNumber(v, rules) || (draft ? v : null);
      };
      return {
        draft,
        fields: Object.fromEntries(HEADER_FIELDS.map((f) => [f.key, plain(f.key, header[f.key] ?? "")])),
        lines: lines.map((l) => ({
          line_no: l.line_no,
          ...Object.fromEntries(LINE_FIELDS.map((k) => [k, plain(k, l[k] ?? "")])),
          line_kind: l.line_kind,
        })),
      };
    },
    [header, lines],
  );

  const onConflict = useCallback((err: unknown) => {
    if (err instanceof ApiError && err.status === 409) {
      const cur = err.current as Review | undefined;
      setConflict(
        `This document was changed by someone else${cur?.review_draft?.saved_at ? ` at ${time(cur.review_draft.saved_at)}` : ""}. Reload to see their changes; your values stay on screen for copying.`,
      );
      return true;
    }
    return false;
  }, []);

  const saveDraft = useCallback(async () => {
    if (!dirty) return;
    const at = edits.current;
    try {
      const r = await send<Review>("PATCH", `/api/v1/invoices/${invoiceId}/extraction`, payload(true), { ifMatch: version });
      setVersion(r.version);
      loadedFor.current = `${invoiceId}:${r.version}`;
      setSavedAt(new Date().toISOString());
      if (edits.current === at) setDirty(false);
    } catch (err) {
      if (!onConflict(err)) setError(`Draft not saved: ${errorText(err)} Your values are still here; try again.`);
    }
  }, [dirty, invoiceId, payload, version, onConflict]);

  // Saves a draft on the server every 30 seconds while there are changes. Nothing in browser storage.
  useEffect(() => {
    const t = window.setInterval(() => void saveDraft(), 30_000);
    return () => window.clearInterval(t);
  }, [saveDraft]);
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  async function confirmAndMatch() {
    setError(null);
    if (checks.length > arithmetic.length) {
      setError("Fill in what is missing above before confirming.");
      summary.current?.focus();
      return;
    }
    if (arithmetic.length && !accept) {
      setError("The checks above do not pass. Correct the values, or tick that the document itself does not add up.");
      summary.current?.focus();
      return;
    }
    if (arithmetic.length && accept && !note.trim()) {
      setError("Say in the note why the document itself does not add up.");
      document.getElementById("inconsistent-note")?.focus();
      return;
    }
    setBusy(true);
    try {
      let v = version;
      if (dirty || (q.data?.review.review_draft ?? null)) {
        const r = await send<Review>("PATCH", `/api/v1/invoices/${invoiceId}/extraction`, payload(false), { ifMatch: v });
        v = r.version;
      }
      await send(
        "POST",
        `/api/v1/invoices/${invoiceId}/confirm-extraction`,
        arithmetic.length && accept ? { accept_inconsistent: true, note: note.trim() } : { accept_inconsistent: false },
        { ifMatch: v },
      );
      setDirty(false);
      qc.invalidateQueries({ queryKey: ["invoice", invoiceId] });
      qc.invalidateQueries({ queryKey: ["invoices"] });
      qc.invalidateQueries({ queryKey: ["batch"] });
      qc.invalidateQueries({ queryKey: ["exceptions"] });
      toast("Confirmed. The match view shows the result when matching finishes.", "success");
      navigate(`/invoices/${invoiceId}`);
    } catch (err) {
      if (!onConflict(err)) setError(errorText(err));
      summary.current?.focus();
    } finally {
      setBusy(false);
    }
  }

  // B9: a line removed in review is kept in its history; the gates run again on the remaining lines.
  async function removeLine() {
    if (!removing) return;
    setBusy(true);
    setError(null);
    try {
      let v = version;
      if (dirty || (q.data?.review.review_draft ?? null)) {
        const kept = payload(false);
        kept.lines = kept.lines.filter((l) => l.line_no !== removing.line_no);
        const saved = await send<Review>("PATCH", `/api/v1/invoices/${invoiceId}/extraction`, kept, { ifMatch: v });
        v = saved.version;
      }
      const after = await send<Review & { gates: Record<string, boolean> }>(
        "POST",
        `/api/v1/invoices/${invoiceId}/lines/${removing.id}/removal`,
        { reason: removeReason.trim() || null },
        { ifMatch: v },
      );
      setLines((ls) => ls.filter((l) => l.line_no !== removing.line_no));
      setVersion(after.version);
      setDirty(false);
      loadedFor.current = null;
      setRemoving(null);
      setRemoveReason("");
      qc.invalidateQueries({ queryKey: ["invoice", invoiceId] });
      const ok = Object.values(after.gates ?? {}).every(Boolean);
      toast(`Line ${removing.line_no} removed. ${ok ? "The checks pass on the remaining lines." : "The checks were run again on the remaining lines."}`, "success");
    } catch (err) {
      if (!onConflict(err)) setError(errorText(err));
      setRemoving(null);
    } finally {
      setBusy(false);
    }
  }

  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorState error={q.error} retry={() => q.refetch()} />;
  const inv = q.data!;
  const r = inv.review;
  const set = (k: string, v: string) => {
    edits.current += 1;
    setHeader((h) => ({ ...h, [k]: v }));
    setDirty(true);
  };
  const setLine = (i: number, k: string, v: string) => {
    edits.current += 1;
    setLines((ls) => ls.map((l, j) => (j === i ? { ...l, [k]: v } : l)));
    setDirty(true);
  };
  // The values as read, to tag a field "edited" as soon as it differs or is held in the server
  // draft, not only after confirmation (review W4; S-07).
  const asRead = fromReview(r);
  const readLine = (no: number) => asRead.lines.find((l) => l.line_no === no);
  const headerError = (k: string) => (FIELD_RULES[k] ? numberError(header[k], FIELD_RULES[k]) : null);
  // Only the arithmetic checks can be accepted as "the document does not add up"; a missing
  // supplier, number, date or line has to be filled in (review, minor).
  const arithmetic = checks.filter((c) => /^Line \d+:|^Lines /.test(c));
  const next = (queue.data?.items ?? []).find((i) => i.id !== invoiceId);
  const confirmed = (r.verification_status ?? "").startsWith("human_confirmed");
  return (
    <>
      <PageHead
        title={`${inv.doc_number ?? "Document"} · extraction review`}
        crumbs={
          <>
            <Link to="/invoices">Invoices</Link> / <Link to={`/invoices/${invoiceId}`}>{inv.doc_number ?? "Document"}</Link>
          </>
        }
        lede={r.vendor_name_read ? `Supplier name read from the document: ${r.vendor_name_read}` : "No supplier name could be read."}
        actions={
          <>
            <StatusChip status={inv.removed ? "deleted" : r.document_state === "needs_review" ? "needs_review" : r.verification_status === "passed" || r.verification_status?.startsWith("human") ? "ready" : "needs_review"} />
            {!inv.removed && (
              <DeleteDocument documentId={inv.document_id} name={inv.doc_number ?? "this document"} onDeleted={() => navigate("/invoices")} />
            )}
          </>
        }
      />
      {inv.removed && <RemovedBanner removed={inv.removed} />}
      {conflict && (
        <Banner tone="warn" role="alert">
          <p>{conflict}</p>
          <button className="btn small" onClick={() => {
            setConflict(null);
            setDirty(false);
            loadedFor.current = null;
            q.refetch();
          }}>
            Reload
          </button>
        </Banner>
      )}
      <div className="review-grid">
        <section className="pane-doc panel panel-body" aria-label="Document">
          <Suspense fallback={<Loading label="Loading document" />}>
            <PdfViewer documentId={inv.document_id} label={`Document ${inv.doc_number ?? ""}`} />
          </Suspense>
        </section>
        <section aria-label="Fields" className="stack">
          <div ref={summary} tabIndex={-1}>
            {checks.length > 0 ? (
              <div className="banner error" role="alert">
                <div>
                  <p>
                    <strong>{checks.length === 1 ? "1 check does not pass" : `${checks.length} checks do not pass`}</strong>
                  </p>
                  <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
                    {checks.map((c) => (
                      <li key={c}>{c}</li>
                    ))}
                  </ul>
                </div>
              </div>
            ) : (
              <Banner tone="ok">All arithmetic checks pass.</Banner>
            )}
            {error && (
              <p className="error-text" role="alert">
                {error}
              </p>
            )}
          </div>
          <TotalCheck printed={asRead.header.total ?? ""} edited={header.total ?? ""} tax={header.tax_total ?? ""} lines={lines.map((l) => l.amount)} />
          <div className="panel">
            <div className="panel-head">
              <h2>Header</h2>
              <span className="muted small">{savedAt ? `Draft saved at ${time(savedAt)}` : dirty ? "Unsaved changes" : ""}</span>
            </div>
            <div className="panel-body grid-2" style={{ gap: "0 16px" }}>
              {HEADER_FIELDS.map((f) => {
                const src = r.field_sources[f.key] ?? (f.source ? r.field_sources[f.source] : undefined);
                return (
                  <div className="field" key={f.key}>
                    <span style={{ display: "flex", gap: 6, alignItems: "center" }}>
                      <label htmlFor={`h-${f.key}`}>{f.label}</label>
                      <Provenance
                        src={src}
                        changed={(header[f.key] ?? "") !== (asRead.header[f.key] ?? "")}
                        value={asRead.header[f.key]}
                        onHistory={() => setHistory({ label: f.label, original: src?.source === "edited" ? src.original : asRead.header[f.key] })}
                      />
                    </span>
                    {f.key === "doc_type" ? (
                      <select id={`h-${f.key}`} value={header[f.key] ?? ""} onChange={(e) => set(f.key, e.target.value)}>
                        <option value="invoice">Invoice</option>
                        <option value="credit_note">Credit note</option>
                      </select>
                    ) : f.key === "vendor_id" ? (
                      <select id={`h-${f.key}`} value={header[f.key] ?? ""} onChange={(e) => set(f.key, e.target.value)} aria-invalid={!header[f.key]}>
                        <option value="">Choose the supplier</option>
                        {(vendors.data?.items ?? []).map((v) => (
                          <option key={v.id} value={v.id}>
                            {v.name}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <input
                        id={`h-${f.key}`}
                        type={f.type ?? "text"}
                        inputMode={FIELD_RULES[f.key] ? "decimal" : undefined}
                        className={FIELD_RULES[f.key] ? "num" : undefined}
                        value={header[f.key] ?? ""}
                        aria-invalid={headerError(f.key) ? true : undefined}
                        aria-describedby={headerError(f.key) ? `h-${f.key}-err` : undefined}
                        onChange={(e) => set(f.key, e.target.value)}
                      />
                    )}
                    {headerError(f.key) && (
                      <span className="error-text small" id={`h-${f.key}-err`}>
                        {headerError(f.key)}
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
          <div className="panel">
            <div className="panel-head">
              <h2>Lines</h2>
              <button
                className="btn small"
                onClick={() => {
                  setLines((ls) => [
                    ...ls,
                    { line_no: Math.max(r.next_line_no ?? 1, Math.max(0, ...ls.map((l) => l.line_no)) + 1), supplier_item_code: "", description: "", qty: "", uom: "", unit_price: "", amount: "", line_kind: "item" },
                  ]);
                  setDirty(true);
                }}
              >
                Add a line
              </button>
            </div>
            {/* One block per line, so quantity, unit, unit price and amount are always in view however
                narrow the pane is (B6 review M3: the table was 929 px wide in a 564 px pane). */}
            <ol className="line-editor">
              {lines.map((l, i) => {
                const src = r.line_fields.find((x) => x.line_no === l.line_no)?.field_sources ?? {};
                const field = (k: (typeof LINE_FIELDS)[number]) => {
                  const bad = FIELD_RULES[k] ? numberError(l[k], FIELD_RULES[k]) : null;
                  return (
                  <div className={`le-field le-${k}`} key={k}>
                    <label htmlFor={`l-${l.line_no}-${k}`}>{LINE_LABELS[k]}</label>
                    <input
                      id={`l-${l.line_no}-${k}`}
                      aria-label={`Line ${l.line_no} ${LINE_LABELS[k]}`}
                      className={FIELD_RULES[k] ? "num" : undefined}
                      inputMode={FIELD_RULES[k] ? "decimal" : undefined}
                      value={l[k] ?? ""}
                      aria-invalid={bad ? true : undefined}
                      aria-describedby={bad ? `l-${l.line_no}-${k}-err` : undefined}
                      onChange={(e) => setLine(i, k, e.target.value)}
                    />
                    {bad && (
                      <span className="error-text small le-error" id={`l-${l.line_no}-${k}-err`}>
                        {bad}
                      </span>
                    )}
                    {(src[k]?.source === "edited" || (readLine(l.line_no) && (l[k] ?? "") !== (readLine(l.line_no)?.[k] ?? ""))) && (
                      <span className="le-edited">
                        <span className="tag edited">edited</span>
                        <button
                          type="button"
                          className="btn small ghost"
                          onClick={() =>
                            setHistory({ label: `Line ${l.line_no} ${LINE_LABELS[k]}`, original: src[k]?.source === "edited" ? src[k]?.original : readLine(l.line_no)?.[k] })
                          }
                        >
                          History
                        </button>
                      </span>
                    )}
                  </div>
                  );
                };
                const stored = r.line_fields.find((x) => x.line_no === l.line_no);
                return (
                  <li key={l.line_no} className="le-line">
                    <div className="le-head">
                      <span className="le-no">Line {l.line_no}</span>
                      <select aria-label={`Line ${l.line_no} kind`} value={l.line_kind} onChange={(e) => setLine(i, "line_kind", e.target.value)}>
                        <option value="item">Item</option>
                        <option value="freight">Freight</option>
                        <option value="fee">Fee</option>
                        <option value="discount">Discount</option>
                      </select>
                      {confirmed ? null : stored ? (
                        <button type="button" className="btn small ghost danger-text" onClick={() => setRemoving({ id: stored.id, line_no: l.line_no })}>
                          Remove line {l.line_no}
                        </button>
                      ) : (
                        <button
                          type="button"
                          className="btn small ghost"
                          onClick={() => {
                            setLines((ls) => ls.filter((_x, j) => j !== i));
                            setDirty(true);
                          }}
                        >
                          Discard new line
                        </button>
                      )}
                    </div>
                    <div className="le-what">{field("supplier_item_code")}{field("description")}</div>
                    <div className="le-sum">{field("qty")}{field("uom")}{field("unit_price")}{field("amount")}</div>
                  </li>
                );
              })}
            </ol>
            <p className="muted small" style={{ padding: "0 16px 12px" }}>
              {confirmed
                ? "This document is confirmed: its lines stay. Correct a misread value instead."
                : "Remove a line the reader invented or read twice. It stays in this document's history; the checks run again."}
            </p>
            {(r.removed_lines ?? []).length > 0 && (
              <details className="removed-lines">
                <summary>{(r.removed_lines ?? []).length === 1 ? "1 removed line" : `${(r.removed_lines ?? []).length} removed lines`}</summary>
                <ul className="plain-list">
                  {(r.removed_lines ?? []).map((x) => (
                    <li key={x.id}>
                      Line {x.line_no}: {x.supplier_item_code ?? "no code"}, {qty(x.qty) || "no quantity"} {x.uom ?? ""} at {x.unit_price ?? "no price"} = {x.amount ?? "no amount"}. Removed {when(x.removed_at)}
                      {x.removed_reason ? `: ${x.removed_reason}` : "."}
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </div>
          {arithmetic.length > 0 && (
            <div className="panel panel-body">
              <label className="choice">
                <input type="checkbox" checked={accept} onChange={(e) => setAccept(e.target.checked)} />
                <span>The document itself does not add up. It is confirmed as read and the report flags it.</span>
              </label>
              {accept && (
                <div className="field" style={{ marginTop: 8 }}>
                  <label htmlFor="inconsistent-note">Note (required): why the document does not add up</label>
                  <textarea
                    id="inconsistent-note"
                    rows={2}
                    maxLength={2000}
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                    placeholder="For example: the printed total leaves out the eco fee on line 3"
                  />
                  <span className="hint">Kept with the document, in its history and in the report.</span>
                </div>
              )}
            </div>
          )}
          {r.inconsistent_note && (
            <Banner tone="warn">
              <p>
                Confirmed as not adding up: <q>{r.inconsistent_note}</q>
              </p>
            </Banner>
          )}
          <div className="actions">
            <button className="btn primary" onClick={confirmAndMatch} disabled={busy}>
              {busy ? "Confirming…" : "Confirm and match"}
            </button>
            <button className="btn" onClick={() => void saveDraft()} disabled={!dirty}>
              Save draft
            </button>
            {next && (
              <Link className="btn ghost" to={`/invoices/${next.id}/review`}>
                Skip to next in review
              </Link>
            )}
          </div>
        </section>
      </div>
      <Dialog
        open={!!removing}
        title={`Remove line ${removing?.line_no ?? ""}`}
        description="The line stays in this document's history with your name and reason. The checks run again on the remaining lines."
        onClose={() => setRemoving(null)}
        footer={
          <>
            <button className="btn" data-safe onClick={() => setRemoving(null)}>
              Keep the line
            </button>
            <button className="btn danger" disabled={busy} onClick={() => void removeLine()}>
              Remove line {removing?.line_no}
            </button>
          </>
        }
      >
        <div className="field">
          <label htmlFor="remove-reason">Reason</label>
          <input id="remove-reason" value={removeReason} maxLength={1000} onChange={(e) => setRemoveReason(e.target.value)} placeholder="For example: printed twice" />
        </div>
        {dirty && <p className="muted small">Your other changes are saved first.</p>}
      </Dialog>
      <Dialog
        open={!!history}
        title={`History: ${history?.label ?? ""}`}
        onClose={() => setHistory(null)}
        footer={
          <button className="btn" data-safe onClick={() => setHistory(null)}>
            Close
          </button>
        }
      >
        <p>
          Originally read: <strong>{history?.original === null || history?.original === undefined || history?.original === "" ? "nothing" : String(history.original)}</strong>
        </p>
      </Dialog>
    </>
  );
}
