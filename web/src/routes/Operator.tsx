import { useEffect, useState } from "react";
import { Link, Route, Routes, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Building2, Eye, Plus } from "lucide-react";
import { ApiError, errorText, get, send } from "../api/client";
import type { DeletionRequest, Me, OperatorTenant, Page, Pilot } from "../api/types";
import { useSession } from "../app/session";
import { Banner, Dialog, Empty, ErrorState, Field, Loading, PageHead, StatusChip, toast, usePageTitle } from "../components/ui";
import { cad } from "../lib/decimal";
import { day, plural, when } from "../lib/format";
import { OUTCOME_WORDS, PAYMENT_WORDS } from "./Pilot";
import { archiveSnapshotText, DeletionStateChip } from "./AccountData";

/** S-18: the operator's console. Accounts, pilot records, billable units and support access; never an
 * account's documents, which open only inside a support grant the account's controller gave. */
export function OperatorPage() {
  return (
    <Routes>
      <Route index element={<TenantList />} />
      <Route path=":tenantId" element={<TenantDetail />} />
    </Routes>
  );
}

function TenantList() {
  usePageTitle("Operator console");
  const qc = useQueryClient();
  const navigate = useNavigate();
  const list = useQuery({ queryKey: ["operator", "tenants"], queryFn: () => get<Page<OperatorTenant>>("/api/v1/operator/tenants") });
  const [name, setName] = useState("");
  const create = useMutation({
    mutationFn: () => send<OperatorTenant>("POST", "/api/v1/operator/tenants", { name }),
    onSuccess: (t) => {
      qc.invalidateQueries({ queryKey: ["operator"] });
      navigate(`/operator/tenants/${t.id}`);
    },
  });
  return (
    <>
      <PageHead
        title="Operator console"
        lede="Accounts, what each agreed and paid, and billable units. An account's documents open only with support access its controller grants."
      />
      <form
        className="inline-form panel panel-body"
        style={{ marginBottom: 16 }}
        onSubmit={(e) => {
          e.preventDefault();
          if (name.trim().length >= 2) create.mutate();
        }}
      >
        <div className="field">
          <label htmlFor="t-name">New pilot account</label>
          <input id="t-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Company name" />
        </div>
        <button className="btn" type="submit" disabled={create.isPending || name.trim().length < 2}>
          <Plus size={16} aria-hidden="true" />
          Create account
        </button>
        {create.error && <span className="error-text">{errorText(create.error)}</span>}
      </form>
      <DeletionRequests />
      {list.isLoading && <Loading />}
      {list.error && <ErrorState error={list.error} retry={() => list.refetch()} />}
      {list.data && list.data.items.length === 0 && (
        <div className="panel">
          <Empty title="No accounts yet" icon={<Building2 size={22} />}>
            <p>Create the first pilot account above.</p>
          </Empty>
        </div>
      )}
      {list.data && list.data.items.length > 0 && (
        <div className="table-wrap">
          <table className="stack-sm">
            <caption className="sr-only">Accounts</caption>
            <thead>
              <tr>
                <th scope="col">Account</th>
                <th scope="col">Status</th>
                <th scope="col">Pilot</th>
                <th scope="col">Payment</th>
                <th scope="col" className="num">Billable units</th>
                <th scope="col">Support access</th>
              </tr>
            </thead>
            <tbody>
              {list.data.items.map((t) => (
                <tr key={t.id}>
                  <td data-label="Account">
                    <Link to={`/operator/tenants/${t.id}`}>{t.name}</Link>
                  </td>
                  <td data-label="Status">
                    <StatusChip status={t.status} />
                  </td>
                  <td data-label="Pilot">
                    {t.pilot ? `${cad(t.pilot.price)}, ${day(t.pilot.period_start)} to ${day(t.pilot.period_end)}` : <span className="muted">No record yet</span>}
                  </td>
                  <td data-label="Payment">{t.pilot ? PAYMENT_WORDS[t.pilot.payment_status] : "–"}</td>
                  <td className="num" data-label="Billable units">{t.usage_units}</td>
                  <td data-label="Support access">
                    {t.active_grant ? "Granted" : t.pending_requests ? "Requested" : <span className="muted">None</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

const EMPTY_FORM = {
  price: "500.00",
  period_start: "",
  period_end: "",
  refund_threshold: "500.00",
  refund_condition: "",
  signed_terms_ref: "",
  signed_by_name: "",
  signed_by_role: "controller",
  delivery_mode: "application",
  payment_status: "unpaid",
  outcome: "",
};

function TenantDetail() {
  const { tenantId } = useParams();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { signedIn } = useSession();
  const q = useQuery({ queryKey: ["operator", "tenant", tenantId], queryFn: () => get<OperatorTenant>(`/api/v1/operator/tenants/${tenantId}`) });
  usePageTitle("Operator console", q.data?.name);
  const [form, setForm] = useState<Record<string, string>>(EMPTY_FORM);
  const [msg, setMsg] = useState<string | null>(null);
  const [hours, setHours] = useState("24");
  const [reason, setReason] = useState("");
  const p = q.data?.pilot ?? null;
  useEffect(() => {
    if (!q.data) return;
    const src: Partial<Pilot> = q.data.pilot ?? {};
    setForm(Object.fromEntries(Object.keys(EMPTY_FORM).map((k) => [k, String((src as Record<string, unknown>)[k] ?? (EMPTY_FORM as Record<string, string>)[k] ?? "")])));
  }, [q.data]);
  const save = useMutation({
    mutationFn: () => {
      const body = Object.fromEntries(Object.entries(form).filter(([k, v]) => v !== "" || k === "signed_terms_ref"));
      if (p?.governing_report_id) delete body.refund_threshold;
      return send<Pilot>("PUT", `/api/v1/operator/tenants/${tenantId}/pilot`, body, p ? { ifMatch: p.version } : undefined);
    },
    onSuccess: () => {
      setMsg(null);
      qc.invalidateQueries({ queryKey: ["operator"] });
      toast(p ? "Pilot record saved." : "Pilot record created.");
    },
    onError: (err) => setMsg(err instanceof ApiError && err.status === 409 ? "Someone changed this record meanwhile. The current values are shown; check them and save again." : errorText(err)),
  });
  const ask = useMutation({
    mutationFn: () => send("POST", `/api/v1/operator/tenants/${tenantId}/support-grants`, { hours: Number(hours), reason }),
    onSuccess: () => {
      setReason("");
      qc.invalidateQueries({ queryKey: ["operator"] });
      toast("Request sent. A controller of the account grants it under Users and access.");
    },
  });
  const enter = useMutation({
    mutationFn: async (grantId: string) => {
      await send("POST", "/api/v1/operator/support-session", { grant_id: grantId });
      return get<Me>("/api/v1/me");
    },
    onSuccess: (fresh) => {
      qc.removeQueries({ predicate: (x) => x.queryKey[0] !== "me" });
      signedIn(fresh); // the session now carries the account: its screens, read only
      navigate("/exceptions");
    },
  });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorState error={q.error} retry={() => q.refetch()} />;
  const t = q.data!;
  const set = (k: string, v: string) => setForm((f) => ({ ...f, [k]: v }));
  const fixedThreshold = !!p?.governing_report_id;
  const active = (t.grants ?? []).find((g) => g.status === "active");
  return (
    <>
      <PageHead
        title={t.name}
        crumbs={<Link to="/operator/tenants">Operator console</Link>}
        lede={`Account created ${when(t.created_at)}. Intake address: ${t.intake_address ?? "not set"}.`}
      />
      {/* B8: payment, pilot and support access read first; editing comes after. */}
      <dl className="op-summary" aria-label="Account at a glance">
        <div>
          <dt>Payment</dt>
          <dd className={p?.payment_status === "paid" ? "ok" : "warn"}>{p ? PAYMENT_WORDS[p.payment_status] ?? p.payment_status : "No pilot record"}</dd>
          {p && <span className="n">{cad(p.price)} pilot</span>}
        </div>
        <div>
          <dt>Pilot</dt>
          <dd>{p ? `${day(p.period_start)} to ${day(p.period_end)}` : "Not set"}</dd>
          {p && (
            <span className="n">
              {p.outcome ? OUTCOME_WORDS[p.outcome] : "Outcome not decided"}
              {p.governing_report_id ? `; governing report chosen, ${p.refund_due ? "refund applies" : "no refund"}` : "; no governing report yet"}
            </span>
          )}
        </div>
        <div>
          <dt>Support access</dt>
          <dd className={active ? "review" : ""}>{active ? `Active until ${when(active.ends_at)}` : (t.grants ?? []).some((g) => g.status === "requested") ? "Requested, waiting" : "None"}</dd>
          {active ? (
            <button className="btn small primary" disabled={enter.isPending} onClick={() => enter.mutate(active.id)}>
              <Eye size={15} aria-hidden="true" />
              Open the account, read only
            </button>
          ) : (
            <a className="n" href="#access-h">
              Ask for access
            </a>
          )}
        </div>
        <div>
          <dt>Billable units</dt>
          <dd className="num">{t.usage_units}</dd>
        </div>
      </dl>
      <div className="operator-grid">
        <section className="panel" aria-labelledby="pilot-h">
          <div className="panel-head">
            <h2 id="pilot-h">Edit the pilot record</h2>
            {p && <span className="muted small">Version {p.version}</span>}
          </div>
          <form
            className="panel-body"
            onSubmit={(e) => {
              e.preventDefault();
              save.mutate();
            }}
          >
            <div className="form-grid">
              <Field label="Price (CAD)">{(f) => <input id={f.id} className="num" inputMode="decimal" value={form.price} onChange={(e) => set("price", e.target.value)} />}</Field>
              <Field label="Refund threshold (CAD)" hint={fixedThreshold ? "Fixed: the governing version is chosen" : undefined}>
                {(f) => (
                  <input
                    id={f.id}
                    className="num"
                    inputMode="decimal"
                    value={form.refund_threshold}
                    disabled={fixedThreshold}
                    aria-describedby={f.describedBy}
                    onChange={(e) => set("refund_threshold", e.target.value)}
                  />
                )}
              </Field>
              <Field label="Pilot starts">{(f) => <input id={f.id} type="date" value={form.period_start} onChange={(e) => set("period_start", e.target.value)} />}</Field>
              <Field label="Pilot ends">{(f) => <input id={f.id} type="date" value={form.period_end} onChange={(e) => set("period_end", e.target.value)} />}</Field>
              <Field label="Signed terms reference">{(f) => <input id={f.id} value={form.signed_terms_ref} onChange={(e) => set("signed_terms_ref", e.target.value)} placeholder="Where the signed copy is filed" />}</Field>
              <Field label="Signed by">{(f) => <input id={f.id} value={form.signed_by_name} onChange={(e) => set("signed_by_name", e.target.value)} />}</Field>
              <Field label="Signer's role">
                {(f) => (
                  <select id={f.id} value={form.signed_by_role} onChange={(e) => set("signed_by_role", e.target.value)}>
                    <option value="controller">Controller</option>
                    <option value="owner">Owner</option>
                  </select>
                )}
              </Field>
              <Field label="Payment">
                {(f) => (
                  <select id={f.id} value={form.payment_status} onChange={(e) => set("payment_status", e.target.value)}>
                    {Object.entries(PAYMENT_WORDS).map(([k, v]) => (
                      <option key={k} value={k}>
                        {v}
                      </option>
                    ))}
                  </select>
                )}
              </Field>
              <Field label="Outcome">
                {(f) => (
                  <select id={f.id} value={form.outcome} onChange={(e) => set("outcome", e.target.value)}>
                    <option value="">Not decided yet</option>
                    {Object.entries(OUTCOME_WORDS).map(([k, v]) => (
                      <option key={k} value={k}>
                        {v}
                      </option>
                    ))}
                  </select>
                )}
              </Field>
            </div>
            <Field label="Refund condition" className="wide-field">
              {(f) => (
                <textarea
                  id={f.id}
                  rows={2}
                  value={form.refund_condition}
                  onChange={(e) => set("refund_condition", e.target.value)}
                  placeholder="Refunded in full if the governing approved back-test report finds qualifying discrepancies below the refund threshold."
                />
              )}
            </Field>
            {p?.governing_report_id && (
              <Banner tone="info">
                <p>
                  Governing version chosen by the account on {when(p.refund_determined_at)}: qualifying {cad(p.refund_qualifying_amount)},{" "}
                  {p.refund_due ? "refund applies" : "no refund"}.
                </p>
              </Banner>
            )}
            {msg && (
              <p className="error-text" role="alert">
                {msg}
              </p>
            )}
            <button className="btn primary" type="submit" disabled={save.isPending}>
              {p ? "Save pilot record" : "Create pilot record"}
            </button>
          </form>
        </section>
        <div className="stack">
          <section className="panel" aria-labelledby="usage-h">
            <div className="panel-head">
              <h2 id="usage-h">Billable units</h2>
              <span className="muted small">{plural(t.usage_units, "unit")} in all</span>
            </div>
            <div className="panel-body">
              {(t.usage ?? []).length === 0 ? (
                <p className="muted" style={{ margin: 0 }}>
                  None yet. One unit per invoice or credit note, in the month it is first read.
                </p>
              ) : (
                <table className="compact">
                  <caption className="sr-only">Billable units by month</caption>
                  <thead>
                    <tr>
                      <th scope="col">Month</th>
                      <th scope="col" className="num">Invoices</th>
                      <th scope="col" className="num">Credit notes</th>
                      <th scope="col" className="num">Units</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(t.usage ?? []).map((u) => (
                      <tr key={u.month}>
                        <td>{new Intl.DateTimeFormat("en-GB", { month: "long", year: "numeric" }).format(new Date(`${u.month}T12:00:00`))}</td>
                        <td className="num">{u.invoice}</td>
                        <td className="num">{u.credit_note}</td>
                        <td className="num">{u.units}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </section>
          <section className="panel" aria-labelledby="access-h">
            <div className="panel-head">
              <h2 id="access-h">Support access</h2>
            </div>
            <div className="panel-body stack">
              {active ? (
                <div className="grant-row">
                  <div>
                    <StatusChip status="active" /> Granted by {active.granted_by_name ?? "a controller"} until {when(active.ends_at)}.
                    <div className="small muted">Read only. Every visit is in the account&apos;s audit log.</div>
                  </div>
                </div>
              ) : (
                <p style={{ margin: 0 }} className="muted">
                  No access now. You cannot see this account&apos;s documents, exceptions or reports.
                </p>
              )}
              {enter.error && <p className="error-text">{errorText(enter.error)}</p>}
              {(t.grants ?? [])
                .filter((g) => g.status === "requested")
                .map((g) => (
                  <p key={g.id} style={{ margin: 0 }}>
                    <StatusChip status="requested" /> {plural(g.hours_requested, "hour")} asked {when(g.requested_at)}; waiting for a controller.
                  </p>
                ))}
              <form
                className="stack"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (reason.trim().length >= 3) ask.mutate();
                }}
              >
                <div className="form-grid">
                  <Field label="Ask for">
                    {(f) => (
                      <select id={f.id} value={hours} onChange={(e) => setHours(e.target.value)}>
                        <option value="4">4 hours</option>
                        <option value="24">24 hours</option>
                        <option value="72">3 days</option>
                        <option value="168">7 days</option>
                      </select>
                    )}
                  </Field>
                  <Field label="Reason the controller will see">{(f) => <input id={f.id} value={reason} onChange={(e) => setReason(e.target.value)} />}</Field>
                </div>
                <div>
                  <button className="btn" type="submit" disabled={ask.isPending || reason.trim().length < 3}>
                    Ask for support access
                  </button>
                  {ask.error && <span className="error-text"> {errorText(ask.error)}</span>}
                </div>
              </form>
              {(t.grants ?? []).filter((g) => !["active", "requested"].includes(g.status)).length > 0 && (
                <details>
                  <summary className="small">Earlier access</summary>
                  <ul className="plain-list small" style={{ marginTop: 8 }}>
                    {(t.grants ?? [])
                      .filter((g) => !["active", "requested"].includes(g.status))
                      .map((g) => (
                        <li key={g.id}>
                          {g.status === "declined" ? "Declined" : "Ended"}: {plural(g.hours_requested, "hour")} asked {when(g.requested_at)}
                        </li>
                      ))}
                  </ul>
                </details>
              )}
            </div>
          </section>
        </div>
      </div>
    </>
  );
}

/** B9, S-18: account deletion requests from controllers. Scheduling gives 30 days' notice; the
 * deletion then runs by itself and leaves only a ledger record. */
function DeletionRequests() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["operator", "deletions"], queryFn: () => get<{ items: DeletionRequest[] }>("/api/v1/operator/deletion-requests") });
  const [pick, setPick] = useState<{ r: DeletionRequest; decision: "schedule" | "decline" } | null>(null);
  const [note, setNote] = useState("");
  const decide = useMutation({
    mutationFn: () => send<{ request: DeletionRequest }>("POST", `/api/v1/operator/deletion-requests/${pick!.r.id}/decision`, { decision: pick!.decision, note: note.trim() || null }, { ifMatch: pick!.r.version }),
    onSuccess: (x) => {
      qc.invalidateQueries({ queryKey: ["operator"] });
      toast(x.request.status === "scheduled" ? `Deletion scheduled for ${day(x.request.delete_after)}.` : "Deletion request declined.");
      setPick(null);
      setNote("");
    },
  });
  const items = q.data?.items ?? [];
  const open = items.filter((r) => r.status === "requested" || r.status === "scheduled" || r.status === "deleting");
  if (!items.length) return null;
  return (
    <section className="panel" aria-labelledby="del-h" style={{ marginBottom: 16 }}>
      <div className="panel-head">
        <h2 id="del-h">Account deletion requests</h2>
        <span className="muted small">{plural(open.length, "open request")}</span>
      </div>
      <div className="panel-body stack">
        {items.slice(0, 10).map((r) => (
          <div key={r.id} className="grant-row">
            <div>
              <DeletionStateChip status={r.status} />{" "}
              <strong>{r.tenant_name ?? "Account"}</strong>: asked {when(r.requested_at)}
              {r.reason ? `. Reason: ${r.reason}` : ""}.
              {r.status === "scheduled" && <div className="small muted">Deletes on {day(r.delete_after)} unless the controller cancels.</div>}
              {r.status === "deleting" && <div className="small">Deleting now (started {when(r.claimed_at)}); it can no longer be cancelled.</div>}
              {r.archive && (
                <div className={`small ${r.archive.state === "complete" ? "muted" : "error-text"}`} data-testid="op-archive">
                  Archive: {archiveSnapshotText(r.archive)}
                  {r.archive.acknowledged ? "; the controller acknowledged deletion without a complete archive" : ""}.
                </div>
              )}
              {r.decision_note && <div className="small muted">Note: {r.decision_note}</div>}
            </div>
            {r.status === "requested" && (
              <div className="actions">
                <button className="btn small" onClick={() => setPick({ r, decision: "decline" })}>
                  Decline
                </button>
                <button className="btn small danger" onClick={() => setPick({ r, decision: "schedule" })}>
                  Schedule deletion
                </button>
              </div>
            )}
          </div>
        ))}
      </div>
      <Dialog
        open={!!pick}
        title={pick?.decision === "schedule" ? `Schedule deletion of ${pick?.r.tenant_name ?? "this account"}` : "Decline the deletion request"}
        description={
          pick?.decision === "schedule"
            ? "In 30 days every file and row of the account is deleted, approved reports and the audit log with them; only a ledger record stays. The controller can cancel until then."
            : "The account stays as it is. Say why; the controller sees the note."
        }
        onClose={() => setPick(null)}
        footer={
          <>
            <button className="btn" data-safe onClick={() => setPick(null)}>
              Cancel
            </button>
            <button className={`btn ${pick?.decision === "schedule" ? "danger" : "primary"}`} disabled={decide.isPending} onClick={() => decide.mutate()}>
              {pick?.decision === "schedule" ? "Schedule deletion" : "Decline"}
            </button>
          </>
        }
      >
        <div className="field">
          <label htmlFor="del-note">Note{pick?.decision === "decline" ? "" : " (optional)"}</label>
          <textarea id="del-note" rows={2} value={note} maxLength={2000} onChange={(e) => setNote(e.target.value)} />
        </div>
        {decide.error && <p className="error-text">{errorText(decide.error)}</p>}
      </Dialog>
    </section>
  );
}
