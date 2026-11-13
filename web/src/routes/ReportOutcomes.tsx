// B9, S-13: what happened to each flagged discrepancy of the governing version (PRD M-3b, M-3c).
// Flagged (the report's frozen figure), confirmed by the controller and credit recovered are three
// separate counts; recording an outcome never changes the report's own figures.
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { errorText, get, send } from "../api/client";
import type { InvoiceSummary, Outcomes, Page, Report } from "../api/types";
import { useSession } from "../app/session";
import { Dialog, toast } from "../components/ui";
import { AMOUNT_INPUT, cad, compareDecimal, numberError, plainNumber } from "../lib/decimal";
import { day } from "../lib/format";
import { typeWord } from "../lib/words";

type Finding = NonNullable<Report["findings"]>[number];

export function useOutcomes(reportId: string | undefined, enabled: boolean) {
  return useQuery({
    queryKey: ["report-outcomes", reportId],
    queryFn: () => get<Outcomes>(`/api/v1/reports/backtest/${reportId}/outcomes`),
    enabled: !!reportId && enabled,
  });
}

export function OutcomesSection({ report, flagged }: { report: Report; flagged: Finding[] }) {
  const { can } = useSession();
  const q = useOutcomes(report.id, report.status === "approved" || report.status === "superseded");
  const [record, setRecord] = useState<{ finding: Finding; outcome: "controller_confirmed" | "credit_recovered" } | null>(null);
  if (report.status !== "approved" && report.status !== "superseded") return null;
  const o = q.data;
  return (
    <section aria-labelledby="outcomes-h">
      <h2 id="outcomes-h">8. What happened to the flagged discrepancies</h2>
      {!o?.is_governing ? (
        <p className="muted">
          Outcomes are recorded on the governing version only, once it is chosen in section 7. This version&apos;s figures stay as approved.
        </p>
      ) : (
        <>
          <p className="small muted" style={{ margin: "0 0 8px" }}>
            Record what the supplier agreed and what was actually credited. Each record is kept as entered, with who and when; it never changes this
            version&apos;s figures.
          </p>
          <div className="table-wrap">
            <table className="compact stack-sm outcomes-table">
              <caption className="sr-only">Outcomes of the flagged discrepancies</caption>
              <thead>
                <tr>
                  <th scope="col">Document</th>
                  <th scope="col">Type</th>
                  <th scope="col" className="num">Flagged (CAD)</th>
                  <th scope="col">Confirmed by the controller</th>
                  <th scope="col">Credit recovered</th>
                </tr>
              </thead>
              <tbody>
                {[...flagged].sort((a, b) => compareDecimal(b.amount, a.amount) || a.id.localeCompare(b.id)).map((f) => {
                  const rec = o.by_finding[f.id] ?? {};
                  const sn = f.snapshot as Record<string, string | number | null>;
                  return (
                    <tr key={f.id}>
                      <td data-label="Document">
                        {sn.doc_number ?? "No number"}
                        {sn.line_no ? <span className="muted"> line {sn.line_no}</span> : null}
                        <div className="muted small">{sn.vendor_name ?? ""}</div>
                      </td>
                      <td data-label="Type">{f.section === "not_received" ? "Not received" : typeWord(f.type)}</td>
                      <td data-label="Flagged (CAD)" className="num">{f.amount}</td>
                      <td data-label="Confirmed by the controller">
                        {rec.controller_confirmed ? (
                          <span>
                            <span className="num">{cad(rec.controller_confirmed.amount)}</span>
                            <span className="muted small"> by {rec.controller_confirmed.recorded_by_name ?? "the controller"}, {day(rec.controller_confirmed.recorded_at)}</span>
                          </span>
                        ) : can("record_finding_outcome") ? (
                          <button className="btn small" onClick={() => setRecord({ finding: f, outcome: "controller_confirmed" })}>
                            Record confirmation
                          </button>
                        ) : (
                          <span className="muted">Not confirmed yet</span>
                        )}
                      </td>
                      <td data-label="Credit recovered">
                        {rec.credit_recovered ? (
                          <span>
                            <span className="num">{cad(rec.credit_recovered.amount)}</span>
                            <span className="muted small"> {rec.credit_recovered.credit_reference ?? "credit note"}, {day(rec.credit_recovered.recorded_at)}</span>
                          </span>
                        ) : rec.controller_confirmed && can("record_finding_outcome") ? (
                          <button className="btn small" onClick={() => setRecord({ finding: f, outcome: "credit_recovered" })}>
                            Record credit recovered
                          </button>
                        ) : (
                          <span className="muted">{rec.controller_confirmed ? "Not recovered yet" : "Needs a confirmation first"}</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
      {record && <RecordDialog report={report} {...record} onClose={() => setRecord(null)} confirmedAmount={o?.by_finding[record.finding.id]?.controller_confirmed?.amount} />}
    </section>
  );
}

function RecordDialog({
  report,
  finding,
  outcome,
  confirmedAmount,
  onClose,
}: {
  report: Report;
  finding: Finding;
  outcome: "controller_confirmed" | "credit_recovered";
  confirmedAmount?: string;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const cap = outcome === "credit_recovered" ? confirmedAmount ?? finding.amount : finding.amount;
  const [amount, setAmount] = useState(cap);
  const [ref, setRef] = useState("");
  const [creditId, setCreditId] = useState("");
  const [note, setNote] = useState("");
  const credits = useQuery({
    queryKey: ["invoices", "credit-notes"],
    queryFn: () => get<Page<InvoiceSummary>>("/api/v1/invoices?limit=200&doc_type=credit_note"),
    enabled: outcome === "credit_recovered",
  });
  const save = useMutation({
    mutationFn: () =>
      send("POST", `/api/v1/reports/findings/${finding.id}/outcomes`, {
        outcome,
        amount: plainNumber(amount, AMOUNT_INPUT),
        credit_invoice_id: creditId || null,
        credit_reference: ref.trim() || null,
        note: note.trim() || null,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["report-outcomes", report.id] });
      toast(outcome === "credit_recovered" ? "Credit recovered recorded." : "Confirmation recorded.");
      onClose();
    },
  });
  const sn = finding.snapshot as Record<string, string | number | null>;
  const creditNotes = (credits.data?.items ?? []).filter((i) => i.doc_type === "credit_note");
  return (
    <Dialog
      open
      title={outcome === "credit_recovered" ? "Record the credit recovered" : "Record the controller's confirmation"}
      description={`${sn.doc_number ?? "Document"}${sn.line_no ? ` line ${sn.line_no}` : ""}: flagged ${cad(finding.amount)}. Recorded once; it cannot be edited afterwards.`}
      onClose={onClose}
      footer={
        <>
          <button className="btn" data-safe onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn primary"
            disabled={save.isPending || !plainNumber(amount, AMOUNT_INPUT) || (outcome === "credit_recovered" && !ref.trim() && !creditId)}
            onClick={() => save.mutate()}
          >
            Record
          </button>
        </>
      }
    >
      <div className="field">
        <label htmlFor="oc-amount">{outcome === "credit_recovered" ? "Amount credited (CAD)" : "Overcharge confirmed (CAD)"}</label>
        <input
          id="oc-amount"
          className="num"
          inputMode="decimal"
          value={amount}
          aria-invalid={numberError(amount, AMOUNT_INPUT) ? true : undefined}
          aria-describedby={numberError(amount, AMOUNT_INPUT) ? "oc-amount-err" : undefined}
          onChange={(e) => setAmount(e.target.value)}
        />
        {numberError(amount, AMOUNT_INPUT) && (
          <span className="error-text small" id="oc-amount-err">
            {numberError(amount, AMOUNT_INPUT)}
          </span>
        )}
        <span className="hint">At most {cad(cap)}{outcome === "credit_recovered" ? ", the confirmed amount" : ", the flagged amount"}.</span>
      </div>
      {outcome === "credit_recovered" && (
        <>
          {creditNotes.length > 0 && (
            <div className="field">
              <label htmlFor="oc-credit">Credit note uploaded to MatchDesk</label>
              <select id="oc-credit" value={creditId} onChange={(e) => setCreditId(e.target.value)}>
                <option value="">None</option>
                {creditNotes.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.doc_number ?? "No number"} {c.vendor_name ? `(${c.vendor_name})` : ""}
                  </option>
                ))}
              </select>
            </div>
          )}
          <div className="field">
            <label htmlFor="oc-ref">Or the QuickBooks credit or refund reference</label>
            <input id="oc-ref" value={ref} maxLength={200} onChange={(e) => setRef(e.target.value)} placeholder="For example: vendor credit VC-77" />
          </div>
        </>
      )}
      <div className="field">
        <label htmlFor="oc-note">Note (optional)</label>
        <textarea id="oc-note" rows={2} value={note} maxLength={2000} onChange={(e) => setNote(e.target.value)} />
      </div>
      {save.error && <p className="error-text">{errorText(save.error)}</p>}
    </Dialog>
  );
}
