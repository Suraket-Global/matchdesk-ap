// B9, S-09: the controller's own decisions on a possible duplicate and on a possible credit (MH-08,
// MH-09), and who is assigned to the exception. Each decision is its own server call; until it is
// made the amount is listed as undecided, never as a finding.
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { errorText, get, send } from "../api/client";
import type { ExceptionItem, Member } from "../api/types";
import { useSession } from "../app/session";
import { toast } from "../components/ui";
import { cad } from "../lib/decimal";
import { day } from "../lib/format";

type Detail = ExceptionItem;

export function useExceptionDetail(id: string | undefined) {
  return useQuery({ queryKey: ["exception", id], queryFn: () => get<Detail>(`/api/v1/exceptions/${id}`), enabled: !!id });
}

/** True when the controller's decision replaces the ordinary resolution codes for this exception. */
export function decidedByController(e: ExceptionItem): boolean {
  return e.status === "open" && (e.type === "possible_duplicate" || e.possibly_credited);
}

function useDecision(e: ExceptionItem, onDone: () => void) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { path: "credit-decision" | "duplicate-decision"; decision: string; note: string }) =>
      send<ExceptionItem>("POST", `/api/v1/exceptions/${e.id}/${v.path}`, { decision: v.decision, note: v.note.trim() || null }, { ifMatch: e.version }),
    onSuccess: (_r, v) => {
      qc.invalidateQueries({ queryKey: ["exceptions"] });
      qc.invalidateQueries({ queryKey: ["exception", e.id] });
      qc.invalidateQueries({ queryKey: ["invoice"] });
      const words: Record<string, string> = {
        credited: "Recorded: credited. Matching again; this exception nets with that credit.",
        not_credited: "Recorded: not credited. Matching again; it is a finding again.",
        is_duplicate: "Recorded: is a duplicate. Matching again; the document is counted once.",
        not_duplicate: "Recorded: not a duplicate. Matching again.",
      };
      toast(words[v.decision] ?? "Recorded.");
      onDone();
    },
  });
}

export function ControllerDecision({ exc, detail, onDone }: { exc: ExceptionItem; detail?: Detail; onDone: () => void }) {
  const { can } = useSession();
  const [note, setNote] = useState("");
  const decide = useDecision(exc, onDone);
  const credit = exc.possibly_credited;
  const bill = detail?.credit_bill;
  const may = can("decide_duplicate_or_credit");
  const options = credit
    ? [
        { decision: "credited", label: "Credited", what: "This exception nets with that one QuickBooks credit and leaves the findings. The credit cannot net a second exception." },
        { decision: "not_credited", label: "Not credited", what: "The flag is cleared: this exception is a finding again and that credit never flags it again." },
      ]
    : [
        { decision: "is_duplicate", label: "Is a duplicate", what: "The document is treated as a duplicate: its total is a finding once and its line exceptions close." },
        { decision: "not_duplicate", label: "Not a duplicate", what: "The document is matched as its own invoice; the possible-duplicate flag is closed." },
      ];
  return (
    <div className="ctl-decision" role="group" aria-label={credit ? "Credit decision" : "Duplicate decision"}>
      <div className="consequence" role="note">
        <strong>{credit ? "Possibly credited in QuickBooks" : "Possible duplicate"}</strong>
        <p>
          {credit
            ? `A QuickBooks vendor credit${bill?.doc_number ? ` ${bill.doc_number}` : ""}${bill?.total ? ` of ${cad(bill.total)}` : ""}${bill?.txn_date ? ` dated ${day(bill.txn_date)}` : ""} matches this supplier and a similar amount but names no invoice or line. `
            : "Another document from this supplier has the same total within 7 days but a different number. "}
          It is listed as undecided, not as a finding, until the controller decides.
        </p>
      </div>
      {may ? (
        <>
          <div className="field">
            <label htmlFor="decision-note">Note (optional)</label>
            <textarea id="decision-note" rows={2} value={note} maxLength={2000} onChange={(e) => setNote(e.target.value)} />
          </div>
          <div className="decision-buttons">
            {options.map((o) => (
              <button
                key={o.decision}
                className="btn"
                disabled={decide.isPending}
                title={o.what}
                onClick={() => decide.mutate({ path: credit ? "credit-decision" : "duplicate-decision", decision: o.decision, note })}
              >
                {o.label}
              </button>
            ))}
          </div>
          <ul className="plain-list small muted">
            {options.map((o) => (
              <li key={o.decision}>
                <strong>{o.label}:</strong> {o.what}
              </li>
            ))}
          </ul>
          {decide.error && <p className="error-text">{errorText(decide.error)}</p>}
        </>
      ) : (
        <p className="muted small">Waiting for the controller&apos;s decision.</p>
      )}
    </div>
  );
}

export function Assignee({ exc, detail }: { exc: ExceptionItem; detail?: Detail }) {
  const { can } = useSession();
  const qc = useQueryClient();
  const members = useQuery({ queryKey: ["members"], queryFn: () => get<{ items: Member[]; me: string }>("/api/v1/members") });
  const assign = useMutation({
    mutationFn: (to: string) => send<Detail>("PUT", `/api/v1/exceptions/${exc.id}/assignment`, { user_id: to || null }, { ifMatch: detail?.version ?? exc.version }),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["exceptions"] });
      qc.invalidateQueries({ queryKey: ["exception", exc.id] });
      qc.invalidateQueries({ queryKey: ["invoice"] });
      toast(r.assigned_to ? `Assigned to ${r.assigned_to === members.data?.me ? "you" : r.assigned_to_name ?? "a member"}.` : "Unassigned.");
    },
  });
  const current = detail?.assigned_to ?? exc.assigned_to ?? "";
  if (!can("assign_exception"))
    return current ? <p className="muted small">Assigned to {detail?.assigned_to_name ?? "a member"}.</p> : null;
  return (
    <div className="field assignee-field">
      <label htmlFor="assignee">Assigned to</label>
      <select id="assignee" value={current} disabled={assign.isPending || !detail} onChange={(e) => assign.mutate(e.target.value)}>
        <option value="">Nobody</option>
        {(members.data?.items ?? []).map((m) => (
          <option key={m.user_id} value={m.user_id}>
            {m.user_id === members.data?.me ? `Me (${m.name ?? "you"})` : m.name ?? "Member"}
          </option>
        ))}
      </select>
      {assign.error && <span className="error-text">{errorText(assign.error)}</span>}
    </div>
  );
}
