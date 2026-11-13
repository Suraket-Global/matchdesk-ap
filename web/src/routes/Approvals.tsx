import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, errorText, get, send } from "../api/client";
import type { Alias, Approval, ExceptionPage, Page, ReceivingImport } from "../api/types";
import { Dialog, Empty, ErrorState, Field, Loading, PageHead, toast, usePageTitle } from "../components/ui";
import { cad } from "../lib/decimal";
import { qty } from "../lib/decimal";
import { plural, when } from "../lib/format";
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

/** One request in four parts, in the order a controller reads it (B8): the proposed change, the
 * records it touches, what approving does, and the decision. */
function DecisionCard({ a, importName, onDecide }: { a: Approval; importName?: ReceivingImport; onDecide: (d: "approve" | "return") => void }) {
  const al = a.alias;
  const e = a.exception;
  const affected = a.affected ?? [];
  const invoices = new Set(affected.map((x) => x.invoice_id)).size;
  return (
    <article className="decision" aria-labelledby={`d-${a.id}`}>
      <div className="d-change">
        <h3 id={`d-${a.id}`} className="d-label">
          Proposed change
        </h3>
        {al ? (
          <>
            <p className="d-big">
              1 {al.supplier_uom ?? "supplier unit"} = {qty(al.conversion_factor)} {al.item_uom ?? "units"}
            </p>
            <p>
              {al.vendor_name ?? "Supplier"} code <strong>{al.supplier_item_code}</strong> becomes our item <strong>{al.item_sku ?? "item"}</strong>.
            </p>
          </>
        ) : e ? (
          <>
            <p className="d-big">Waive {cad(a.amount ?? e.reported_amount ?? e.variance_amount)}</p>
            <p>
              {typeWord(e.type)} on {e.vendor_name ?? "the supplier"} {e.doc_number}
              {e.line_no ? `, line ${e.line_no}` : ""}.
            </p>
          </>
        ) : (
          <p className="d-big">Count late receiving evidence</p>
        )}
        <p className="muted small">
          Asked by {a.requested_by_name ?? "a clerk"} {when(a.requested_at)}. {a.reason ? `Reason: "${a.reason}"` : "No reason given."}
        </p>
      </div>
      <div className="d-records">
        <h3 className="d-label">Affected records</h3>
        {al && affected.length > 0 && (
          <div className="table-wrap">
            <table className="compact stack-sm">
              <caption className="sr-only">Invoice lines re-matched by this conversion</caption>
              <thead>
                <tr>
                  <th scope="col">Invoice line</th>
                  <th scope="col" className="num">
                    Billed
                  </th>
                  <th scope="col" className="num">
                    After conversion
                  </th>
                  <th scope="col">Open now</th>
                </tr>
              </thead>
              <tbody>
                {affected.map((x) => (
                  <tr key={x.invoice_line_id}>
                    <td className="nowrap" data-label="Invoice line">
                      <Link to={`/invoices/${x.invoice_id}?line=${x.invoice_line_id}&from=${encodeURIComponent("/approvals")}`}>
                        {x.doc_number} line {x.line_no}
                      </Link>
                    </td>
                    <td className="num" data-label="Billed">
                      {qty(x.qty)} {x.uom ?? ""}
                    </td>
                    <td className="num" data-label="After conversion">
                      {qty(x.converted_qty)} {al.item_uom ?? ""}
                    </td>
                    <td className="small" data-label="Open now">{x.open_exceptions.length ? x.open_exceptions.map(typeWord).join(", ") : <span className="muted">None</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {al && affected.length === 0 && <p className="muted">No invoice uses this code yet; future invoices will.</p>}
        {e && (
          <p>
            <Link to={`/invoices/${e.invoice_id}?line=${e.invoice_line_id ?? ""}&exc=${e.id}&from=${encodeURIComponent("/approvals")}`}>
              {e.doc_number}
              {e.line_no ? ` line ${e.line_no}` : ""}: open the evidence
            </Link>
          </p>
        )}
        {a.receiving_import_id && (
          <p>
            <Link to={`/receiving/imports/${a.receiving_import_id}`}>{importName?.file_name ?? "Open the import"}</Link>{" "}
            <span className="muted small">{EVIDENCE_CLASSES[importName?.evidence_class ?? ""]?.name}</span>
          </p>
        )}
        {a.subject_type === "late_receipt" && (
          <div className="would-clear">
            <h3 className="d-label">Exceptions open on those lines now</h3>
            {(a.would_clear ?? []).length === 0 ? (
              <p className="muted small">None is open now.</p>
            ) : (
              <ul className="plain-list small">
                {(a.would_clear ?? []).map((x) => (
                  <li key={x.id}>
                    <Link to={`/invoices/${x.invoice_id}?line=${x.invoice_line_id ?? ""}&exc=${x.id}`}>
                      {x.doc_number ?? "Document"}
                      {x.line_no ? ` line ${x.line_no}` : ""}
                    </Link>
                    : {typeWord(x.type)}, {cad(x.value)}
                  </li>
                ))}
              </ul>
            )}
            <p className="muted small">The re-match after approval decides which of them clear; nothing clears by approval alone.</p>
          </div>
        )}
      </div>
      <div className="d-consequence">
        <h3 className="d-label">If you approve</h3>
        <p>
          {al
            ? `${plural(affected.length, "line")} on ${plural(invoices, "invoice")} ${affected.length === 1 ? "is" : "are"} matched again in ${al.item_uom ?? "our units"}: quantities are multiplied by ${qty(al.conversion_factor)} before they are compared with the purchase order and the receipts. Their exceptions are raised again or cleared by the new result.`
            : e
              ? "It is listed in the report as waived, with your name. A waiver never lowers the refund calculation."
              : "Rows loaded after an exception was already open on their purchase-order lines start to count, and those lines are matched again."}
        </p>
        <p className="muted small">If you return it, nothing changes: {al ? "the alias stays pending and its lines stay in the queue" : "the request goes back to the clerk with your note"}.</p>
      </div>
      <div className="d-decide">
        <button className="btn primary" onClick={() => onDecide("approve")}>
          {e ? "Approve waiver" : "Approve"}
        </button>
        <button className="btn" onClick={() => onDecide("return")}>
          Return with note
        </button>
      </div>
    </article>
  );
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
        "success",
      );
    },
  });
  const ack = useMutation({
    mutationFn: () => send<{ acknowledged: number }>("POST", "/api/v1/aliases/review-acknowledgement"),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["aliases"] }); // the list empties (review W5)
      toast(`${plural(r.acknowledged, "new alias", "new aliases")} marked reviewed.`, "success");
    },
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
  const newAliases = (aliases.data?.items ?? []).filter((a) => !a.approved_by && !a.reviewed_at && /^1(\.0+)?$/.test(a.conversion_factor));
  return (
    <>
      <PageHead title="Approvals" lede="Approve or return what your clerk cannot decide alone." />
      {items.length === 0 && (
        <div className="panel" style={{ marginBottom: 16 }}>
          <Empty title={newAliases.length ? "No approvals are waiting. New aliases are waiting for your review below." : "Nothing is waiting for you."} />
        </div>
      )}
      <div className="stack">
        {groups
          .filter(([, , list]) => list.length)
          .map(([key, title, list]) => (
            <section key={key} aria-labelledby={`g-${key}`}>
              <h2 id={`g-${key}`} style={{ marginBottom: 8 }}>
                {title} <span className="muted">({list.length})</span>
              </h2>
              <div className="stack">
                {list.map((a) => (
                  <DecisionCard key={a.id} a={a} importName={imports.data?.items.find((i) => i.id === a.receiving_import_id)} onDecide={(decision) => setOpen({ a, decision })} />
                ))}
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
              Approved earlier (the last 10)
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
