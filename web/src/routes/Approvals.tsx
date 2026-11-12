import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, errorText, get, send } from "../api/client";
import type { Alias, Approval, ExceptionPage, Page, ReceivingImport } from "../api/types";
import { Dialog, Empty, ErrorState, Field, Loading, PageHead, toast, usePageTitle } from "../components/ui";
import { cad } from "../lib/decimal";
import { multiply, qty } from "../lib/decimal";
import { when } from "../lib/format";
import { typeWord, EVIDENCE_CLASSES } from "../lib/words";

function sentence(a: Approval): string {
  if (a.subject_type === "waiver" && a.exception) {
    const e = a.exception;
    return `Waive ${cad(a.amount ?? e.reported_amount ?? e.variance_amount)} on ${e.vendor_name ?? "the supplier"} ${e.doc_type === "credit_note" ? "credit note" : "invoice"} ${e.doc_number}${e.line_no ? `, line ${e.line_no}` : ""} (${typeWord(e.type).toLowerCase()}). It will be listed in the report as waived, with your name.`;
  }
  if (a.subject_type === "alias_conversion" && a.alias) {
    const al = a.alias;
    return `Approve conversion: 1 ${al.supplier_uom ?? "supplier unit"} of ${al.vendor_name ?? "the supplier"} code ${al.supplier_item_code} = ${qty(al.conversion_factor)} ${al.item_uom ?? "units"} of ${al.item_sku ?? "our item"}. Every line using this alias is re-matched.`;
  }
  if (a.subject_type === "late_receipt") return "Approve late receiving evidence: rows loaded after an exception was already open on their purchase-order lines start to count, and those lines are re-matched.";
  return "Approve this request.";
}

