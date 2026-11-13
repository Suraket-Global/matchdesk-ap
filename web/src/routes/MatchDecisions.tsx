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
      toast(words[v.decision] ?? "Recorded.", "success");
      onDone();
    },
  });
}

/** The money a decision is about: the amount counted for the line, else its variance. */
function decisionAmount(e: ExceptionItem): string | null {
  return e.reported_amount ?? e.variance_amount ?? null;
}

/** What the chosen decision does to the money, in one sentence (B10, outside QA item 11). */
export function decisionEffect(decision: string, e: ExceptionItem, creditRef: string | null): string {
  const amount = decisionAmount(e);
  const a = amount ? cad(amount) : "The amount";
  const ref = creditRef ?? "that QuickBooks credit";
  switch (decision) {
    case "credited":
      return `Credited: ${a} nets against ${ref} and leaves the findings. ${ref} cannot net a second exception.`;
    case "not_credited":
      return `Not credited: ${a} is a finding again, and ${ref} never flags this exception again.`;
    case "is_duplicate":
      return `Is a duplicate: the document's total${amount ? ` (${a})` : ""} is a finding once and its line exceptions close.`;
    case "not_duplicate":
      return `Not a duplicate: the document is matched as its own invoice; ${a} is not counted as a duplicate.`;
    default:
      return "";
  }
}

export function ControllerDecision({ exc, detail, onDone }: { exc: ExceptionItem; detail?: Detail; onDone: () => void }) {
  const { can } = useSession();
  const [note, setNote] = useState("");
  const [choice, setChoice] = useState<string | null>(null);
  const decide = useDecision(exc, onDone);
  const credit = exc.possibly_credited;
  const bill = detail?.credit_bill;
  const may = can("decide_duplicate_or_credit");
  const d = detail ?? exc;
  const amount = decisionAmount(d);
  const creditRef = bill?.doc_number ?? null;
  const options = credit
    ? [
        { decision: "credited", label: "Credited" },
        { decision: "not_credited", label: "Not credited" },
      ]
    : [
        { decision: "is_duplicate", label: "Is a duplicate" },
        { decision: "not_duplicate", label: "Not a duplicate" },
      ];
  const chosen = options.find((o) => o.decision === choice);
  return (
    <div className="ctl-decision" role="group" aria-label={credit ? "Credit decision" : "Duplicate decision"}>
      <div className="consequence" role="note">
        <strong>{credit ? "Possibly credited in QuickBooks" : "Possible duplicate"}</strong>
        {/* B10: the facts the decision rests on, together, next to it. */}
        <dl className="decision-facts" data-testid="decision-facts">
          <div>
            <dt>Invoice</dt>
            <dd>{d.doc_number ?? "No number"}{d.line_no ? `, line ${d.line_no}` : ""}</dd>
          </div>
          {credit && (
            <div>
              <dt>Candidate credit</dt>
              <dd>
                {creditRef ?? "QuickBooks vendor credit (no number)"}
                {bill?.total ? `, ${cad(bill.total)}` : ""}
                {bill?.txn_date ? `, ${day(bill.txn_date)}` : ""}
              </dd>
            </div>
          )}
          <div>
            <dt>Supplier</dt>
            <dd>{d.vendor_name ?? "Not identified"}</dd>
          </div>
          <div>
            <dt>Amount</dt>
            <dd className="num">{amount ? cad(amount) : "Not stated"}</dd>
          </div>
          <div className="wide">
            <dt>Why only possible</dt>
            <dd>
              {credit
                ? "The credit matches this supplier and a similar amount, but it names no invoice or line, so nothing links it to this exception."
                : "Another document from this supplier has the same total within 7 days but a different number."}
            </dd>
          </div>
        </dl>
        <p className="small">Listed as undecided, not as a finding, until the controller decides.</p>
      </div>
      {may ? (
        <>
          <fieldset className="decision-choice">
            <legend>Decision</legend>
            {options.map((o) => (
              <label key={o.decision} className="choice">
                <input type="radio" name={`decision-${exc.id}`} value={o.decision} checked={choice === o.decision} onChange={() => setChoice(o.decision)} />
                <span>
                  <strong>{o.label}</strong>
                  <span className="small muted"> {decisionEffect(o.decision, d, creditRef)}</span>
                </span>
              </label>
            ))}
          </fieldset>
          <div className="field">
            <label htmlFor="decision-note">Note (optional)</label>
            <textarea id="decision-note" rows={2} value={note} maxLength={2000} onChange={(e) => setNote(e.target.value)} />
          </div>
          {chosen && (
            <p className="decision-effect" role="status" data-testid="decision-effect">
              {decisionEffect(chosen.decision, d, creditRef)}
            </p>
          )}
          <div className="decision-buttons">
            <button
              className="btn primary"
              disabled={decide.isPending || !chosen}
              onClick={() => chosen && decide.mutate({ path: credit ? "credit-decision" : "duplicate-decision", decision: chosen.decision, note })}
            >
              {chosen ? `Confirm: ${chosen.label}` : "Choose a decision"}
            </button>
          </div>
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
      toast(r.assigned_to ? `Assigned to ${r.assigned_to === members.data?.me ? "you" : r.assigned_to_name ?? "a member"}.` : "Unassigned.", "success");
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
