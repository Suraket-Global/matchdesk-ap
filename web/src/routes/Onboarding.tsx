import { PilotCard } from "./Pilot";
import { Link, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { errorText, get, send } from "../api/client";
import type { Batch, InvoiceSummary, NoReceivingDeclaration, Page, PurchaseOrder, QboConnection, ReceivingImport, SyncRun } from "../api/types";
import { useSession } from "../app/session";
import { usePeriod } from "../app/period";
import { Banner, Dialog, ErrorState, Loading, PageHead, StatusChip, toast, usePageTitle } from "../components/ui";
import { Stepper } from "../components/Page";
import { monthName, monthRange, plural, when } from "../lib/format";
import { useState } from "react";

export function useOnboarding() {
  const qbo = useQuery({ queryKey: ["qbo", "connection"], queryFn: () => get<QboConnection>("/api/v1/qbo/connection") });
  const imports = useQuery({
    queryKey: ["receiving", "imports"],
    queryFn: () => get<Page<ReceivingImport>>("/api/v1/receiving/imports?limit=200"),
  });
  const batches = useQuery({ queryKey: ["batches"], queryFn: () => get<Page<Batch>>("/api/v1/intake/batches?limit=200") });
  const declaration = useQuery({
    queryKey: ["no-receiving"],
    queryFn: () => get<{ declaration: NoReceivingDeclaration | null; statement: string }>("/api/v1/onboarding/no-receiving-declaration"),
  });
  const committed = (imports.data?.items ?? []).filter((i) => i.state === "succeeded");
  const processed = (batches.data?.items ?? []).reduce((n, b) => n + b.totals.ready + b.totals["needs review"], 0);
  const files = (batches.data?.items ?? []).reduce((n, b) => n + b.totals.file_count, 0);
  const connected = qbo.data?.status === "connected";
  return {
    loading: qbo.isLoading || imports.isLoading || batches.isLoading,
    error: qbo.error ?? imports.error ?? batches.error,
    qbo: qbo.data,
    connected,
    committed,
    processed,
    files,
    declaration: declaration.data?.declaration ?? null,
    statement: declaration.data?.statement ?? "",
    complete: connected && (committed.length > 0 || !!declaration.data?.declaration) && processed > 0,
  };
}

/** S-03: the four things MatchDesk needs, which are done, and where to do the rest. */
export function OnboardingPage() {
  usePageTitle("Onboarding checklist");
  const [params, setParams] = useSearchParams();
  const period = usePeriod();
  const month = params.get("month") ?? period.month;
  const { can, role } = useSession();
  const qc = useQueryClient();
  const ob = useOnboarding();
  const approvals = useQuery({ queryKey: ["approvals", "pending"], queryFn: () => get<Page<{ id: string }>>("/api/v1/approvals?status=pending"), enabled: can("approve") });
  const pos = useQuery({
    queryKey: ["purchase-orders"],
    queryFn: () => get<Page<PurchaseOrder>>("/api/v1/purchase-orders?limit=200"),
  });
  const invoices = useQuery({
    queryKey: ["invoices", "all"],
    queryFn: () => get<Page<InvoiceSummary>>("/api/v1/invoices?limit=200"),
  });
  const status = useQuery({
    queryKey: ["onboarding-status"],
    queryFn: () =>
      get<{
        attestation: { evidence_class: string; source_description: string; attested_by_name: string | null; attested_at: string } | null;
        earlier_invoices_needed: { po_number: string | null; purchase_order_id: string; po_line_no: number | null; billed_without_document_qty: string | null; uom: string | null; bills_to_upload: string[] }[];
      }>("/api/v1/onboarding/status"),
  });
  const att = status.data?.attestation;
  const earlier = status.data?.earlier_invoices_needed ?? [];
  const [run, setRun] = useState<SyncRun | null>(null);
  const sync = useMutation({
    mutationFn: () => {
      const { start, end } = monthRange(month);
      const refs = [
        ...new Set(
          (invoices.data?.items ?? [])
            .filter((i) => i.doc_date && i.doc_date >= start && i.doc_date <= end && i.po_number)
            .map((i) => i.po_number as string),
        ),
      ];
      const body = refs.length
        ? { mode: "po_references", po_references: refs }
        : { mode: "date_range", range_start: start, range_end: end };
      return send<SyncRun>("POST", "/api/v1/qbo/sync-runs", body);
    },
    onSuccess: (r) => {
      setRun(r);
      toast("Reading from QuickBooks started.");
      qc.invalidateQueries({ queryKey: ["purchase-orders"] });
    },
  });
  const syncStatus = useQuery({
    queryKey: ["sync-run", run?.id],
    queryFn: () => get<SyncRun>(`/api/v1/qbo/sync-runs/${run?.id}`),
    enabled: !!run,
    // Stops on a finished run, and on an error so a failing request is not repeated forever (review, minor).
    refetchInterval: (q) => (q.state.error || (q.state.data && ["succeeded", "failed"].includes(q.state.data.state)) ? false : 2000),
    retry: 2,
  });
  if (ob.loading) return <Loading />;
  if (ob.error) return <ErrorState error={ob.error} />;
  const lines = ob.committed.reduce((n, i) => n + (i.rows_valid ?? 0), 0);
  const poCount = pos.data?.items.length ?? 0;
  const done = [ob.connected, ob.connected && poCount > 0, ob.committed.length > 0 || !!ob.declaration, ob.processed > 0];
  const current = done.findIndex((d) => !d);
  const cls = (i: number) => (done[i] ? "done" : i === current ? "current" : "");
  // B8: the one next task this role can do, first on the page.
  const waiting = approvals.data?.items.length ?? 0;
  const next: { title: string; body: string; to: string; action: string } | null =
    role === "controller" && waiting > 0
      ? { title: `${plural(waiting, "approval")} waiting for you`, body: "Your clerk cannot decide these alone.", to: "/approvals", action: "Open approvals" }
      : !ob.connected && can("connect_qbo")
        ? { title: "Connect QuickBooks", body: "MatchDesk only reads purchase orders, bills and credits.", to: "/settings/quickbooks", action: "Connect QuickBooks" }
        : ob.committed.length === 0 && !ob.declaration && can("upload")
          ? {
              title: "Load the warehouse receiving file",
              body: "Required before any line can pass: a CSV or Excel export with PO number, PO line or item code, quantity received, date received and who received it. Without it every line is receipt absent.",
              to: "/receiving",
              action: "Load the receiving file",
            }
          : ob.files === 0 && can("upload")
            ? { title: `Upload the invoices for ${monthName(month)}`, body: "PDF files; drag them all at once.", to: "/intake", action: "Upload invoices" }
            : ob.processed > 0
              ? { title: "Work the exception queue", body: "Each open exception needs a decision before the report is approved.", to: "/exceptions", action: "Open the queue" }
              : null;
  return (
    <>
      <PageHead
        title="Onboarding checklist"
        lede="Four things MatchDesk needs for a back-test. Steps 3 and 4 can be done in either order."
        actions={
          ob.processed > 0 ? (
            <Link className="btn primary" to="/exceptions">
              Go to exceptions
            </Link>
          ) : undefined
        }
      />
      {next && (
        <section className="next-task" aria-labelledby="next-h">
          <div>
            <h2 id="next-h">{next.title}</h2>
            <p>{next.body}</p>
          </div>
          <Link className="btn primary" to={next.to}>
            {next.action}
          </Link>
        </section>
      )}
      {role === "controller" && <PilotCard />}
      <div className="panel panel-body">
        <Stepper
          current={current}
          steps={[
            { label: "Connect QuickBooks", sub: ob.connected ? "Connected" : "Read-only access", done: done[0] },
            { label: "Choose the test month", sub: monthName(month), done: done[1] },
            { label: "Load receiving evidence", sub: ob.committed.length ? plural(ob.committed.length, "file") : ob.declaration ? "None kept (declared)" : "Warehouse log", done: done[2] },
            { label: "Upload invoices", sub: ob.files ? `${ob.processed} of ${ob.files} processed` : "PDF files", done: done[3] },
          ]}
        />
        <p className="muted" style={{ margin: 0 }}>
          {current < 0 ? "Setup is complete. Work the exception queue, then draft the back-test report." : `${done.filter(Boolean).length} of 4 done. Next: step ${current + 1}.`}
        </p>
      </div>
      {role !== "controller" && <PilotCard />}
      <ol className="steps">
        <li className={cls(0)}>
          <div>
            <h2>Connect QuickBooks Online</h2>
            <p className="muted">
              {ob.connected
                ? `${ob.qbo?.company_name ?? "Company"} connected. Last successful read: ${when(ob.qbo?.last_success_at) || "not yet"}`
                : "MatchDesk only reads. It never creates or changes anything in QuickBooks."}
            </p>
          </div>
          <div className="step-action">
            <StatusChip status={ob.connected ? "connected" : "disconnected"} />
          </div>
          <div style={{ gridColumn: "1 / -1" }}>
            <Link className={`btn small ${ob.connected ? "" : "primary"}`} to="/settings/quickbooks">{ob.connected ? "View the connection" : "Connect QuickBooks"}</Link>
          </div>
        </li>
        <li className={cls(1)}>
          <div>
            <h2>Choose the test month</h2>
            <p className="muted">
              MatchDesk reads every purchase order named on that month's invoices, whatever its date, with all bills and
              credits on those purchase orders.
            </p>
          </div>
          <div className="step-action muted">{plural(poCount, "purchase order")}</div>
          <div style={{ gridColumn: "1 / -1" }} className="inline-form">
            <div className="field">
              <label htmlFor="month">Test month</label>
              <input
                id="month"
                type="month"
                value={month}
                onChange={(e) => e.target.value && setParams({ month: e.target.value }, { replace: true })}
              />
            </div>
            {can("start_sync") && (
              <button className="btn" onClick={() => sync.mutate()} disabled={!ob.connected || sync.isPending || syncStatus.data?.state === "running"}>
                Read from QuickBooks
              </button>
            )}
            <div role="status" aria-live="polite" className="muted">
              {syncStatus.data &&
                (syncStatus.data.state === "succeeded"
                  ? `Read finished for ${monthName(month)}.`
                  : syncStatus.data.state === "failed"
                    ? "The read failed. The last good copy stays in use. Try again."
                    : "Reading purchase orders from QuickBooks…")}
            </div>
            {sync.error && <p className="error-text">{errorText(sync.error)}</p>}
            {ob.connected && poCount === 0 && (
              <p className="muted">
                No purchase orders were read. Check that the QuickBooks plan is Plus or Advanced with purchase orders turned on.
              </p>
            )}
          </div>
        </li>
        <li className={cls(2)}>
          <div>
            <h2>Load receiving evidence</h2>
            <p className="muted">
              For those purchase orders, for any date, and say what kind it is. MatchDesk counts warehouse receiving records
              and delivery documents your receiver has signed or marked. It does not count the "received" quantity on a
              QuickBooks purchase order, or a supplier's packing slip with no receiver marks.
            </p>
            {ob.committed.length > 0 && (
              <p>
                Receiving: {plural(ob.committed.length, "file")}, {plural(lines, "line")}.
              </p>
            )}
            {att && (
              <p className="small" data-testid="attestation">
                Attested by {att.attested_by_name ?? "the controller"} on {when(att.attested_at)}: class {att.evidence_class} evidence, {att.source_description}.
              </p>
            )}
          </div>
          <div className="step-action">
            <StatusChip
              status={ob.committed.length || ob.declaration ? "succeeded" : "queued"}
              word={ob.committed.length ? "Loaded" : ob.declaration ? "None kept" : "Not started"}
            />
          </div>
          <div style={{ gridColumn: "1 / -1" }}>
            {!ob.declaration && (
              <Link className={`btn small ${current === 2 ? "primary" : ""}`} to="/receiving">Load a receiving file</Link>
            )}
            <NoReceivingRecords declaration={ob.declaration} statement={ob.statement} hasImports={ob.committed.length > 0} />
          </div>
        </li>
        <li className={cls(3)}>
          <div>
            <h2>Upload the month's invoices and credit notes</h2>
            <p className="muted">
              And earlier invoices on the same purchase orders, where MatchDesk asks for them.
              {ob.files > 0 && ` ${plural(ob.files, "file")} uploaded, ${ob.processed} processed.`}
            </p>
            {earlier.length > 0 && (
              <div className="earlier-needed" data-testid="earlier-invoices">
                <p className="small">
                  <strong>Earlier invoices needed.</strong> QuickBooks shows more billed on these purchase-order lines than MatchDesk has documents for:
                </p>
                <ul className="plain-list small">
                  {earlier.map((e) => (
                    <li key={`${e.purchase_order_id}-${e.po_line_no}`}>
                      <Link to={`/purchase-orders/${e.purchase_order_id}`}>PO {e.po_number}</Link> line {e.po_line_no ?? "?"}: {e.billed_without_document_qty} {e.uom ?? ""} billed without a document
                      {e.bills_to_upload.length ? `; upload QuickBooks bill ${e.bills_to_upload.join(", ")}` : ""}.
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
          <div className="step-action">
            <StatusChip status={ob.processed ? "ready" : "queued"} word={ob.processed ? "Processed" : "Not started"} />
          </div>
          <div style={{ gridColumn: "1 / -1" }}>
            <Link className={`btn small ${current === 3 ? "primary" : ""}`} to="/intake">Upload invoices</Link>
          </div>
        </li>
      </ol>
    </>
  );
}

/** S-03 step 3 (B9): "We have no warehouse receiving records". Records a fact; it never passes a line. */
function NoReceivingRecords({
  declaration,
  statement,
  hasImports,
}: {
  declaration: NoReceivingDeclaration | null;
  statement: string;
  hasImports: boolean;
}) {
  const { can } = useSession();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [withdrawOpen, setWithdrawOpen] = useState(false);
  const [reason, setReason] = useState("");
  const done = () => {
    qc.invalidateQueries({ queryKey: ["no-receiving"] });
    qc.invalidateQueries({ queryKey: ["coverage"] });
  };
  const declare = useMutation({
    mutationFn: () => send("POST", "/api/v1/onboarding/no-receiving-declaration", {}),
    onSuccess: () => {
      setOpen(false);
      done();
      toast("Recorded: no warehouse receiving records.");
    },
  });
  const withdraw = useMutation({
    mutationFn: () => send("POST", "/api/v1/onboarding/no-receiving-declaration/withdraw", { reason }),
    onSuccess: () => {
      setWithdrawOpen(false);
      setReason("");
      done();
      toast("Withdrawn. Load the receiving file to count receipts.");
    },
  });
  if (declaration)
    return (
      <div className="declaration" data-testid="no-receiving-declared">
        <Banner tone="warn">
          <p>
            <strong>No warehouse receiving records</strong>, recorded by {declaration.declared_by_name ?? "the controller"} on{" "}
            {when(declaration.declared_at)}. Every invoiced line carries a "receipt absent" exception; price, ordered-quantity and
            duplicate checks still run; receipt coverage is 0% and the report is a two-way match only.
          </p>
        </Banner>
        {can("attest_receiving") && (
          <button className="btn small" onClick={() => setWithdrawOpen(true)}>
            Withdraw this statement
          </button>
        )}
        <Dialog
          open={withdrawOpen}
          title="Withdraw the statement"
          description="Do this when receiving records are found. Committing a receiving file also withdraws it."
          onClose={() => setWithdrawOpen(false)}
          footer={
            <>
              <button className="btn" data-safe onClick={() => setWithdrawOpen(false)}>
                Cancel
              </button>
              <button className="btn primary" disabled={reason.trim().length < 3 || withdraw.isPending} onClick={() => withdraw.mutate()}>
                Withdraw
              </button>
            </>
          }
        >
          <div className="field">
            <label htmlFor="nr-reason">Why</label>
            <textarea id="nr-reason" rows={2} value={reason} onChange={(e) => setReason(e.target.value)} />
          </div>
          {withdraw.error && <p className="error-text">{errorText(withdraw.error)}</p>}
        </Dialog>
      </div>
    );
  return (
    <div className="declaration">
      <p className="muted small" style={{ marginTop: 6 }}>
        No warehouse receiving records at all? The controller can record that here. Every line then carries a "receipt
        absent" exception and the report is two-way only.
      </p>
      {can("attest_receiving") && !hasImports && (
        <button className="btn small" onClick={() => setOpen(true)}>
          We have no warehouse receiving records
        </button>
      )}
      <Dialog
        open={open}
        title="We have no warehouse receiving records"
        description="This is recorded with your name and shown on the report. It does not pass any line."
        onClose={() => setOpen(false)}
        footer={
          <>
            <button className="btn" data-safe onClick={() => setOpen(false)}>
              Cancel
            </button>
            <button className="btn primary" disabled={declare.isPending} onClick={() => declare.mutate()}>
              Record this statement
            </button>
          </>
        }
      >
        <p>{statement}</p>
        <ul className="plain-list">
          <li>Receipt coverage is set to 0%.</li>
          <li>Every invoiced line carries a "receipt absent" exception. None is shown as matched.</li>
          <li>Price, ordered-quantity and duplicate checks still run.</li>
        </ul>
        {declare.error && <p className="error-text">{errorText(declare.error)}</p>}
      </Dialog>
    </div>
  );
}
