import { useCallback, useRef, useState, type DragEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, errorText, get, newKey, send, upload } from "../api/client";
import type { Batch, BatchFile, BatchTotals, Page } from "../api/types";
import { useSession } from "../app/session";
import { Banner, Empty, ErrorState, Loading, NarrowNote, PageHead, StatusChip, ThrottledStatus, toast, usePageTitle } from "../components/ui";
import { FAILURE_CODES } from "../lib/words";
import { plural, when } from "../lib/format";

const MAX_BYTES = 20 * 1024 * 1024;
const ACCEPT = ["application/pdf", "image/png", "image/jpeg"];

interface Pending {
  name: string;
  state: "waiting" | "uploading" | "received" | "refused";
  reason?: string;
}

const SEGMENTS: { key: keyof BatchTotals; label: string; cls: string }[] = [
  { key: "queued", label: "Queued", cls: "" },
  { key: "processing", label: "Processing", cls: "seg-processing" },
  { key: "ready", label: "Ready", cls: "seg-ready" },
  { key: "needs review", label: "Needs review", cls: "seg-review" },
  { key: "failed", label: "Failed", cls: "seg-failed" },
  { key: "duplicate file", label: "Duplicate file", cls: "seg-dup" },
];

/** Six segments that always add up to the file count (DD-08). The counts are text. */
export function TotalsBar({ totals }: { totals: BatchTotals }) {
  return (
    <div className="totals" role="group" aria-label={`Files: ${totals.file_count}`}>
      {SEGMENTS.map((s) => (
        <div key={s.key} className={s.cls}>
          <span className="n">{totals[s.key]}</span>
          <span className="muted small">{s.label}</span>
        </div>
      ))}
    </div>
  );
}

function sentence(t: BatchTotals): string {
  const inProgress = t.queued + t.processing;
  const parts = [`${t.ready} ready`, `${t["needs review"]} need review`, `${t.failed} failed`];
  if (t["duplicate file"]) parts.push(`${t["duplicate file"]} duplicate`);
  return `Reading ${plural(t.file_count, "file")}. ${parts.join(", ")}, ${inProgress} still in progress.${inProgress ? " You can leave this page; nothing will be lost." : ""}`;
}

/** Upload files into a batch, four at a time, each with its own idempotency key (S-06). */
function useUploader(onDone: (batchId: string) => void) {
  const [pending, setPending] = useState<Pending[]>([]);
  const [busy, setBusy] = useState(false);
  const qc = useQueryClient();
  const start = useCallback(
    async (files: File[], batchId?: string) => {
      setBusy(true);
      const list: Pending[] = files.map((f) => ({ name: f.name, state: "waiting" }));
      const refuse = (i: number, reason: string) => (list[i] = { ...list[i], state: "refused", reason });
      files.forEach((f, i) => {
        if (f.size > MAX_BYTES) refuse(i, "Larger than 20 MB.");
        else if (f.type && !ACCEPT.includes(f.type)) refuse(i, "Not a PDF or image.");
      });
      setPending([...list]);
      try {
        const id = batchId ?? (await send<{ id: string }>("POST", "/api/v1/intake/batches")).id;
        let next = 0;
        const worker = async () => {
          while (next < files.length) {
            const i = next++;
            if (list[i].state === "refused") continue;
            list[i] = { ...list[i], state: "uploading" };
            setPending([...list]);
            const form = new FormData();
            form.append("file", files[i], files[i].name);
            try {
              await upload(`/api/v1/intake/batches/${id}/files`, form, newKey());
              list[i] = { ...list[i], state: "received" };
            } catch (err) {
              const why =
                err instanceof ApiError && err.status === 415
                  ? "Not a PDF or image."
                  : err instanceof ApiError && err.status === 413
                    ? "Larger than 20 MB."
                    : errorText(err);
              list[i] = { ...list[i], state: "refused", reason: why };
            }
            setPending([...list]);
          }
        };
        await Promise.all([worker(), worker(), worker(), worker()]);
        qc.invalidateQueries({ queryKey: ["batches"] });
        onDone(id);
      } catch (err) {
        toast(errorText(err));
      } finally {
        setBusy(false);
      }
    },
    [onDone, qc],
  );
  return { pending, busy, start };
}

