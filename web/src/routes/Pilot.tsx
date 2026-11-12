import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileSignature } from "lucide-react";
import { errorText, get, send } from "../api/client";
import type { PilotRead, Report } from "../api/types";
import { useSession } from "../app/session";
import { Dialog, toast } from "../components/ui";
import { cad } from "../lib/decimal";
import { day, monthName, when } from "../lib/format";

export const PAYMENT_WORDS: Record<string, string> = { unpaid: "Not paid yet", paid: "Paid", refunded: "Refunded" };
export const OUTCOME_WORDS: Record<string, string> = { converted: "Continued as a customer", refunded: "Refunded", ended: "Ended" };

export function usePilot() {
  return useQuery({ queryKey: ["pilot"], queryFn: () => get<PilotRead>("/api/v1/pilot") });
}

/** S-03: the pilot as agreed (T-5.1.3). Read only here; MatchDesk keeps the record. */
export function PilotCard() {
  const q = usePilot();
  const p = q.data?.pilot;
  if (q.isLoading) return null;
  return (
    <section className="panel pilot-card" aria-labelledby="pilot-h">
      <div className="panel-head">
        <h2 id="pilot-h">
          <FileSignature size={17} aria-hidden="true" style={{ verticalAlign: "-3px", marginRight: 8 }} />
          Pilot terms
        </h2>
        {p && <span className="muted small">Kept by MatchDesk; ask support to correct anything</span>}
      </div>
      <div className="panel-body">
        {!p ? (
          <p className="muted" style={{ margin: 0 }}>
            No pilot record yet. MatchDesk records the signed terms here before the pilot starts.
          </p>
        ) : (
          <dl className="facts">
            <dt>Pilot</dt>
            <dd>
              {cad(p.price)} for {day(p.period_start)} to {day(p.period_end)}
            </dd>
            <dt>Refund</dt>
            <dd>
              {p.refund_condition} Threshold: {cad(p.refund_threshold)}.
            </dd>
            <dt>Signed terms</dt>
            <dd>
              {p.signed_terms_ref ?? <span className="muted">Not recorded yet</span>}
              {p.signed_by_name && <div className="small muted">Signed by {p.signed_by_name}{p.signed_by_role ? `, ${p.signed_by_role}` : ""}</div>}
            </dd>
            <dt>Payment</dt>
            <dd>{PAYMENT_WORDS[p.payment_status] ?? p.payment_status}</dd>
            <dt>Governing report</dt>
            <dd>
              {q.data?.governing ? (
                <>
                  <Link to={`/reports/backtest/${q.data.governing.report_id}`}>
                    {monthName(q.data.governing.period_start.slice(0, 7))}, version {q.data.governing.version_no}
                  </Link>
                  {p.refund_due !== null && <div className="small">{p.refund_due ? "Refund applies." : "No refund."}</div>}
                </>
              ) : (
                <span className="muted">Not chosen yet. Your controller chooses one approved back-test version.</span>
              )}
            </dd>
          </dl>
        )}
      </div>
    </section>
  );
}

/** S-13 section 7: the pilot terms and, on an approved version, choosing it as the governing one. */
export function PilotSection({ r }: { r: Report }) {
  const { can } = useSession();
  const qc = useQueryClient();
  const q = usePilot();
  const [open, setOpen] = useState(false);
  const govern = useMutation({
    mutationFn: () => send("PUT", "/api/v1/pilot/governing-report", { report_id: r.id }),
    onSuccess: () => {
      setOpen(false);
      qc.invalidateQueries({ queryKey: ["pilot"] });
      qc.invalidateQueries({ queryKey: ["refund", r.id] });
      toast(`Version ${r.version_no} now governs the pilot refund.`);
    },
  });
  const p = q.data?.pilot;
  const gov = q.data?.governing;
  if (q.isLoading) return null;
  if (!p)
    return (
      <p className="muted">
        No pilot record yet, so the default threshold of {cad("500.00")} is shown. MatchDesk records the signed terms before the pilot starts.
      </p>
    );
  const isGoverning = gov?.report_id === r.id;
  return (
    <>
      <dl className="facts panel panel-body">
        <dt>Pilot</dt>
        <dd>
          {cad(p.price)}, {day(p.period_start)} to {day(p.period_end)}
        </dd>
        <dt>Refund condition</dt>
        <dd>{p.refund_condition}</dd>
        <dt>Threshold</dt>
        <dd>{cad(p.refund_threshold)}, from the signed terms ({p.signed_terms_ref ?? "reference not recorded"})</dd>
        <dt>Governing version</dt>
        <dd>
          {isGoverning ? (
            <strong>This version. Chosen {when(p.refund_determined_at)}; it cannot change.</strong>
          ) : gov ? (
            <Link to={`/reports/backtest/${gov.report_id}`}>
              {monthName(gov.period_start.slice(0, 7))}, version {gov.version_no}
            </Link>
          ) : (
            <span className="muted">Not chosen yet</span>
          )}
        </dd>
        {isGoverning && (
          <>
            <dt>Refund result</dt>
            <dd>
              Qualifying discrepancies {cad(p.refund_qualifying_amount)} against the threshold {cad(p.refund_threshold)}:{" "}
              <strong>{p.refund_due ? "refund applies" : "no refund"}</strong>.
            </dd>
          </>
        )}
      </dl>
      {r.status === "approved" && !gov && can("approve_report") && (
        <p style={{ marginTop: 12 }}>
          <button className="btn primary" onClick={() => setOpen(true)}>
            Make version {r.version_no} the governing version
          </button>
        </p>
      )}
      <Dialog
        open={open}
        title={`Make version ${r.version_no} the governing version?`}
        onClose={() => setOpen(false)}
        footer={
          <>
            <button className="btn" data-safe onClick={() => setOpen(false)}>
              Cancel
            </button>
            <button className="btn primary" disabled={govern.isPending} onClick={() => govern.mutate()}>
              Make it governing
            </button>
          </>
        }
      >
        <p>
          The pilot refund is decided on this version once, from its stored qualifying total of {cad(r.qualifying_amount)} against the threshold of{" "}
          {cad(p.refund_threshold)} in the signed terms. This choice cannot be changed later, and a newer version will not replace it.
        </p>
        {govern.error && <p className="error-text">{errorText(govern.error)}</p>}
      </Dialog>
    </>
  );
}
