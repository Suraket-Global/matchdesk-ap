import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, errorText, get, send } from "../api/client";
import type { FieldSource, InvoiceDetail, InvoiceSummary, Page, Review, Vendor } from "../api/types";
import { Banner, Dialog, ErrorState, Loading, NarrowNote, PageHead, StatusChip, toast, usePageTitle } from "../components/ui";
import { failedChecks, type LineValues } from "../lib/checks";
import { qty } from "../lib/decimal";
import { time } from "../lib/format";

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

function Provenance({ src, onHistory }: { src?: FieldSource; onHistory: () => void }) {
  if (src?.source === "edited")
    return (
      <span>
        <span className="tag edited">edited</span>{" "}
        <button type="button" className="btn small ghost" onClick={onHistory}>
          History
        </button>
      </span>
    );
  return <span className="tag">read</span>;
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
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [conflict, setConflict] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<{ label: string; original: unknown } | null>(null);
  const summary = useRef<HTMLDivElement>(null);
  const loadedFor = useRef<string | null>(null);

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

  const payload = useCallback(
    (draft: boolean) => ({
      draft,
      fields: Object.fromEntries(HEADER_FIELDS.map((f) => [f.key, header[f.key] === "" ? null : header[f.key]])),
      lines: lines.map((l) => ({
        line_no: l.line_no,
        ...Object.fromEntries(LINE_FIELDS.map((k) => [k, l[k] === "" ? null : l[k]])),
        line_kind: l.line_kind,
      })),
    }),
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
    try {
      const r = await send<Review>("PATCH", `/api/v1/invoices/${invoiceId}/extraction`, payload(true), { ifMatch: version });
      setVersion(r.version);
      loadedFor.current = `${invoiceId}:${r.version}`;
      setSavedAt(new Date().toISOString());
      setDirty(false);
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
    if (checks.length && !accept) {
      setError("The checks above do not pass. Correct the values, or tick that the document itself does not add up.");
      summary.current?.focus();
      return;
    }
    setBusy(true);
    try {
      let v = version;
      if (dirty || (q.data?.review.review_draft ?? null)) {
        const r = await send<Review>("PATCH", `/api/v1/invoices/${invoiceId}/extraction`, payload(false), { ifMatch: v });
        v = r.version;
      }
      await send("POST", `/api/v1/invoices/${invoiceId}/confirm-extraction`, { accept_inconsistent: accept }, { ifMatch: v });
      setDirty(false);
      qc.invalidateQueries({ queryKey: ["invoice", invoiceId] });
      qc.invalidateQueries({ queryKey: ["invoices"] });
      qc.invalidateQueries({ queryKey: ["batch"] });
      qc.invalidateQueries({ queryKey: ["exceptions"] });
      toast("Confirmed. Matching…");
      navigate(`/invoices/${invoiceId}`);
    } catch (err) {
      if (!onConflict(err)) setError(errorText(err));
      summary.current?.focus();
    } finally {
      setBusy(false);
    }
  }

  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorState error={q.error} retry={() => q.refetch()} />;
  const inv = q.data!;
  const r = inv.review;
  const set = (k: string, v: string) => {
    setHeader((h) => ({ ...h, [k]: v }));
    setDirty(true);
  };
  const setLine = (i: number, k: string, v: string) => {
    setLines((ls) => ls.map((l, j) => (j === i ? { ...l, [k]: v } : l)));
    setDirty(true);
  };
  const next = (queue.data?.items ?? []).find((i) => i.id !== invoiceId);
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
        actions={<StatusChip status={r.document_state === "needs_review" ? "needs_review" : r.verification_status === "passed" || r.verification_status?.startsWith("human") ? "ready" : "needs_review"} />}
      />
      <NarrowNote />
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
                      <Provenance src={src} onHistory={() => setHistory({ label: f.label, original: src?.original })} />
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
                        inputMode={["subtotal", "tax_total", "total"].includes(f.key) ? "decimal" : undefined}
                        className={["subtotal", "tax_total", "total"].includes(f.key) ? "num" : undefined}
                        value={header[f.key] ?? ""}
                        onChange={(e) => set(f.key, e.target.value)}
                      />
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
                    { line_no: Math.max(0, ...ls.map((l) => l.line_no)) + 1, supplier_item_code: "", description: "", qty: "", uom: "", unit_price: "", amount: "", line_kind: "item" },
                  ]);
                  setDirty(true);
                }}
              >
                Add a line
              </button>
            </div>
            <div className="table-wrap" style={{ border: 0 }}>
              <table className="compact">
                <thead>
                  <tr>
                    <th scope="col">Line</th>
                    <th scope="col">Kind</th>
                    {LINE_FIELDS.map((k) => (
                      <th scope="col" key={k} className={["qty", "unit_price", "amount"].includes(k) ? "num" : undefined}>
                        {LINE_LABELS[k]}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {lines.map((l, i) => {
                    const src = r.line_fields.find((x) => x.line_no === l.line_no)?.field_sources ?? {};
                    return (
                      <tr key={l.line_no}>
                        <td className="num">{l.line_no}</td>
                        <td>
                          <select aria-label={`Line ${l.line_no} kind`} value={l.line_kind} onChange={(e) => setLine(i, "line_kind", e.target.value)}>
                            <option value="item">Item</option>
                            <option value="freight">Freight</option>
                            <option value="fee">Fee</option>
                            <option value="discount">Discount</option>
                          </select>
                        </td>
                        {LINE_FIELDS.map((k) => (
                          <td key={k}>
                            <input
                              aria-label={`Line ${l.line_no} ${LINE_LABELS[k]}`}
                              className={["qty", "unit_price", "amount"].includes(k) ? "num" : undefined}
                              size={k === "description" ? 18 : 8}
                              value={l[k] ?? ""}
                              onChange={(e) => setLine(i, k, e.target.value)}
                            />
                            {src[k]?.source === "edited" && (
                              <button type="button" className="btn small ghost" onClick={() => setHistory({ label: `Line ${l.line_no} ${LINE_LABELS[k]}`, original: src[k]?.original })}>
                                History
                              </button>
                            )}
                          </td>
                        ))}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <p className="muted small" style={{ padding: "0 16px 12px" }}>
              Deleting a line is not built yet. Correct a misread line's values instead.
            </p>
          </div>
          {checks.length > 0 && (
            <div className="panel panel-body">
              <label className="choice">
                <input type="checkbox" checked={accept} onChange={(e) => setAccept(e.target.checked)} />
                <span>The document itself does not add up. It is confirmed as read and the report flags it.</span>
              </label>
            </div>
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
