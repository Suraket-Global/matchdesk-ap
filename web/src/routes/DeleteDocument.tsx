import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { errorText, get, send } from "../api/client";
import type { DocumentDeletionResult, DocumentDeletionRule } from "../api/types";
import { useSession } from "../app/session";
import { Banner, Dialog, toast } from "../components/ui";

/** "Delete document" on S-06 and S-07 (B12). A document no one accepted yet: a clerk or the
 * controller, reason optional. A document already accepted into matching: the controller, with a
 * reason. The server decides; the dialog says beforehand what the deletion does. */
export function DeleteDocument({
  documentId,
  name,
  small,
  onDeleted,
}: {
  documentId: string;
  name: string;
  small?: boolean;
  onDeleted?: (r: DocumentDeletionResult) => void;
}) {
  const { can, role } = useSession();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const rule = useQuery({
    queryKey: ["document-deletion", documentId],
    queryFn: () => get<DocumentDeletionRule>(`/api/v1/documents/${documentId}/deletion`),
    enabled: open,
  });
  const del = useMutation({
    mutationFn: () =>
      send<DocumentDeletionResult>("POST", `/api/v1/documents/${documentId}/deletion-requests`, {
        reason: reason.trim() || null,
      }),
    onSuccess: (r) => {
      setOpen(false);
      setReason("");
      toast(
        r.match_run_id
          ? `Deleted ${name}. The supplier's other documents are being matched again.`
          : `Deleted ${name}.`,
        "success",
      );
      qc.invalidateQueries();
      onDeleted?.(r);
    },
  });
  if (!can("delete_document")) return null;
  const r = rule.data;
  const needsController = !!r?.needs_controller && role !== "controller";
  const reasonMissing = !!r?.reason_required && reason.trim().length === 0;
  const close = () => {
    setOpen(false);
    del.reset();
  };
  return (
    <>
      <button type="button" className={`btn ghost danger-text${small ? " small" : ""}`} onClick={() => setOpen(true)}>
        <Trash2 size={14} aria-hidden="true" /> Delete document
      </button>
      <Dialog
        open={open}
        title={`Delete ${name}?`}
        description="The document leaves matching, the queue and new reports. Its history stays in the audit log."
        onClose={close}
        footer={
          <>
            <button className="btn" data-safe onClick={close}>
              Keep the document
            </button>
            <button
              className="btn danger"
              disabled={!r || !!r.blocked || needsController || reasonMissing || del.isPending}
              onClick={() => del.mutate()}
            >
              {del.isPending ? "Deleting…" : "Delete document"}
            </button>
          </>
        }
      >
        {rule.isLoading && <p className="muted">Checking what this deletion needs…</p>}
        {rule.error && <p className="error-text">{errorText(rule.error)}</p>}
        {r?.blocked && <Banner tone="warn">{r.blocked}</Banner>}
        {r && !r.blocked && (
          <>
            <ul className="plain-list small" style={{ marginBottom: "var(--s-4)" }}>
              <li>Its lines lose their current match result; earlier results are kept as history.</li>
              <li>Its exceptions close. Every other document from the same supplier is matched again without it.</li>
              <li>An approved report that included it does not change. A later draft lists it as deleted after approval.</li>
              <li>The original file is kept until the account is deleted, and the archive lists it as deleted.</li>
            </ul>
            {r.accepted && (
              <Banner tone={needsController ? "error" : "warn"}>
                {needsController
                  ? "This document was already accepted into matching, so only your controller can delete it, with a reason."
                  : "This document was already accepted into matching. Say why it is being deleted; the reason goes into the audit log."}
              </Banner>
            )}
            {!needsController && (
              <div className="field">
                <label htmlFor={`del-doc-reason-${documentId}`}>
                  Reason{r.reason_required ? "" : " (optional)"}
                </label>
                <textarea
                  id={`del-doc-reason-${documentId}`}
                  rows={2}
                  maxLength={500}
                  value={reason}
                  aria-required={r.reason_required}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder="For example: uploaded twice, or belongs to another company"
                />
              </div>
            )}
          </>
        )}
        {del.error && <p className="error-text">{errorText(del.error)}</p>}
      </Dialog>
    </>
  );
}
