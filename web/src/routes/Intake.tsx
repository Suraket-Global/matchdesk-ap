import { useCallback, useState } from "react";
import { CheckCircle2, FileText, Inbox, Mail, RotateCw, Trash2, XCircle } from "lucide-react";
import { FileDropzone } from "../components/FileDropzone";
import { TableSkeleton } from "../components/States";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, errorText, get, newKey, send, upload } from "../api/client";
import type { Batch, BatchFile, BatchTotals, IntakeEmail, Page } from "../api/types";
import { useSession } from "../app/session";
import { Banner, Dialog, Empty, ErrorState, Loading, PageHead, StatusChip, ThrottledStatus, toast, usePageTitle } from "../components/ui";
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
  // "Reading" only while files are in progress; afterwards the totals alone (B6 review minor).
  if (!inProgress) return `${plural(t.file_count, "file")} read: ${parts.join(", ")}.`;
  return `Reading ${plural(t.file_count, "file")}. ${parts.join(", ")}, ${inProgress} still in progress. You can leave this page; nothing will be lost.`;
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
        toast(errorText(err), "error");
      } finally {
        setBusy(false);
      }
    },
    [onDone, qc],
  );
  return { pending, busy, start };
}

function DropZone({ onFiles, disabled }: { onFiles: (f: File[]) => void; disabled: boolean }) {
  return (
    <FileDropzone
      title="Drop invoice and credit-note files here"
      hint="PDF, PNG or JPEG, up to 20 MB each and 500 per batch. The same file twice becomes one document."
      accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg"
      disabled={disabled}
      onFiles={(files) => files.length && onFiles(files)}
    />
  );
}

const PENDING_WORD: Record<Pending["state"], string> = { waiting: "Waiting", uploading: "Uploading", received: "Received", refused: "Refused" };

