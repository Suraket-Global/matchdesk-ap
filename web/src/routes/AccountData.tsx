// B9, S-16 (controller): the account's archive (records as CSV and the original files in one ZIP) and
// a request to delete the account, which MatchDesk processes with 30 days' notice (schema.md 8).
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { download, errorText, get, send } from "../api/client";
import type { ArchiveExport, DeletionRequest } from "../api/types";
import { useSession } from "../app/session";
import { Banner, Dialog, StatusChip, toast } from "../components/ui";
import { day, plural, when } from "../lib/format";

function size(bytes: number | null): string {
  if (!bytes) return "";
  return bytes > 1_000_000 ? `${(Math.round(bytes / 100_000) / 10).toString()} MB` : `${Math.max(1, Math.round(bytes / 1000))} KB`;
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
    queryFn: () => get<{ request: DeletionRequest | null; notice_days: number }>("/api/v1/account/deletion-request"),
  });
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
    mutationFn: () => send("POST", "/api/v1/account/deletion-requests", { reason: reason.trim() || null, confirm_name: typed }),
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
  const open = req && (req.status === "requested" || req.status === "scheduled");
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
              <p className="small" role="status">
                <StatusChip status={latest.status === "ready" ? "succeeded" : latest.status === "failed" ? "failed" : latest.status === "expired" ? "auto_closed" : "running"} word={latest.status === "ready" ? "Ready" : latest.status === "expired" ? "Expired" : latest.status === "failed" ? "Failed" : "Preparing…"} />{" "}
                {latest.status === "ready"
                  ? `${plural(latest.file_count ?? 0, "original file")}, ${size(latest.byte_size)}; available until ${when(latest.expires_at)}.`
                  : `Asked ${when(latest.requested_at)}.`}
              </p>
            )}
          </div>
          <div className="actions">
            {latest?.downloadable && (
              <button className="btn primary" onClick={() => download(`/api/v1/exports/archive/${latest.id}/content`, "matchdesk-archive.zip").catch((e) => toast(errorText(e)))}>
                Download the archive
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
              <Banner tone="warn">
                <p>
                  {req.status === "requested"
                    ? `Deletion requested on ${day(req.requested_at)}. MatchDesk will set the date, at least ${deletion.data?.notice_days ?? 30} days ahead.`
                    : `Scheduled: every document, report and audit event of this account will be deleted on ${day(req.delete_after)}.`}{" "}
                  Download the archive, the approved reports and the audit log before then.
                </p>
              </Banner>
            ) : (
              <p className="muted small">
                Removes every document, record, approved report and audit event of this account after {deletion.data?.notice_days ?? 30} days&apos; notice.
                MatchDesk keeps only a record that the account was deleted. Backups expire within 56 days.
                {req && req.status === "declined" ? ` The last request was declined${req.decision_note ? `: ${req.decision_note}` : ""}.` : ""}
              </p>
            )}
          </div>
          <div className="actions">
            {open ? (
              <button className="btn" disabled={cancel.isPending} onClick={() => cancel.mutate(req)}>
                Cancel the deletion
              </button>
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
        onClose={() => setAskOpen(false)}
        footer={
          <>
            <button className="btn" data-safe onClick={() => setAskOpen(false)}>
              Keep the account
            </button>
            <button className="btn danger" disabled={ask.isPending || typed.trim().toLowerCase() !== (tenantName ?? "").trim().toLowerCase()} onClick={() => ask.mutate()}>
              Request deletion
            </button>
          </>
        }
      >
        <p>Approved reports and the audit log are deleted with the account. Download the archive first.</p>
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
