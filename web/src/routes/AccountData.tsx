// B9, S-16 (controller): the account's archive (records as CSV and the original files in one ZIP) and
// a request to delete the account, which MatchDesk processes with 30 days' notice (schema.md 8).
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { download, errorText, get, send } from "../api/client";
import type { ArchiveExport, ArchiveSnapshot, DeletionRequest } from "../api/types";
import { useSession } from "../app/session";
import { Banner, Dialog, StatusChip, toast } from "../components/ui";
import { day, plural, when } from "../lib/format";

function size(bytes: number | null): string {
  if (!bytes) return "";
  return bytes > 1_000_000 ? `${(Math.round(bytes / 100_000) / 10).toString()} MB` : `${Math.max(1, Math.round(bytes / 1000))} KB`;
}

/** "Complete: 13/13 originals" or "Incomplete: 12/13 originals" (B10, outside QA item 1). */
export function completenessText(included: number | null | undefined, expected: number | null | undefined): string {
  const inc = included ?? 0;
  const exp = expected ?? 0;
  return `${inc === exp ? "Complete" : "Incomplete"}: ${inc}/${exp} originals`;
}

/** The latest verified archive in words, for the deletion dialog and the operator's row. */
export function archiveSnapshotText(a: ArchiveSnapshot | null | undefined): string {
  if (!a || a.state === "none") return "No archive prepared";
  if (a.state === "failed") return "The last archive could not be built";
  return completenessText(a.included, a.expected);
}

const DELETION_WORD: Record<string, string> = { requested: "Requested", scheduled: "Scheduled", deleting: "Deleting", cancelled: "Cancelled", declined: "Declined", executed: "Deleted" };
const DELETION_TONE: Record<string, string> = { requested: "pending_approval", scheduled: "open", deleting: "running", cancelled: "auto_closed", declined: "auto_closed", executed: "failed" };

export function DeletionStateChip({ status }: { status: DeletionRequest["status"] }) {
  return <StatusChip status={DELETION_TONE[status] ?? "open"} word={DELETION_WORD[status] ?? status} />;
}