function PendingList({ pending }: { pending: Pending[] }) {
  if (!pending.length) return null;
  const received = pending.filter((p) => p.state === "received").length;
  const sendable = pending.filter((p) => p.state !== "refused").length;
  return (
    <section className="panel" aria-labelledby="upload-h">
      <div className="panel-head">
        <h2 id="upload-h">Uploading</h2>
        <span role="status" aria-live="polite" className="muted">
          {received} of {sendable} received
        </span>
      </div>
      <div className="progress ok" style={{ margin: "0 20px" }} aria-hidden="true">
        <span style={{ width: `${sendable ? (received / sendable) * 100 : 0}%` }} />
      </div>
      <ul className="file-rows">
        {pending.map((p, i) => (
          <li key={i} className="file-row">
            <span className="ficon" aria-hidden="true">
              {p.state === "received" ? <CheckCircle2 size={18} color="var(--success-solid)" /> : p.state === "refused" ? <XCircle size={18} color="var(--danger-solid)" /> : <FileText size={18} />}
            </span>
            <span className="fname" title={p.name}>
              {p.name}
              {p.reason && <span className="cell-sub error-text">{p.reason}</span>}
            </span>
            <span className={`progress ${p.state === "refused" ? "bad" : p.state === "received" ? "ok" : ""}`} aria-hidden="true">
              <span style={{ width: p.state === "waiting" ? "0%" : p.state === "uploading" ? "55%" : "100%" }} />
            </span>
            <span className="small muted" style={{ minWidth: 70, textAlign: "right" }}>
              {PENDING_WORD[p.state]}
            </span>
          </li>
        ))}
      </ul>
    </section>
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
      {can("upload") && <DropZone onFiles={(f) => start(f)} disabled={busy} />}
      <PendingList pending={pending} />
      <section aria-labelledby="batches-h">
        <h2 id="batches-h" style={{ margin: "8px 0 12px" }}>
          Batches
        </h2>
        {batches.isLoading && <TableSkeleton />}
        {batches.error && <ErrorState error={batches.error} retry={() => batches.refetch()} />}
        {batches.data && items.length === 0 && (
          <div className="panel">
            <Empty title="No invoices uploaded yet" icon={<Inbox size={22} />}>
              <p>Drop the month&apos;s invoice PDFs above, or forward them by email to your intake address.</p>
            </Empty>
          </div>
        )}
        {items.length > 0 && (
          <div className="table-wrap">
            <table className="stack-sm">
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
                    <td data-label="Uploaded">
                      <Link to={`/intake/batches/${b.id}`}>{when(b.created_at)}</Link>
                    </td>
                    <td data-label="Source">{b.source === "email" ? "Email" : "Upload"}</td>
                    <td className="num" data-label="Files">{b.totals.file_count}</td>
                    {SEGMENTS.map((s) => (
                      <td className="num" key={s.key} data-label={s.label}>
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
      <EmailIntake />
    </>
  );
}

function fileAction(f: BatchFile, primary = false) {
  const inv = f.invoices[0];
  if (f.displayed_state === "needs review" && inv)
    return (
      <Link className={primary ? "btn small primary" : undefined} to={`/invoices/${inv.id}/review`}>
        Review extraction
      </Link>
    );
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
      toast(`${plural(r.requeued, "failed file")} queued again.`, "info");
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
  const byState = (st: string) => (b.files ?? []).filter((f) => f.displayed_state === st);
  return (
    <>
      <PageHead
        title={`Batch of ${when(b.created_at)}`}
        crumbs={<Link to="/intake">Invoice intake</Link>}
        actions={
          <>
            {can("upload") && t.failed > 0 && (
              <button className="btn" onClick={() => retry.mutate()} disabled={retry.isPending}>
                <RotateCw size={16} aria-hidden="true" />
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
      <p className="muted">{sentence(t)}</p>
      <ThrottledStatus text={sentence(t)} final={done} />
      <TotalsBar totals={t} />
      {!done || !(b.files ?? []).length ? (
        <>
          {can("upload") && <DropZone onFiles={(f) => start(f, batchId)} disabled={busy} />}
          <PendingList pending={pending} />
          <FileTable files={b.files ?? []} names={names} caption="Files in this batch" />
        </>
      ) : (
        <>
          {/* B8: once the batch is read, the work comes first; ready files and provenance stay a click away. */}
          {byState("needs review").length > 0 ? (
            <section className="batch-lead" aria-labelledby="todo-h">
              <h2 id="todo-h">
                Review {plural(byState("needs review").length, "invoice")}
              </h2>
              <p className="muted">These could not be checked automatically. Open each one and confirm or correct what was read.</p>
              <FileTable files={byState("needs review")} names={names} caption="Invoices to review" primary />
            </section>
          ) : (
            <Banner tone="ok">Every file in this batch is read. Nothing needs review.</Banner>
          )}
          {byState("failed").length > 0 && (
            <section className="batch-group" aria-labelledby="failed-h">
              <h2 id="failed-h">{plural(byState("failed").length, "file")} could not be read</h2>
              <FileTable files={byState("failed")} names={names} caption="Files that failed" />
            </section>
          )}
          {byState("duplicate file").length > 0 && (
            <section className="batch-group" aria-labelledby="dup-h">
              <h2 id="dup-h">{plural(byState("duplicate file").length, "duplicate file")}</h2>
              <p className="muted small">Byte-identical to a file already uploaded; not read again and not counted.</p>
              <FileTable files={byState("duplicate file")} names={names} caption="Duplicate files" />
            </section>
          )}
          <details className="panel fold">
            <summary>
              {plural(byState("ready").length, "file")} ready and matched
            </summary>
            <FileTable files={byState("ready")} names={names} caption="Ready files" />
          </details>
          {can("upload") && (
            <details className="panel fold">
              <summary>Add files to this batch</summary>
              <div className="panel-body">
                <DropZone onFiles={(f) => start(f, batchId)} disabled={busy} />
                <PendingList pending={pending} />
              </div>
            </details>
          )}
        </>
      )}
    </>
  );
}

/** The files of a batch with their state, supplier, document and next step. */
function FileTable({ files, names, caption, primary = false }: { files: BatchFile[]; names: Map<string, string>; caption: string; primary?: boolean }) {
  if (!files.length) return <p className="muted panel-body">None.</p>;
  return (
      <div className="table-wrap">
        <table className="stack-sm">
          <caption className="sr-only">{caption}</caption>
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
            {[...files]
              .sort((x, y) => (x.original_name ?? "").localeCompare(y.original_name ?? "", undefined, { numeric: true }) || x.id.localeCompare(y.id))
              .map((f) => (
              <tr key={f.id}>
                <td data-label="File">
                  <span className="cell-main">{f.original_name ?? "file"}</span>
                </td>
                <td data-label="State">
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
                <td data-label="Supplier">
                  {[...new Set(f.invoices.map((i) => i.vendor_name).filter(Boolean))].join(", ") || (
                    <span className="muted">
                      {f.duplicate_of_document_id ? "See the original file" : f.displayed_state === "queued" || f.displayed_state === "processing" ? "Not read yet" : "Not identified"}
                    </span>
                  )}
                </td>
                <td data-label="Document">
                  {f.invoices.map((i) => (
                    <div key={i.id}>
                      {i.doc_type === "credit_note" ? "Credit note " : ""}
                      {i.doc_number ?? "No number read"}
                    </div>
                  ))}
                  {f.invoices.length > 1 && <div className="muted small">{f.invoices.length} documents in this file</div>}
                </td>
                <td data-label="Next">{fileAction(f, primary)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
  );
}

/** S-06 email intake (T-3.3.4): the account's address, who may send to it, and messages held for a person. */
function EmailIntake() {
  const { can } = useSession();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["intake-email"], queryFn: () => get<IntakeEmail>("/api/v1/intake/email"), refetchInterval: 15_000 });
  const [sender, setSender] = useState("");
  const [discard, setDiscard] = useState<IntakeEmail["messages"][number] | null>(null);
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["intake-email"] });
    qc.invalidateQueries({ queryKey: ["batches"] });
  };
  const add = useMutation({
    mutationFn: () => send("POST", "/api/v1/intake/senders", { address_or_domain: sender }),
    onSuccess: () => {
      setSender("");
      refresh();
      toast("Sender allowed. Their next emailed invoices go straight into a batch.", "success");
    },
  });
  const remove = useMutation({
    mutationFn: (id: string) => send("DELETE", `/api/v1/intake/senders/${id}`),
    onSuccess: refresh,
  });
  const decide = useMutation({
    mutationFn: (x: { id: string; decision: string }) => send<{ batch_id: string | null; status: string }>("POST", `/api/v1/intake/messages/${x.id}/decision`, { decision: x.decision }),
    onSuccess: (r) => {
      setDiscard(null);
      refresh();
      toast(r.status === "processed" ? "Released: its attachments are in a new batch." : "Discarded. Nothing was imported.", "success");
    },
  });
  const d = q.data;
  if (!d) return null;
  const held = d.messages.filter((m) => m.status === "held");
  const recent = d.messages.filter((m) => m.status !== "held").slice(0, 8);
  return (
    <section className="panel email-intake" aria-labelledby="email-h" style={{ marginTop: 16 }}>
      <div className="panel-head">
        <h2 id="email-h">
          <Mail size={17} aria-hidden="true" style={{ verticalAlign: "-3px", marginRight: 8 }} />
          Invoices by email
        </h2>
      </div>
      <div className="panel-body stack">
        <p style={{ margin: 0 }}>
          Suppliers or your team can email invoices to{" "}
          {d.address ? <strong className="mono-address">{d.address}</strong> : <span className="muted">an address MatchDesk sets up for you</span>}. PDF, PNG and
          JPEG attachments from an allowed sender go straight into a batch; anything else waits here for you.
        </p>
        <div>
          <h3 className="small-head">Allowed senders</h3>
          {d.senders.length ? (
            <ul className="chips">
              {d.senders.map((s) => (
                <li key={s.id}>
                  {s.address_or_domain}
                  {can("edit_intake_settings") && (
                    <button className="btn ghost icon-btn sm" aria-label={`Remove ${s.address_or_domain}`} onClick={() => remove.mutate(s.id)}>
                      <Trash2 size={14} aria-hidden="true" />
                    </button>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">None yet: every message is held for a person.</p>
          )}
          {can("edit_intake_settings") && (
            <form
              className="inline-form"
              style={{ marginTop: 8 }}
              onSubmit={(e) => {
                e.preventDefault();
                if (sender.trim()) add.mutate();
              }}
            >
              <div className="field">
                <label htmlFor="sender">Allow an address or a whole domain</label>
                <input id="sender" placeholder="billing@supplier.example or @supplier.example" value={sender} onChange={(e) => setSender(e.target.value)} />
              </div>
              <button className="btn" type="submit" disabled={add.isPending || !sender.trim()}>
                Allow sender
              </button>
              {add.error && <span className="error-text">{errorText(add.error)}</span>}
            </form>
          )}
        </div>
        <div>
          <h3 className="small-head">Held for you ({held.length})</h3>
          {held.length === 0 ? (
            <p className="muted">Nothing is waiting.</p>
          ) : (
            <div className="table-wrap">
              <table className="compact stack-sm">
                <caption className="sr-only">Held emails</caption>
                <thead>
                  <tr>
                    <th scope="col">From</th>
                    <th scope="col">Subject</th>
                    <th scope="col" className="num">Attachments</th>
                    <th scope="col">Received</th>
                    <th scope="col">
                      <span className="sr-only">Actions</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {held.map((m) => (
                    <tr key={m.id}>
                      <td data-label="From">{m.from_address}</td>
                      <td data-label="Subject">{m.subject ?? <span className="muted">No subject</span>}</td>
                      <td className="num" data-label="Attachments">{m.attachment_count}</td>
                      <td data-label="Received">{when(m.received_at)}</td>
                      <td data-label="Actions">
                        {can("release_held_email") && (
                          <span className="row-actions">
                            <button className="btn small" onClick={() => setDiscard(m)}>
                              Discard
                            </button>
                            <button className="btn small primary" disabled={decide.isPending} onClick={() => decide.mutate({ id: m.id, decision: "release" })}>
                              Release into a batch
                            </button>
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
        {recent.length > 0 && (
          <details>
            <summary className="small">Recent emails ({recent.length})</summary>
            <ul className="plain-list small" style={{ marginTop: 8 }}>
              {recent.map((m) => (
                <li key={m.id}>
                  <StatusChip status={m.status} /> {m.from_address}, {when(m.received_at)}
                  {m.batch_id && (
                    <>
                      {" "}
                      <Link to={`/intake/batches/${m.batch_id}`}>open its batch</Link>
                    </>
                  )}
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>
      <Dialog
        open={!!discard}
        title="Discard this email?"
        onClose={() => setDiscard(null)}
        footer={
          <>
            <button className="btn" data-safe onClick={() => setDiscard(null)}>
              Cancel
            </button>
            <button className="btn danger" disabled={decide.isPending} onClick={() => discard && decide.mutate({ id: discard.id, decision: "discard" })}>
              Discard
            </button>
          </>
        }
      >
        <p>
          Nothing from {discard?.from_address} is imported. The message itself is deleted after 7 days.
        </p>
      </Dialog>
    </section>
  );
}
