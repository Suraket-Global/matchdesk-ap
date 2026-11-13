import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, errorText, get, send, upload } from "../api/client";
import type { Coverage, Page, ReceivingImport, SavedMapping } from "../api/types";
import { FIGURE_STATES } from "../api/types";
import { usePeriod } from "../app/period";
import { useSession } from "../app/session";
import { Banner, Dialog, Empty, ErrorState, Field, Loading, PageHead, StatusChip, toast, usePageTitle } from "../components/ui";
import { EVIDENCE_CLASSES } from "../lib/words";
import { day, monthName, monthRange, plural, safePath, when } from "../lib/format";

const REJECT_WORDS: Record<string, string> = {
  po_not_found: "Unknown PO number",
  po_line_not_found: "Unknown PO line or item",
  qty_unreadable: "Quantity not a number",
  date_unreadable: "Unreadable date",
  uom_unknown: "Unknown unit",
  entered_after_bill: "Entered after the bill",
  entered_by_ap_staff: "Entered by accounts-payable staff",
};

const TARGETS: { key: string; label: string; required?: boolean; guess: RegExp }[] = [
  { key: "po_number", label: "PO number", required: true, guess: /^(po|po ?(number|no|#)|purchase ?order)/i },
  { key: "line_no", label: "PO line number", guess: /^(line|line ?(no|number|#))$/i },
  { key: "item_code", label: "Item code", guess: /^(item|sku|item ?code|part)/i },
  { key: "qty_received", label: "Quantity received", required: true, guess: /^(qty|quantity|received ?qty|qty ?received)/i },
  { key: "uom", label: "Unit", guess: /^(uom|unit|units)$/i },
  { key: "received_date", label: "Received date", required: true, guess: /^(received|date|received ?date|receipt ?date)/i },
  { key: "receiver_ref", label: "Receiver reference", guess: /^(receiver|received ?by|ref|reference)/i },
];

/** First day of the month two months before last month: the history a back-test usually needs. */
function defaultStart(now: Date = new Date()): string {
  const d = new Date(now.getFullYear(), now.getMonth() - 3, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-01`;
}

function status(i: ReceivingImport): string {
  if (i.state === "succeeded") return "succeeded";
  if (i.state === "voided") return "voided";
  return "draft";
}

/** S-05 list: imports, their evidence class and rows, and the upload form. */
export function ReceivingListPage() {
  usePageTitle("Receiving imports");
  const { can } = useSession();
  // B10: newest first from the server, paged by (created, id); every page can be loaded.
  const list = useInfiniteQuery({
    queryKey: ["receiving", "imports", "pages"],
    queryFn: ({ pageParam }) => get<Page<ReceivingImport>>(`/api/v1/receiving/imports?limit=200${pageParam ? `&cursor=${encodeURIComponent(pageParam)}` : ""}`),
    initialPageParam: "",
    getNextPageParam: (l) => l.next_cursor ?? undefined,
  });
  const imports = (list.data?.pages ?? []).flatMap((p) => p.items);
  return (
    <>
      <PageHead
        title="Receiving imports"
        lede="Warehouse receiving logs and receiver-signed delivery documents. Each receipt line shows the file, the row and the kind of evidence."
      />
      <CoverageSummary />
      {can("upload") && <UploadForm />}
      <section style={{ marginTop: 16 }} aria-labelledby="imports-h">
        <h2 id="imports-h" style={{ marginBottom: 8 }}>
          Imports
        </h2>
        {list.isLoading && <Loading />}
        {list.error && <ErrorState error={list.error} retry={() => list.refetch()} />}
        {list.data && imports.length === 0 && (
          <div className="panel">
            <Empty title="No receiving file yet">
              <p>
                Upload the warehouse receiving log as CSV or XLSX. A layout that works: columns PO, Line, Qty, UOM, Received,
                Receiver, one row per delivered line.
              </p>
            </Empty>
          </div>
        )}
        {imports.length > 0 && (
          <div className="table-wrap">
            <table className="stack-sm">
              <thead>
                <tr>
                  <th scope="col">File</th>
                  <th scope="col">Evidence</th>
                  <th scope="col">Declared complete for</th>
                  <th scope="col">Loaded</th>
                  <th scope="col" className="num">
                    Rows imported
                  </th>
                  <th scope="col" className="num">
                    Rows rejected
                  </th>
                  <th scope="col" className="num">
                    Rows waiting for controller approval
                  </th>
                  <th scope="col">Status</th>
                </tr>
              </thead>
              <tbody>
                {imports.map((i) => (
                  <tr key={i.id}>
                    <td data-label="File">
                      <Link to={`/receiving/imports/${i.id}`}>{i.file_name || "Receiving file"}</Link>
                    </td>
                    <td data-label="Evidence">
                      {i.evidence_class} · {EVIDENCE_CLASSES[i.evidence_class]?.name}
                      {i.source_type === "qbo_item_receipt_export" && <div className="muted small">QuickBooks item-receipt export</div>}
                    </td>
                    <td data-label="Declared complete for">{i.declared_complete ? `${day(i.coverage_start)} to ${day(i.coverage_end)}` : <span className="muted">Not declared</span>}</td>
                    <td data-label="Loaded">{when(i.committed_at ?? i.created_at)}</td>
                    <td data-label="Rows imported" className="num">{i.state === "succeeded" || i.state === "voided" ? i.rows_valid ?? 0 : ""}</td>
                    <td data-label="Rows rejected" className="num">{i.rows_rejected ?? ""}</td>
                    <td data-label="Waiting for approval" className="num">{i.late_lines_waiting ? <Link to="/approvals">{i.late_lines_waiting}</Link> : i.state === "succeeded" ? 0 : ""}</td>
                    <td data-label="Status">
                      <StatusChip status={status(i)} word={i.state === "draft" ? "Draft, not imported" : undefined} />
                      {i.state === "draft" && i.expires_at && <div className="muted small">Removed on {day(i.expires_at)} if not imported</div>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {list.hasNextPage && (
          <button className="btn" style={{ marginTop: 12 }} onClick={() => list.fetchNextPage()} disabled={list.isFetchingNextPage}>
            {list.isFetchingNextPage ? "Loading…" : "Show older imports"}
          </button>
        )}
      </section>
    </>
  );
}

function UploadForm() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [cls, setCls] = useState("A");
  const [source, setSource] = useState("spreadsheet");
  const [keptBy, setKeptBy] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function submit(e: FormEvent) {
    e.preventDefault();
    const f = fileRef.current?.files?.[0];
    if (!f) {
      setErr("Choose a CSV or XLSX file.");
      fileRef.current?.focus();
      return;
    }
    setErr(null);
    setBusy(true);
    const form = new FormData();
    form.append("file", f);
    form.append("evidence_class", source === "qbo_item_receipt_export" ? "A" : cls);
    form.append("source_type", source);
    if (keptBy.trim()) form.append("kept_by_name", keptBy.trim());
    try {
      const imp = await upload<ReceivingImport>("/api/v1/receiving/imports", form);
      qc.invalidateQueries({ queryKey: ["receiving", "imports"] });
      navigate(`/receiving/imports/${imp.id}`);
    } catch (e2) {
      if (e2 instanceof ApiError && e2.status === 409)
        setErr("This file was already imported. Nothing was added. Void the earlier import first if it was wrong.");
      else setErr(errorText(e2));
    } finally {
      setBusy(false);
    }
  }
  return (
    <form className="panel" onSubmit={submit} aria-labelledby="upload-h">
      <div className="panel-head">
        <h2 id="upload-h">Load a receiving file</h2>
      </div>
      <div className="panel-body grid-2">
        <div>
          <div className="field">
            <label htmlFor="rfile">File (CSV or XLSX, up to 20 MB)</label>
            <input id="rfile" ref={fileRef} type="file" accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" aria-describedby={err ? "rfile-err" : undefined} />
            {err && (
              <span className="error" id="rfile-err" role="alert">
                {err}
              </span>
            )}
          </div>
          <div className="field">
            <label htmlFor="source">Source</label>
            <select id="source" value={source} onChange={(e) => setSource(e.target.value)}>
              <option value="spreadsheet">Warehouse receiving log</option>
              <option value="qbo_item_receipt_export">QuickBooks item-receipt export</option>
            </select>
          </div>
          <Field label="Who keeps this record" hint="For example the warehouse supervisor.">
            {(f) => <input id={f.id} type="text" value={keptBy} onChange={(e) => setKeptBy(e.target.value)} aria-describedby={f.describedBy} />}
          </Field>
        </div>
        <fieldset>
          <legend>What kind of evidence is it?</legend>
          {Object.entries(EVIDENCE_CLASSES).map(([k, v]) => (
            <label className="choice" key={k}>
              <input
                type="radio"
                name="cls"
                value={k}
                checked={(source === "qbo_item_receipt_export" ? "A" : cls) === k}
                disabled={source === "qbo_item_receipt_export" && k !== "A"}
                onChange={() => setCls(k)}
              />
              <span>
                <strong>
                  {k} · {v.name}
                </strong>
                <br />
                <span className="muted">{v.explain}</span>
              </span>
            </label>
          ))}
        </fieldset>
      </div>
      <div className="panel-body" style={{ paddingTop: 0 }}>
        <button className="btn primary" type="submit" disabled={busy}>
          {busy ? "Uploading…" : "Upload and preview"}
        </button>
      </div>
    </form>
  );
}

function downloadRejected(imp: ReceivingImport) {
  const rows = imp.rejected_rows ?? [];
  const esc = (v: unknown) => {
    const s = String(v ?? "");
    const safe = /^[=+\-@\t\r]/.test(s) ? `'${s}` : s;
    return /[",\n]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe;
  };
  const text = ["row,reason,value", ...rows.map((r) => [r.row, REJECT_WORDS[r.reason] ?? r.reason, r.value].map(esc).join(","))].join("\n");
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = `rejected-rows-${imp.file_name ?? imp.id}.csv`.replace(/\.csv\.csv$/, ".csv");
  a.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 5000);
}

/** S-05 import: map columns, validate, declare coverage, import valid rows; or view and void. */
export function ReceivingImportPage() {
  const { importId } = useParams();
  const { can } = useSession();
  const qc = useQueryClient();
  const key = ["receiving", "import", importId];
  const q = useQuery({ queryKey: key, queryFn: () => get<ReceivingImport>(`/api/v1/receiving/imports/${importId}`) });
  usePageTitle("Receiving import", q.data?.file_name);
  const imp = q.data;
  const headers = imp?.preview?.headers ?? [];
  const [map, setMap] = useState<Record<string, string>>({});
  const [saveAs, setSaveAs] = useState("Warehouse log");
  const saved = useQuery({
    queryKey: ["receiving", "mappings"],
    queryFn: () => get<{ items: SavedMapping[] }>("/api/v1/receiving/mappings"),
    enabled: can("upload"),
  });
  const [mapErr, setMapErr] = useState<string | null>(null);
  const [validation, setValidation] = useState<ReceivingImport | null>(null);
  const [complete, setComplete] = useState(true);
  const [covStart, setCovStart] = useState(defaultStart());
  const [covEnd, setCovEnd] = useState(new Date().toISOString().slice(0, 10));
  const [keptBy, setKeptBy] = useState("");
  const [voidOpen, setVoidOpen] = useState(false);
  const [voidReason, setVoidReason] = useState("");
  const summaryRef = useRef<HTMLDivElement>(null);
  const [result, setResult] = useState<ReceivingImport | null>(null);

  useEffect(() => {
    if (!imp) return;
    if (imp.column_map && Object.keys(map).length === 0) setMap(imp.column_map);
    else if (headers.length && Object.keys(map).length === 0) {
      const guess: Record<string, string> = {};
      for (const t of TARGETS) {
        const h = headers.find((x) => t.guess.test(x.trim()) && !Object.values(guess).includes(x));
        if (h) guess[t.key] = h;
      }
      setMap(guess);
    }
    if (imp.kept_by_name && !keptBy) setKeptBy(imp.kept_by_name);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [imp?.id, headers.length]);

  const saveMapping = useMutation({
    mutationFn: () => {
      const cols = Object.fromEntries(Object.entries(map).filter(([, v]) => v));
      return send<ReceivingImport>("PUT", `/api/v1/receiving/imports/${importId}/mapping`, { columns: cols, save_as: saveAs.trim() || null });
    },
    onSuccess: (r) => {
      // The validation counts are in `validation`; the import fields beside it predate the check.
      const merged = { ...r, ...(r.validation as Partial<ReceivingImport>) };
      setValidation(merged);
      qc.setQueryData(key, { ...imp, ...merged, preview: imp?.preview });
      qc.invalidateQueries({ queryKey: ["receiving", "mappings"] });
      window.setTimeout(() => summaryRef.current?.focus(), 0);
    },
    onError: (e) => {
      setMapErr(errorText(e));
      window.setTimeout(() => summaryRef.current?.focus(), 0);
    },
  });
  const declare = useMutation({
    mutationFn: () =>
      send<ReceivingImport>("PUT", `/api/v1/receiving/imports/${importId}/declaration`, {
        declared_complete: complete,
        coverage_start: complete ? covStart : null,
        coverage_end: complete ? covEnd : null,
        kept_by_name: keptBy || null,
      }),
  });
  const commit = useMutation({
    mutationFn: async () => {
      if (imp?.evidence_class === "A") await declare.mutateAsync();
      return send<ReceivingImport>("POST", `/api/v1/receiving/imports/${importId}/commit`);
    },
    onSuccess: (r) => {
      setResult(r);
      qc.invalidateQueries({ queryKey: ["receiving"] });
      qc.invalidateQueries({ queryKey: ["exceptions"] });
      qc.invalidateQueries({ queryKey: ["invoice"] });
    },
  });
  const voidIt = useMutation({
    mutationFn: () => send<ReceivingImport>("POST", `/api/v1/receiving/imports/${importId}/void`, { reason: voidReason }),
    onSuccess: () => {
      setVoidOpen(false);
      qc.invalidateQueries({ queryKey: ["receiving"] });
      qc.invalidateQueries({ queryKey: ["exceptions"] });
      toast("Import voided. Its receipt lines no longer count; affected lines are being re-matched.", "info");
    },
  });
  const missing = useMemo(() => {
    const m = TARGETS.filter((t) => t.required && !map[t.key]).map((t) => t.label);
    if (!map.line_no && !map.item_code) m.push("PO line number or item code");
    return m;
  }, [map]);

  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorState error={q.error} retry={() => q.refetch()} />;
  if (!imp) return null;
  const draft = imp.state === "draft";
  // A pre-applied saved mapping is only a proposal: the rows are checked once the clerk asks (B9).
  const v = validation ?? (imp.column_map && imp.rows_valid !== null ? imp : null);
  const applied = (saved.data?.items ?? []).find((m) => m.id === imp.mapping_id) ?? imp.preview?.applied_mapping ?? null;
  const fits = (m: SavedMapping) => Object.values(m.columns).every((c) => headers.includes(c));
  const mappingPanel = (
          <section className="panel" aria-labelledby="map-h">
            <div className="panel-head">
              <h2 id="map-h">1. Match the columns</h2>
              <span className="muted">{plural(imp.preview?.rows_total ?? imp.rows_total ?? 0, "row")} in the file</span>
            </div>
            <div className="panel-body">
              {applied && !validation && (
                <Banner tone="info">
                  <p>
                    The saved mapping <strong>{applied.name}</strong> fits this file and is filled in. Check each column, then
                    check the rows.
                  </p>
                </Banner>
              )}
              {(saved.data?.items ?? []).length > 0 && (
                <div className="field saved-mapping">
                  <label htmlFor="saved-map">Use a saved mapping</label>
                  <select
                    id="saved-map"
                    value=""
                    onChange={(e) => {
                      const m = saved.data?.items.find((x) => x.id === e.target.value);
                      if (m) {
                        setMap({ ...m.columns });
                        setSaveAs(m.name);
                        toast(`Mapping "${m.name}" filled in. Check the columns.`, "success");
                      }
                    }}
                  >
                    <option value="">Choose…</option>
                    {(saved.data?.items ?? []).map((m) => (
                      <option key={m.id} value={m.id} disabled={!fits(m)}>
                        {m.name}
                        {fits(m) ? "" : " (columns not in this file)"}
                      </option>
                    ))}
                  </select>
                </div>
              )}
              {/* B10 (outside QA item 13): each mapping shows a value from the file; required fields
                  not yet matched come first; optional mappings are folded away. */}
              <MappingRows targets={TARGETS.filter((t) => t.required)} map={map} setMap={setMap} headers={headers} sample={imp.preview?.sample_rows ?? []} sortUnmapped />
              <details className="map-optional">
                <summary>
                  Optional columns ({TARGETS.filter((t) => !t.required && map[t.key]).length} of {TARGETS.filter((t) => !t.required).length} matched)
                </summary>
                <MappingRows targets={TARGETS.filter((t) => !t.required)} map={map} setMap={setMap} headers={headers} sample={imp.preview?.sample_rows ?? []} />
              </details>
              {imp.preview && (
                <div className="table-wrap" style={{ marginTop: 12, maxHeight: 320 }}>
                  <table className="compact">
                    <caption>First {plural(Math.min(20, imp.preview.sample_rows?.length ?? 0), "row")}</caption>
                    <thead>
                      <tr>
                        <th scope="col">Row</th>
                        {headers.map((h) => (
                          <th scope="col" key={h}>
                            {h}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {(imp.preview.sample_rows ?? []).map((r, i) => (
                        <tr key={i}>
                          <td className="num muted">{i + 2}</td>
                          {r.map((c, j) => (
                            <td key={j}>{c}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <div className="field" style={{ marginTop: 12, maxWidth: 320 }}>
                <label htmlFor="save-as">Save this mapping as</label>
                <input id="save-as" value={saveAs} maxLength={80} onChange={(e) => setSaveAs(e.target.value)} />
                <span className="hint">The next file with these columns starts from it.</span>
              </div>
              <div className="actions" style={{ marginTop: 12 }}>
                <button
                  className="btn"
                  onClick={() => {
                    setMapErr(missing.length ? `Choose a column for: ${missing.join(", ")}.` : null);
                    if (!missing.length) saveMapping.mutate();
                    else window.setTimeout(() => summaryRef.current?.focus(), 0);
                  }}
                  disabled={saveMapping.isPending}
                >
                  Check rows
                </button>
              </div>
            </div>
          </section>
  );
  return (
    <>
      <PageHead
        title={imp.file_name || "Receiving import"}
        crumbs={<Link to="/receiving">Receiving imports</Link>}
        lede={`${imp.evidence_class} · ${EVIDENCE_CLASSES[imp.evidence_class]?.name}. ${imp.kept_by_name ? `Kept by ${imp.kept_by_name}.` : ""}`}
        actions={
          <>
            <StatusChip status={status(imp)} word={draft ? "Draft, not imported" : undefined} />
            {imp.state === "succeeded" && can("upload") && (
              <button className="btn danger" onClick={() => setVoidOpen(true)}>
                Void import
              </button>
            )}
          </>
        }
      />
      {imp.evidence_class === "C" && (
        <Banner tone="warn">Supplier documents only. Accepted and shown as context, labelled "Supplier's packing slip. Not counted as a receipt."</Banner>
      )}
      {result && (
        <Banner tone="ok" role="status">
          <p>
            Imported {plural(result.rows_valid ?? 0, "row")}.{" "}
            {result.late_lines
              ? `${plural(result.late_lines, "row")} for lines that already had an open exception are waiting for controller approval and do not count until approved. `
              : ""}
            {result.match_run_id ? "The affected purchase-order lines are being re-matched." : "No line needed a re-match."}{" "}
            <Link to="/exceptions">Go to exceptions</Link>
          </p>
        </Banner>
      )}
      {imp.state === "voided" && <Banner tone="warn">Voided: {imp.void_reason}. Its receipt lines no longer count.</Banner>}

      {draft && can("upload") && (
        <div className="stack">
          {!v && mappingPanel}
          <section className="panel" aria-labelledby="val-h">
            <div className="panel-head">
              <h2 id="val-h">2. Validation result</h2>
            </div>
            <div className="panel-body">
              <div ref={summaryRef} tabIndex={-1}>
                {mapErr && (
                  <p className="error-text" role="alert">
                    {mapErr}
                  </p>
                )}
                {!mapErr && !v && <p className="muted">Match the columns and choose Check rows.</p>}
                {!mapErr && v && (
                  <div className="val-lead" aria-label="Validation result">
                    <span className="good">
                      <strong className="num">{(v.rows_valid ?? 0).toLocaleString("en-CA")}</strong> valid {(v.rows_valid ?? 0) === 1 ? "row" : "rows"}
                    </span>
                    <span className={(v.rows_rejected ?? 0) > 0 ? "bad" : ""}>
                      <strong className="num">{(v.rows_rejected ?? 0).toLocaleString("en-CA")}</strong> rejected
                    </span>
                  </div>
                )}
                {!mapErr && v && (
                  <p className="muted small">
                    <span className="sr-only">
                      {plural(v.rows_valid ?? 0, "row")} valid, {(v.rows_rejected ?? 0).toLocaleString("en-CA")} rejected.
                    </span>{" "}
                    {(v.rows_rejected ?? 0) > 0 &&
                      `Download the ${plural(v.rows_rejected ?? 0, "rejected row")} with reasons, fix them in your spreadsheet and upload them again, or import the valid rows now. A date outside the test month is not an error.`}
                  </p>
                )}
              </div>
              {v && (v.rejected_rows?.length ?? 0) > 0 && (
                <>
                  <div className="table-wrap" style={{ marginTop: 8 }}>
                    <table className="compact">
                      <thead>
                        <tr>
                          <th scope="col" className="num">
                            Row
                          </th>
                          <th scope="col">Reason</th>
                          <th scope="col">Value</th>
                          <th scope="col">Original row</th>
                          <th scope="col">Fix</th>
                        </tr>
                      </thead>
                      <tbody>
                        {v.rejected_rows!.map((r) => (
                          <tr key={r.row}>
                            <td className="num">{r.row}</td>
                            <td>{REJECT_WORDS[r.reason] ?? r.reason}</td>
                            <td>{String(r.value ?? "")}</td>
                            <td className="orig-row">{originalRow(imp, r.row)}</td>
                            <td>{r.reason === "po_line_not_found" ? <Link to="/aliases">Add an alias</Link> : <span className="muted">Correct the file</span>}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <button className="btn small" style={{ marginTop: 8 }} onClick={() => downloadRejected(v)}>
                    Download rejected rows
                  </button>
                </>
              )}
            </div>
          </section>

          {imp.evidence_class === "A" && (
            <section className="panel" aria-labelledby="dec-h">
              <div className="panel-head">
                <h2 id="dec-h">3. Coverage</h2>
              </div>
              <div className="panel-body">
                <label className="choice">
                  <input type="checkbox" checked={complete} onChange={(e) => setComplete(e.target.checked)} />
                  <span>Every delivery between these dates is in this file.</span>
                </label>
                <div className="inline-form">
                  <Field label="From">{(f) => <input id={f.id} type="date" value={covStart} disabled={!complete} onChange={(e) => setCovStart(e.target.value)} />}</Field>
                  <Field label="To">{(f) => <input id={f.id} type="date" value={covEnd} disabled={!complete} onChange={(e) => setCovEnd(e.target.value)} />}</Field>
                  <Field label="Kept by">{(f) => <input id={f.id} type="text" value={keptBy} onChange={(e) => setKeptBy(e.target.value)} />}</Field>
                </div>
                <p className="muted small">
                  Where the log is declared complete and shows nothing for an invoiced line, that line is "not received". Otherwise it is
                  unverified.
                </p>
              </div>
            </section>
          )}

          <div className="actions">
            <button className="btn primary" disabled={!v || (v.rows_valid ?? 0) === 0 || commit.isPending} onClick={() => commit.mutate()}>
              {commit.isPending ? "Importing…" : `Import ${v ? plural(v.rows_valid ?? 0, "valid row") : "valid rows"}`}
            </button>
            {(commit.error || declare.error) && <span className="error-text">{errorText(commit.error ?? declare.error)}</span>}
          </div>
          {v && (
            <details className="panel fold">
              <summary>Column matching (checked). Change it and check the rows again</summary>
              {mappingPanel}
            </details>
          )}
        </div>
      )}

      {!draft && <ReceiptsTable imp={imp} />}

      <Dialog
        open={voidOpen}
        title="Void import"
        onClose={() => setVoidOpen(false)}
        footer={
          <>
            <button className="btn" data-safe onClick={() => setVoidOpen(false)}>
              Keep it
            </button>
            <button className="btn danger" disabled={!voidReason.trim() || voidIt.isPending} onClick={() => voidIt.mutate()}>
              Void import
            </button>
          </>
        }
      >
        <p>Its {plural(imp.rows_valid ?? 0, "receipt line")} stop counting and the affected lines are re-matched. The import stays listed as voided.</p>
        <Field label="Reason (required)">{(f) => <textarea id={f.id} value={voidReason} onChange={(e) => setVoidReason(e.target.value)} />}</Field>
        {voidIt.error && <p className="error-text">{errorText(voidIt.error)}</p>}
      </Dialog>
    </>
  );
}

/** The cells of a file row as the file has them, when the row is in the stored preview (B8). */
function originalRow(imp: ReceivingImport, row: number): string {
  const cells = imp.preview?.sample_rows?.[row - 2];
  return cells ? cells.join(", ") : "Not in the first 20 rows; see the downloaded file";
}

function ReceiptsTable({ imp }: { imp: ReceivingImport }) {
  const { can } = useSession();
  // B8: ?row=N from a match view opens on that receipt row, marked, with a way back.
  const [params] = useSearchParams();
  const want = Number(params.get("row") ?? 0);
  const back = safePath(params.get("from"), "");
  useEffect(() => {
    if (want) window.setTimeout(() => document.getElementById(`receipt-row-${want}`)?.focus(), 50);
  }, [want, imp.id]);
  const qc = useQueryClient();
  const [signer, setSigner] = useState<Record<string, string>>({});
  const confirm = useMutation({
    mutationFn: (r: { id: string; version: number; marks: boolean }) =>
      send("POST", `/api/v1/receiving/receipts/${r.id}/confirm`, { receiver_marks_present: r.marks, receiver_name: signer[r.id] || null }, { ifMatch: r.version }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["receiving", "import", imp.id] }),
  });
  const receipts = imp.receipts ?? [];
  if (!receipts.length) return <Empty title="No receipt lines in this import" />;
  return (
    <section aria-labelledby="rec-h">
      <h2 id="rec-h" style={{ marginBottom: 8 }}>
        Receipt lines
      </h2>
      {want > 0 && (
        <p className="row-target-note">
          Row {want} of {imp.file_name} is marked below.{back && <> <Link to={back}>Back to the invoice</Link></>}
        </p>
      )}
      <div className="table-wrap">
        <table className="stack-sm">
          <thead>
            <tr>
              <th scope="col">PO</th>
              <th scope="col" className="num">
                PO line
              </th>
              <th scope="col">Received</th>
              <th scope="col">Receiver reference</th>
              <th scope="col" className="num">
                Row
              </th>
              <th scope="col" className="num">
                Quantity
              </th>
              <th scope="col">Unit</th>
              <th scope="col">Counts as a receipt</th>
            </tr>
          </thead>
          <tbody>
            {receipts.flatMap((r) =>
              r.lines.map((ln) => (
                <tr
                  key={ln.id}
                  id={`receipt-row-${ln.source_row}`}
                  tabIndex={ln.source_row === want ? -1 : undefined}
                  aria-current={ln.source_row === want ? "true" : undefined}
                  className={`${imp.state === "voided" || imp.evidence_class === "C" ? "greyed" : ""} ${ln.source_row === want ? "row-target" : ""}`}
                >
                  <td data-label="PO">
                    <Link to={`/purchase-orders/${r.purchase_order_id}`}>{r.po_number ?? "PO"}</Link>
                  </td>
                  <td data-label="PO line" className="num">{ln.po_line_no ?? ""}</td>
                  <td data-label="Received">{day(r.received_date)}</td>
                  <td data-label="Receiver reference">{r.receiver_ref}</td>
                  <td data-label="Row" className="num">{ln.source_row}</td>
                  <td data-label="Quantity" className="num">{ln.qty_received.replace(/\.?0+$/, "")}</td>
                  <td data-label="Unit">{ln.uom ?? ""}</td>
                  <td data-label="Counts as a receipt">
                    {imp.state === "voided"
                      ? "No: import voided"
                      : imp.evidence_class === "C"
                        ? "No: supplier's packing slip"
                        : ln.added_after_exception && !ln.late_approved
                          ? "Waiting for controller approval"
                          : imp.evidence_class === "B" && !(r.receiver_marks_present && r.receiver_name)
                            ? "No: receiver marks not recorded"
                            : "Yes"}
                  </td>
                </tr>
              )),
            )}
          </tbody>
        </table>
      </div>
      {imp.evidence_class === "B" && can("upload") && imp.state === "succeeded" && (
        <div className="stack" style={{ marginTop: 16 }}>
          <h3>Confirm receiver marks</h3>
          {receipts.map((r) => (
            <div className="inline-form panel panel-body" key={r.id}>
              <span>
                PO {r.po_number} · {day(r.received_date)}
              </span>
              <Field label="Who signed">{(f) => <input id={f.id} type="text" value={signer[r.id] ?? r.receiver_name ?? ""} onChange={(e) => setSigner({ ...signer, [r.id]: e.target.value })} />}</Field>
              <button className="btn" disabled={confirm.isPending} onClick={() => confirm.mutate({ id: r.id, version: r.version, marks: true })}>
                Receiver's signature or count marks are on this document
              </button>
            </div>
          ))}
          {confirm.error && <p className="error-text">{errorText(confirm.error)}</p>}
        </div>
      )}
    </section>
  );
}

/** S-05 coverage summary (B9): invoiced PO item lines of the test month with a counting receipt, by
 * class, the same figures and denominator as the queue strip and the report draft. */
function CoverageSummary() {
  const { month } = usePeriod();
  const { start, end } = monthRange(month);
  const cov = useQuery({
    queryKey: ["coverage", start, end],
    queryFn: () => get<Coverage>(`/api/v1/coverage?period_start=${start}&period_end=${end}`),
  });
  const c = cov.data;
  if (!c) return null;
  const measured = c.state ? FIGURE_STATES.includes(c.state) : c.item_lines > 0;
  const pct = (v: string | null) => (v ? `${v.replace(/\.00$/, "")}%` : "not measured");
  return (
    <p className="coverage-line" data-testid="receiving-coverage">
      <strong>Receipt coverage, {monthName(month)}:</strong>{" "}
      {c.state === "no_receiving_records"
        ? "0%: the controller declared that no warehouse receiving records exist."
        : measured
          ? `${pct(c.receipt_coverage_pct)} of ${plural(c.item_lines, "invoiced PO line")} have a counting receipt (signed delivery documents ${pct(c.coverage_class_b_pct)}); ${pct(c.coverage_class_a_pct)} are inside a warehouse log declared complete.`
          : "not measured yet: it needs invoices for the month and their match results."}
    </p>
  );
}

/** The first value of a column in the stored sample rows, for "Received qty → Qty Received → 60". */
export function sampleValue(headers: string[], sample: (string | null)[][], column: string | undefined): string | null {
  if (!column) return null;
  const j = headers.indexOf(column);
  if (j < 0) return null;
  for (const r of sample) {
    const v = r[j];
    if (v !== null && v !== undefined && String(v).trim() !== "") return String(v);
  }
  return null;
}

function MappingRows(props: {
  targets: typeof TARGETS;
  map: Record<string, string>;
  setMap: (m: Record<string, string>) => void;
  headers: string[];
  sample: (string | null)[][];
  sortUnmapped?: boolean;
}) {
  const { map, setMap, headers, sample } = props;
  const rows = props.sortUnmapped ? [...props.targets].sort((a, b) => Number(!!map[a.key]) - Number(!!map[b.key])) : props.targets;
  return (
    <ul className="map-rows">
      {rows.map((t) => {
        const v = sampleValue(headers, sample, map[t.key]);
        return (
          <li key={t.key} className={`map-row ${t.required && !map[t.key] ? "missing" : ""}`} data-testid={`map-${t.key}`}>
            <label htmlFor={`map-${t.key}`}>
              {t.label}
              {t.required ? " (required)" : ""}
            </label>
            <span className="map-arrow" aria-hidden="true">
              →
            </span>
            <select id={`map-${t.key}`} value={map[t.key] ?? ""} aria-describedby={`map-${t.key}-sample`} onChange={(e) => setMap({ ...map, [t.key]: e.target.value })}>
              <option value="">Not in this file</option>
              {headers.map((h) => (
                <option key={h} value={h}>
                  {h}
                </option>
              ))}
            </select>
            <span className="map-arrow" aria-hidden="true">
              →
            </span>
            <span className="map-sample" id={`map-${t.key}-sample`}>
              {map[t.key] ? v !== null ? <code>{v}</code> : <span className="muted">empty in the first rows</span> : t.required ? <span className="error-text">Choose the column</span> : <span className="muted">not used</span>}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