export function AccountDataPanel() {
  const { can, tenantName } = useSession();
  const qc = useQueryClient();
  const archives = useQuery({
    queryKey: ["archives"],
    queryFn: () => get<{ items: ArchiveExport[] }>("/api/v1/exports/archive"),
    refetchInterval: (q) => (q.state.data?.items.some((a) => a.status === "queued" || a.status === "running") ? 2000 : false),
  });
  const deletion = useQuery({
    queryKey: ["deletion-request"],
    queryFn: () => get<{ request: DeletionRequest | null; notice_days: number; archive?: ArchiveSnapshot }>("/api/v1/account/deletion-request"),
    refetchInterval: (q) => (q.state.data?.request?.status === "deleting" ? 3000 : false),
  });
  const retry = useMutation({
    mutationFn: (a: ArchiveExport) => send<ArchiveExport>("POST", `/api/v1/exports/archive/${a.id}/retry`, {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["archives"] });
      qc.invalidateQueries({ queryKey: ["deletion-request"] });
      toast("Reading the missing files again. The archive is rebuilt when they are read.");
    },
  });
  const [ack, setAck] = useState(false);
  const build = useMutation({
    mutationFn: () => send<ArchiveExport>("POST", "/api/v1/exports/archive", {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["archives"] });
      toast("Preparing the archive. It appears here when it is ready.");
    },
  });
  const [askOpen, setAskOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [typed, setTyped] = useState("");
  const ask = useMutation({
    mutationFn: () => send("POST", "/api/v1/account/deletion-requests", { reason: reason.trim() || null, confirm_name: typed, acknowledge_incomplete_archive: ack }),
    onSuccess: () => {
      setAskOpen(false);
      setTyped("");
      qc.invalidateQueries({ queryKey: ["deletion-request"] });
      toast("Deletion requested. MatchDesk will confirm the date.");
    },
  });
  const cancel = useMutation({
    mutationFn: (r: DeletionRequest) => send("POST", `/api/v1/account/deletion-requests/${r.id}/cancel`, {}, { ifMatch: r.version }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["deletion-request"] });
      toast("Deletion request cancelled. Nothing will be deleted.");
    },
  });
  if (!can("request_deletion_or_archive")) return null;
  const latest = archives.data?.items[0];
  const req = deletion.data?.request;
  const open = req && (req.status === "requested" || req.status === "scheduled" || req.status === "deleting");
  const snapshot = deletion.data?.archive;
  const archiveComplete = snapshot?.state === "complete";
  const built = latest && (latest.status === "ready" || latest.status === "incomplete");
  return (
    <section className="panel" aria-labelledby="data-h">
      <div className="panel-head">
        <h2 id="data-h">Account data</h2>
      </div>
      <div className="panel-body stack">
        <div className="data-row">
          <div>
            <h3>Archive of this account</h3>
            <p className="muted small">
              One ZIP: every invoice, receiving file and credit note as uploaded, with CSV files of invoices, lines, exceptions, receiving records, reports,
              findings and the audit log. Available for 24 hours after it is ready.
            </p>
            {latest && (
              <p className="small" role="status" data-testid="archive-state">
                <StatusChip
                  status={latest.status === "ready" ? "succeeded" : latest.status === "incomplete" || latest.status === "failed" ? "failed" : latest.status === "expired" ? "auto_closed" : "running"}
                  word={latest.status === "ready" ? "Ready" : latest.status === "incomplete" ? "Incomplete" : latest.status === "expired" ? "Expired" : latest.status === "failed" ? "Failed" : "Preparing…"}
                />{" "}
                {built
                  ? `${completenessText(latest.included_count ?? latest.file_count, latest.expected_count ?? latest.file_count)}, ${size(latest.byte_size)}; available until ${when(latest.expires_at)}.`
                  : latest.status === "expired" && latest.expected_count !== null
                    ? `${completenessText(latest.included_count, latest.expected_count)}; no longer available.`
                    : `Asked ${when(latest.requested_at)}.`}
              </p>
            )}
            {latest?.status === "incomplete" && (
              <Banner tone="error">
                <p>
                  {plural(latest.missing_count ?? 0, "original file")} could not be read and {latest.missing_count === 1 ? "is" : "are"} marked missing in documents.csv. This archive is not a complete copy of the account.
                </p>
              </Banner>
            )}
          </div>
          <div className="actions">
            {latest?.status === "incomplete" && (
              <button className="btn primary" disabled={retry.isPending} onClick={() => retry.mutate(latest)}>
                Retry missing files
              </button>
            )}
            {latest?.downloadable && (
              <button className={`btn ${latest.status === "incomplete" ? "" : "primary"}`} onClick={() => download(`/api/v1/exports/archive/${latest.id}/content`, "matchdesk-archive.zip").catch((e) => toast(errorText(e)))}>
                {latest.status === "incomplete" ? "Download the incomplete archive" : "Download the archive"}
              </button>
            )}
            <button className="btn" disabled={build.isPending || latest?.status === "queued" || latest?.status === "running"} onClick={() => build.mutate()}>
              {latest?.downloadable ? "Prepare a new archive" : "Prepare an archive"}
            </button>
          </div>
        </div>
        <div className="data-row">
          <div>
            <h3>Delete this account</h3>
            {open ? (
              <Banner tone={req.status === "deleting" ? "error" : "warn"}>
                <p>
                  <DeletionStateChip status={req.status} />{" "}
                  {req.status === "deleting"
                    ? "Deleting now: the files of this account are being removed. It can no longer be cancelled."
                    : req.status === "requested"
                    ? `Deletion requested on ${day(req.requested_at)}. MatchDesk will set the date, at least ${deletion.data?.notice_days ?? 30} days ahead.`
                    : `Scheduled: every document, report and audit event of this account will be deleted on ${day(req.delete_after)}.`}{" "}
                  {req.status !== "deleting" && " Download the archive, the approved reports and the audit log before then."}
                </p>
                {req.archive && <p className="small">Archive when last checked: {archiveSnapshotText(req.archive)}{req.archive.acknowledged ? " (deletion acknowledged without a complete archive)" : ""}.</p>}
              </Banner>
            ) : (
              <p className="muted small">
                Removes every document, record, approved report and audit event of this account after {deletion.data?.notice_days ?? 30} days&apos; notice.
                MatchDesk keeps only a record that the account was deleted. Backups expire within 56 days.
                {req && req.status === "declined" ? ` The last request was declined${req.decision_note ? `: ${req.decision_note}` : ""}.` : ""}
                {req && req.status === "cancelled" ? ` The last request was cancelled on ${day(req.cancelled_at ?? req.requested_at)}; nothing was deleted.` : ""}
              </p>
            )}
          </div>
          <div className="actions">
            {open ? (
              req.status !== "deleting" && (
                <button className="btn" disabled={cancel.isPending} onClick={() => cancel.mutate(req)}>
                  Cancel the deletion
                </button>
              )
            ) : (
              <button className="btn danger" onClick={() => setAskOpen(true)}>
                Request deletion
              </button>
            )}
          </div>
        </div>
      </div>
      <Dialog
        open={askOpen}
        title="Request deletion of this account"
        description="MatchDesk schedules it with 30 days' notice. You can cancel until then."
        onClose={() => {
          setAskOpen(false);
          setAck(false);
        }}
        footer={
          <>
            <button className="btn" data-safe onClick={() => setAskOpen(false)}>
              Keep the account
            </button>
            <button className="btn danger" disabled={ask.isPending || typed.trim().toLowerCase() !== (tenantName ?? "").trim().toLowerCase() || (!archiveComplete && !ack)} onClick={() => ask.mutate()}>
              Request deletion
            </button>
          </>
        }
      >
        <p>Approved reports and the audit log are deleted with the account. Download the archive first.</p>
        <p className="small" data-testid="dialog-archive">
          Latest archive: <strong>{archiveSnapshotText(snapshot)}</strong>
          {snapshot?.checked_at ? `, checked ${when(snapshot.checked_at)}` : ""}.
        </p>
        {!archiveComplete && (
          <Banner tone="error">
            <p>No complete archive of this account exists. After deletion, missing originals cannot be recovered.</p>
            <label className="check">
              <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} /> I understand the account will be deleted without a complete archive.
            </label>
          </Banner>
        )}
        <div className="field">
          <label htmlFor="del-reason">Reason (optional)</label>
          <textarea id="del-reason" rows={2} value={reason} maxLength={2000} onChange={(e) => setReason(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="del-name">Type the account name to confirm: {tenantName}</label>
          <input id="del-name" value={typed} autoComplete="off" onChange={(e) => setTyped(e.target.value)} />
        </div>
        {ask.error && <p className="error-text">{errorText(ask.error)}</p>}
      </Dialog>
    </section>
  );
}