function DropZone({ onFiles, disabled }: { onFiles: (f: File[]) => void; disabled: boolean }) {
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const drop = (e: DragEvent) => {
    e.preventDefault();
    setOver(false);
    if (!disabled) onFiles(Array.from(e.dataTransfer.files));
  };
  return (
    <div
      className={`dropzone wide-only ${over ? "over" : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={drop}
    >
      <h2>Drop invoice and credit-note files here</h2>
      <p className="muted">PDF, PNG or JPEG, up to 20 MB each and 500 per batch. The same file twice becomes one document.</p>
      <label className="btn primary">
        Choose files
        <input
          ref={input}
          className="sr-only"
          type="file"
          multiple
          accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg"
          disabled={disabled}
          onChange={(e) => {
            const files = Array.from(e.target.files ?? []);
            e.target.value = "";
            if (files.length) onFiles(files);
          }}
        />
      </label>
    </div>
  );
}

function PendingList({ pending }: { pending: Pending[] }) {
  if (!pending.length) return null;
  const received = pending.filter((p) => p.state === "received").length;
  const sendable = pending.filter((p) => p.state !== "refused").length;
  return (
    <div className="panel" style={{ marginTop: 12 }}>
      <div className="panel-head">
        <h2>Upload</h2>
        <span role="status" aria-live="polite">
          {received} of {sendable} received
        </span>
      </div>
      <div className="panel-body">
        <ul style={{ margin: 0, paddingLeft: 18 }}>
          {pending.map((p, i) => (
            <li key={i}>
              {p.name}: {p.state === "refused" ? <span className="error-text">{p.reason}</span> : p.state}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

/** S-06 list. */
export function IntakeListPage() {
  usePageTitle("Invoice intake");
  const { can } = useSession();
  const navigate = useNavigate();
  const batches = useQuery({
    queryKey: ["batches"],
    queryFn: () => get<Page<Batch>>("/api/v1/intake/batches?limit=200"),
    refetchInterval: 10_000,
  });
  const { pending, busy, start } = useUploader(useCallback((id: string) => navigate(`/intake/batches/${id}`), [navigate]));
  const items = [...(batches.data?.items ?? [])].sort((a, b) => b.created_at.localeCompare(a.created_at));
  return (
    <>
      <PageHead title="Invoice intake" lede="Upload a month of invoices and credit notes and see what happened to each file." />
      <NarrowNote />
      {can("upload") && <DropZone onFiles={(f) => start(f)} disabled={busy} />}
      <PendingList pending={pending} />
      <section style={{ marginTop: 16 }} aria-labelledby="batches-h">
        <h2 id="batches-h" style={{ marginBottom: 8 }}>
          Batches
        </h2>
        {batches.isLoading && <Loading />}
        {batches.error && <ErrorState error={batches.error} retry={() => batches.refetch()} />}
        {batches.data && items.length === 0 && (
          <div className="panel">
            <Empty title="No invoices uploaded yet">
              <p>Drop the month's invoice PDFs above. The demo files are in play-files/invoices.</p>
            </Empty>
          </div>
        )}
        {items.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">Uploaded</th>
                  <th scope="col">Source</th>
                  <th scope="col" className="num">Files</th>
                  {SEGMENTS.map((s) => (
                    <th scope="col" className="num" key={s.key}>
                      {s.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {items.map((b) => (
                  <tr key={b.id}>
                    <td>
                      <Link to={`/intake/batches/${b.id}`}>{when(b.created_at)}</Link>
                    </td>
                    <td>Upload</td>
                    <td className="num">{b.totals.file_count}</td>
                    {SEGMENTS.map((s) => (
                      <td className="num" key={s.key}>
                        {b.totals[s.key]}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <p className="muted small" style={{ marginTop: 16 }}>
        Email intake (forwarding invoices to an account address) is not built yet.
      </p>
    </>
  );
}

function fileAction(f: BatchFile) {
  const inv = f.invoices[0];
  if (f.displayed_state === "needs review" && inv) return <Link to={`/invoices/${inv.id}/review`}>Review extraction</Link>;
  if (f.displayed_state === "ready" && inv) return <Link to={`/invoices/${inv.id}`}>Open match view</Link>;
  if (f.displayed_state === "duplicate file") return <span className="muted">Same file as one already uploaded</span>;
  return null;
}

/** S-06 batch: totals that add up, per-file state, retry failed only. */
export function BatchPage() {
  const { batchId } = useParams();
  const { can } = useSession();
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["batch", batchId],
    queryFn: () => get<Batch>(`/api/v1/intake/batches/${batchId}`),
    refetchInterval: (query) => {
      const t = query.state.data?.totals;
      return t && t.queued + t.processing > 0 ? 5000 : false;
    },
  });
  usePageTitle("Invoice batch", q.data ? when(q.data.created_at) : null);
  const retry = useMutation({
    mutationFn: () => send<{ requeued: number }>("POST", `/api/v1/intake/batches/${batchId}/retry-failed`),
    onSuccess: (r) => {
      toast(`${plural(r.requeued, "failed file")} queued again.`);
      qc.invalidateQueries({ queryKey: ["batch", batchId] });
    },
  });
  const { pending, busy, start } = useUploader(
    useCallback(() => qc.invalidateQueries({ queryKey: ["batch", batchId] }), [qc, batchId]),
  );
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorState error={q.error} retry={() => q.refetch()} />;
  const b = q.data!;
  const t = b.totals;
  const done = t.queued + t.processing === 0;
  const names = new Map<string, string>();
  (b.files ?? []).forEach((f) => names.set(f.id, f.original_name ?? "file"));
  return (
    <>
      <PageHead
        title={`Batch of ${when(b.created_at)}`}
        crumbs={<Link to="/intake">Invoice intake</Link>}
        actions={
          <>
            {can("upload") && t.failed > 0 && (
              <button className="btn" onClick={() => retry.mutate()} disabled={retry.isPending}>
                Retry failed
              </button>
            )}
            {t.ready > 0 && (
              <Link className="btn primary" to="/exceptions">
                Go to exceptions
              </Link>
            )}
          </>
        }
      />
      <p>{sentence(t)}</p>
      <ThrottledStatus text={sentence(t)} final={done} />
      <TotalsBar totals={t} />
      {t["needs review"] > 0 && (
        <Banner tone="draft">
          <p>
            {plural(t["needs review"], "document")} could not be checked automatically. Open each one and confirm or correct what was read.
          </p>
        </Banner>
      )}
      {can("upload") && <DropZone onFiles={(f) => start(f, batchId)} disabled={busy} />}
      <PendingList pending={pending} />
      <div className="table-wrap" style={{ marginTop: 12 }}>
        <table>
          <thead>
            <tr>
              <th scope="col">File</th>
              <th scope="col">State</th>
              <th scope="col">Supplier</th>
              <th scope="col">Document</th>
              <th scope="col">Next</th>
            </tr>
          </thead>
          <tbody>
            {(b.files ?? []).map((f) => (
              <tr key={f.id}>
                <td>{f.original_name ?? "file"}</td>
                <td>
                  <StatusChip status={f.displayed_state} />
                  {f.failure_code && <div className="error-text">{FAILURE_CODES[f.failure_code] ?? "Could not be read. Try again."}</div>}
                  {f.duplicate_of_document_id && (
                    <div className="muted small">
                      Same as{" "}
                      {f.duplicate_of_invoice_id ? (
                        <Link to={`/invoices/${f.duplicate_of_invoice_id}`}>{names.get(f.duplicate_of_document_id) ?? "the original file"}</Link>
                      ) : (
                        (names.get(f.duplicate_of_document_id) ?? "an earlier file")
                      )}
                    </div>
                  )}
                </td>
                <td>{f.invoices.map((i) => i.vendor_name).filter(Boolean).join(", ") || <span className="muted">Not known yet</span>}</td>
                <td>
                  {f.invoices.map((i) => (
                    <div key={i.id}>
                      {i.doc_type === "credit_note" ? "Credit note " : ""}
                      {i.doc_number ?? "No number read"}
                    </div>
                  ))}
                  {f.invoices.length > 1 && <div className="muted small">{f.invoices.length} documents in this file</div>}
                </td>
                <td>{fileAction(f)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
