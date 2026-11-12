import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Mail } from "lucide-react";
import { errorText, get, send } from "../api/client";
import type { Weekly } from "../api/types";
import { useSession } from "../app/session";
import { Dialog, Empty, ErrorState, Loading, PageHead, toast, usePageTitle } from "../components/ui";
import { cad, money } from "../lib/decimal";
import { day, plural, when } from "../lib/format";
import { queueLink } from "../lib/queue";

function iso(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function monday(isoDay: string): string {
  const [y, m, d] = isoDay.split("-").map(Number);
  const dt = new Date(y, m - 1, d);
  dt.setDate(dt.getDate() - ((dt.getDay() + 6) % 7));
  return iso(dt);
}

function shift(isoDay: string, days: number): string {
  const [y, m, d] = isoDay.split("-").map(Number);
  return iso(new Date(y, m - 1, d + days));
}

/** S-14: one week per supplier, the same figures as the exception queue with the same filters (IT-25). */
export function WeeklyPage() {
  usePageTitle("Weekly summary");
  const [params, setParams] = useSearchParams();
  const { can } = useSession();
  const qc = useQueryClient();
  const lastWeek = monday(shift(iso(new Date()), -7));
  const week = monday(params.get("week") ?? lastWeek);
  const q = useQuery({ queryKey: ["weekly", week], queryFn: () => get<Weekly>(`/api/v1/weekly-summary?week_start=${week}`) });
  const [confirm, setConfirm] = useState(false);
  const sendNow = useMutation({
    mutationFn: () => send<{ recipients: number }>("POST", "/api/v1/weekly-summary/send", { week_start: week }),
    onSuccess: (r) => {
      setConfirm(false);
      qc.invalidateQueries({ queryKey: ["weekly", week] });
      toast(`Weekly summary emailed to ${plural(r.recipients, "controller")}.`);
    },
  });
  useEffect(() => sendNow.reset(), [week]); // eslint-disable-line react-hooks/exhaustive-deps
  const go = (w: string) => setParams({ week: w });
  const w = q.data;
  return (
    <>
      <PageHead
        title="Weekly summary"
        crumbs={<Link to="/reports">Back-test reports</Link>}
        lede="Documents dated in one week, by supplier. Open exceptions and their value are the exception queue's, with the same filters."
        actions={
          can("send_weekly_summary") && (
            <button className="btn" onClick={() => setConfirm(true)} disabled={!w}>
              <Mail size={16} aria-hidden="true" />
              Email this week now
            </button>
          )
        }
      />
      <div className="week-nav panel panel-body">
        <button className="btn icon-btn" aria-label="Previous week" onClick={() => go(shift(week, -7))}>
          <ChevronLeft size={16} aria-hidden="true" />
        </button>
        <div className="week-label">
          <strong>
            {day(week)} to {day(shift(week, 6))}
          </strong>
          <label className="small muted">
            Week of{" "}
            <input type="date" aria-label="Week of" value={week} onChange={(e) => e.target.value && go(monday(e.target.value))} />
          </label>
        </div>
        <button className="btn icon-btn" aria-label="Next week" onClick={() => go(shift(week, 7))}>
          <ChevronRight size={16} aria-hidden="true" />
        </button>
      </div>
      {q.isLoading && <Loading />}
      {q.error && <ErrorState error={q.error} retry={() => q.refetch()} />}
      {w && w.state && w.state !== "measured" && w.state !== "unavailable" && (
        <div className="panel">
          <Empty title={w.state === "awaiting_invoices" ? "Nothing checked for this week" : w.state === "processing" ? "This week is still being read and matched" : "Waiting for receiving evidence"}>
            <p>
              {w.state === "awaiting_invoices"
                ? "No invoice is dated in this week, so there are no figures to read: this is not a clean week. Choose another week, or upload its invoices on Intake."
                : w.state === "processing"
                  ? "Figures appear when every document dated in this week is read and matched."
                  : "Invoices dated in this week are matched, but no receiving file has been imported, so no line can pass. Import the warehouse receiving file on Receiving."}
            </p>
          </Empty>
        </div>
      )}
      {w && (!w.state || w.state === "measured" || w.state === "unavailable") && (
        <>
          <div className="cards">
            <div>
              <span className="muted small">Flagged discrepancies</span>
              <span className="big">{cad(w.total.flagged_amount)}</span>
              <span className="small">findings and not received</span>
            </div>
            <div>
              <span className="muted small">Open exceptions</span>
              <span className="big">{cad(w.total.open_value)}</span>
              <span className="small">{plural(w.total.open_count, "exception")} waiting for a person</span>
            </div>
            <div>
              <span className="muted small">Documents</span>
              <span className="big">{w.total.documents}</span>
              <span className="small">{plural(w.total.lines, "line")} checked</span>
            </div>
            <div>
              <span className="muted small">Passed every check</span>
              <span className="big">{w.total.pass_rate_pct ? `${w.total.pass_rate_pct.replace(/\.0$/, "")}%` : "–"}</span>
              <span className="small">{plural(w.total.lines_matched, "line")} matched</span>
            </div>
          </div>
          {w.suppliers.length === 0 ? (
            <div className="panel">
              <Empty title="No documents dated in this week">
                <p>Choose another week, or upload the invoices for it on Intake.</p>
              </Empty>
            </div>
          ) : (
            <div className="table-wrap">
              <table className="stack-sm">
                <caption className="sr-only">Weekly summary by supplier</caption>
                <thead>
                  <tr>
                    <th scope="col">Supplier</th>
                    <th scope="col" className="num">Documents</th>
                    <th scope="col" className="num">Lines</th>
                    <th scope="col" className="num">Passed</th>
                    <th scope="col" className="num">Flagged (CAD)</th>
                    <th scope="col" className="num">Open exceptions</th>
                    <th scope="col" className="num">Open value (CAD)</th>
                  </tr>
                </thead>
                <tbody>
                  {w.suppliers.map((s) => (
                    <tr key={s.vendor_id ?? "none"}>
                      <td data-label="Supplier">{s.vendor_name ?? <span className="muted">Not identified</span>}</td>
                      <td className="num" data-label="Documents">{s.documents}</td>
                      <td className="num" data-label="Lines">{s.lines}</td>
                      <td className="num" data-label="Passed">{s.pass_rate_pct ? `${s.pass_rate_pct.replace(/\.0$/, "")}%` : "–"}</td>
                      <td className="num" data-label="Flagged (CAD)">{money(s.flagged_amount)}</td>
                      <td className="num" data-label="Open exceptions">
                        {s.open_count > 0 ? (
                          <Link to={queueLink({ vendor: s.vendor_id ?? "none", from: w.week_start, to: w.week_end, src: "weekly" })} aria-label={`${s.open_count} open exceptions for ${s.vendor_name ?? "supplier not identified"}, ${day(w.week_start)} to ${day(w.week_end)}`}>
                            {s.open_count}
                          </Link>
                        ) : (
                          s.open_count
                        )}
                      </td>
                      <td className="num" data-label="Open value (CAD)">{money(s.open_value)}</td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr>
                    <td>Total</td>
                    <td className="num">{w.total.documents}</td>
                    <td className="num">{w.total.lines}</td>
                    <td className="num">{w.total.pass_rate_pct ? `${w.total.pass_rate_pct.replace(/\.0$/, "")}%` : "–"}</td>
                    <td className="num">{money(w.total.flagged_amount)}</td>
                    <td className="num">
                      {w.total.open_count > 0 ? <Link to={queueLink({ from: w.week_start, to: w.week_end, src: "weekly" })}>{w.total.open_count}</Link> : w.total.open_count}
                    </td>
                    <td className="num">{money(w.total.open_value)}</td>
                  </tr>
                </tfoot>
              </table>
            </div>
          )}
          <section className="panel" aria-labelledby="sent-h" style={{ marginTop: 16 }}>
            <div className="panel-head">
              <h2 id="sent-h">Weekly email</h2>
            </div>
            <div className="panel-body">
              <p style={{ marginTop: 0 }}>
                Every Monday morning MatchDesk emails your controllers last week&apos;s totals and a link to this page. The email carries no supplier,
                price, document or line.
              </p>
              {w.sent.length ? (
                <ul className="plain-list">
                  {w.sent.map((x) => (
                    <li key={`${x.week_start}-${x.trigger}`}>
                      Week of {day(x.week_start)}: {x.trigger === "manual" ? "sent by hand" : "sent on schedule"} {when(x.sent_at)} to {plural(x.recipients, "controller")}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="muted">Not sent yet.</p>
              )}
            </div>
          </section>
        </>
      )}
      <Dialog
        open={confirm}
        title="Email this week's summary now?"
        onClose={() => setConfirm(false)}
        footer={
          <>
            <button className="btn" data-safe onClick={() => setConfirm(false)}>
              Cancel
            </button>
            <button className="btn primary" disabled={sendNow.isPending} onClick={() => sendNow.mutate()}>
              Email now
            </button>
          </>
        }
      >
        <p>
          Your controllers receive the totals for {day(week)} to {day(shift(week, 6))} and a link to this page. It can be sent by hand once per week; the Monday
          email is separate.
        </p>
        {sendNow.error && <p className="error-text">{errorText(sendNow.error)}</p>}
      </Dialog>
    </>
  );
}