/** S-12: what the clerk cannot decide alone. Each decision restates itself before it is made (DD-09). */
export function ApprovalsPage() {
  usePageTitle("Approvals");
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["approvals", "pending"], queryFn: () => get<Page<Approval>>("/api/v1/approvals?status=pending") });
  const recent = useQuery({ queryKey: ["approvals", "approved"], queryFn: () => get<Page<Approval>>("/api/v1/approvals?status=approved") });
  const aliases = useQuery({ queryKey: ["aliases"], queryFn: () => get<Page<Alias>>("/api/v1/aliases?status=active") });
  const imports = useQuery({ queryKey: ["receiving", "imports"], queryFn: () => get<Page<ReceivingImport>>("/api/v1/receiving/imports?limit=200") });
  const weekAgo = new Date(Date.now() - 7 * 86_400_000).toISOString();
  const waived = useQuery({
    queryKey: ["exceptions", "waived-week"],
    queryFn: () => get<ExceptionPage>(`/api/v1/exceptions?limit=200&status=waived&resolved_since=${encodeURIComponent(weekAgo)}`),
  });
  const [open, setOpen] = useState<{ a: Approval; decision: "approve" | "return" } | null>(null);
  const [note, setNote] = useState("");
  const decide = useMutation({
    mutationFn: ({ a, decision }: { a: Approval; decision: "approve" | "return" }) =>
      send<Approval & { effect: string | null; match_run_id: string | null }>("POST", `/api/v1/approvals/${a.id}/decision`, { decision, note: note || null }, { ifMatch: a.version }),
    onSuccess: (r, v) => {
      setOpen(null);
      setNote("");
      qc.invalidateQueries({ queryKey: ["approvals"] });
      qc.invalidateQueries({ queryKey: ["aliases"] });
      qc.invalidateQueries({ queryKey: ["exceptions"] });
      qc.invalidateQueries({ queryKey: ["invoice"] });
      toast(
        v.decision === "return"
          ? "Returned with your note."
          : r.self_approved
            ? "Approved. You are the only controller, so this is recorded as self-approved and flagged in the report."
            : r.match_run_id
              ? "Approved. The affected lines are being re-matched."
              : "Approved.",
      );
    },
  });
  const ack = useMutation({
    mutationFn: () => send<{ acknowledged: number }>("POST", "/api/v1/aliases/review-acknowledgement"),
    onSuccess: (r) => toast(`${r.acknowledged} new aliases marked reviewed.`),
  });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorState error={q.error} retry={() => q.refetch()} />;
  const items = q.data!.items;
  const groups: [string, string, Approval[]][] = [
    ["waiver", "Waivers above the limit or the 30-day cap", items.filter((a) => a.subject_type === "waiver")],
    ["alias_conversion", "Unit conversions", items.filter((a) => a.subject_type === "alias_conversion")],
    ["late_receipt", "Late receiving evidence", items.filter((a) => a.subject_type === "late_receipt")],
  ];
  const conflict = decide.error instanceof ApiError && decide.error.status === 409;
  const newAliases = (aliases.data?.items ?? []).filter((a) => !a.approved_by && /^1(\.0+)?$/.test(a.conversion_factor));
  return (
    <>
      <PageHead title="Approvals" lede="Approve or return what your clerk cannot decide alone." />
      {items.length === 0 && (
        <div className="panel" style={{ marginBottom: 16 }}>
          <Empty title="Nothing is waiting for you." />
        </div>
      )}
      <div className="stack">
        {groups
          .filter(([, , list]) => list.length)
          .map(([key, title, list]) => (
            <section key={key} aria-labelledby={`g-${key}`}>
              <h2 id={`g-${key}`} style={{ marginBottom: 8 }}>
                {title}
              </h2>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th scope="col">Request</th>
                      <th scope="col">Asked by</th>
                      <th scope="col">Reason</th>
                      <th scope="col">
                        <span className="sr-only">Decision</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {list.map((a) => (
                      <tr key={a.id}>
                        <td style={{ maxWidth: 520 }}>
                          {sentence(a)}
                          {a.exception && (
                            <div>
                              <Link to={`/invoices/${a.exception.invoice_id}?line=${a.exception.invoice_line_id ?? ""}&exc=${a.exception.id}&from=${encodeURIComponent("/approvals")}`}>
                                Open the evidence
                              </Link>
                            </div>
                          )}
                          {a.alias && (
                            <div className="muted small">
                              Example: 2 {a.alias.supplier_uom ?? "supplier units"} become {qty(multiply("2", a.alias.conversion_factor, 4))} {a.alias.item_uom ?? "our units"}.{" "}
                              <Link to={`/invoices?vendor=${a.alias.vendor_id}`}>Invoices from this supplier</Link>
                            </div>
                          )}
                          {a.receiving_import_id && (
                            <div>
                              <Link to={`/receiving/imports/${a.receiving_import_id}`}>
                                {imports.data?.items.find((i) => i.id === a.receiving_import_id)?.file_name ?? "Open the import"}
                              </Link>{" "}
                              <span className="muted small">
                                {EVIDENCE_CLASSES[imports.data?.items.find((i) => i.id === a.receiving_import_id)?.evidence_class ?? ""]?.name}
                              </span>
                            </div>
                          )}
                        </td>
                        <td>
                          {a.requested_by_name}
                          <div className="muted small">{when(a.requested_at)}</div>
                        </td>
                        <td>{a.reason ?? <span className="muted">None given</span>}</td>
                        <td>
                          <div className="actions">
                            <button className="btn" onClick={() => setOpen({ a, decision: "return" })}>
                              Return with note
                            </button>
                            <button className="btn primary" onClick={() => setOpen({ a, decision: "approve" })}>
                              Approve
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          ))}
        <section aria-labelledby="new-aliases-h" className="panel">
          <div className="panel-head">
            <h2 id="new-aliases-h">New 1-to-1 aliases for review</h2>
            <button className="btn" disabled={!newAliases.length || ack.isPending} onClick={() => ack.mutate()}>
              Mark reviewed
            </button>
          </div>
          <div className="panel-body">
            {newAliases.length ? (
              <ul style={{ margin: 0, paddingLeft: 18 }}>
                {newAliases.map((a) => (
                  <li key={a.id}>
                    {a.vendor_name}: {a.supplier_item_code} → {a.item_sku} ({a.created_by_name})
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted">None.</p>
            )}
          </div>
        </section>
        <section aria-labelledby="week-h" className="panel">
          <div className="panel-head">
            <h2 id="week-h">This week's waivers made without approval</h2>
          </div>
          <div className="panel-body">
            {(waived.data?.items ?? []).length ? (
              <ul style={{ margin: 0, paddingLeft: 18 }}>
                {waived.data!.items.map((e) => (
                  <li key={e.id}>
                    {e.vendor_name} {e.doc_number}: {typeWord(e.type)} {cad(e.reported_amount ?? e.variance_amount)} {e.resolution_note ? `"${e.resolution_note}"` : ""}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted">None.</p>
            )}
          </div>
        </section>
        {(recent.data?.items ?? []).length > 0 && (
          <section aria-labelledby="done-h">
            <h2 id="done-h" style={{ marginBottom: 8 }}>
              Recently approved
            </h2>
            <ul className="panel panel-body" style={{ margin: 0, paddingLeft: 32 }}>
              {recent.data!.items.slice(-10).map((a) => (
                <li key={a.id}>
                  {sentence(a).split(".")[0]}. Approved by {a.decided_by_name}
                  {a.self_approved ? " (self-approved)" : ""}.
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
      <Dialog
        open={!!open}
        title={open?.decision === "return" ? "Return to the clerk" : open?.a.subject_type === "waiver" ? "Approve waiver" : open?.a.subject_type === "alias_conversion" ? "Approve conversion" : "Approve late evidence"}
        onClose={() => setOpen(null)}
        footer={
          <>
            <button className="btn" data-safe onClick={() => setOpen(null)}>
              Cancel
            </button>
            <button
              className={`btn ${open?.decision === "approve" ? "primary" : ""}`}
              disabled={decide.isPending || (open?.decision === "return" && !note.trim())}
              onClick={() => open && decide.mutate(open)}
            >
              {open?.decision === "return" ? `Return to ${open.a.requested_by_name ?? "the clerk"}` : open?.a.subject_type === "waiver" ? "Approve waiver" : "Approve"}
            </button>
          </>
        }
      >
        {open && <p>{sentence(open.a)}</p>}
        {open?.a.reason && <p>Reason given: "{open.a.reason}"</p>}
        <Field label={open?.decision === "return" ? "Note (required)" : "Note (optional)"}>{(f) => <textarea id={f.id} value={note} onChange={(e) => setNote(e.target.value)} />}</Field>
        {decide.error && <p className="error-text">{conflict ? "Another controller decided this a moment ago. The list now shows the outcome." : errorText(decide.error)}</p>}
      </Dialog>
    </>
  );
}
