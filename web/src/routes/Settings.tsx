import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { errorText, get, send } from "../api/client";
import type { Invitation, Page, Tolerance, UserRow, Vendor } from "../api/types";
import { useSession } from "../app/session";
import { SETTINGS_NAV } from "../app/routes";
import { Banner, Dialog, ErrorState, Field, Loading, NarrowNote, PageHead, StatusChip, toast, usePageTitle } from "../components/ui";
import { isDecimal, compareDecimal } from "../lib/decimal";
import { when } from "../lib/format";
import { ROLES } from "../lib/words";

export function SettingsPage() {
  usePageTitle("Settings");
  const { role } = useSession();
  return (
    <>
      <PageHead title="Settings" />
      <ul className="panel panel-body" style={{ margin: 0, listStyle: "none", display: "grid", gap: 10 }}>
        {SETTINGS_NAV.filter((n) => role && n.roles.includes(role)).map((n) => (
          <li key={n.to}>
            <Link to={n.to}>{n.label}</Link>
          </li>
        ))}
      </ul>
    </>
  );
}

interface Tolerances {
  default: Tolerance;
  vendors: Tolerance[];
  history: Tolerance[];
  waiver_limit: string;
  waiver_period_cap: string;
  receipt_note: string;
}

const FIELDS: { key: keyof Tolerance; label: string; hint: string }[] = [
  { key: "qty_tolerance", label: "Quantity tolerance", hint: "Units above received or ordered that still pass." },
  { key: "price_tol_abs", label: "Price tolerance (amount)", hint: "Per unit, in CAD." },
  { key: "price_tol_pct", label: "Price tolerance (percent)", hint: "At most 10. The larger of the two applies." },
  { key: "charge_allowance", label: "Charge allowance", hint: "Freight or fees not on the PO that still pass, in CAD." },
];

/** S-15: how much difference is acceptable per supplier and how much the clerk may waive. */
export function TolerancesPage() {
  usePageTitle("Tolerances");
  const { can } = useSession();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["tolerances"], queryFn: () => get<Tolerances>("/api/v1/tolerances") });
  const vendors = useQuery({ queryKey: ["vendors"], queryFn: () => get<Page<Vendor>>("/api/v1/vendors") });
  const [scope, setScope] = useState("default");
  const [vals, setVals] = useState<Record<string, string>>({});
  const [limit, setLimit] = useState("");
  const [cap, setCap] = useState("");
  const [preview, setPreview] = useState<{ lines_rematched: number; exceptions_cleared: number } | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const editable = can("edit_tolerances");
  useEffect(() => {
    if (!q.data) return;
    const t = scope === "default" ? q.data.default : q.data.vendors.find((v) => v.vendor_id === scope) ?? q.data.default;
    setVals(Object.fromEntries(FIELDS.map((f) => [f.key, String(t[f.key] ?? "")])));
    setLimit(q.data.waiver_limit);
    setCap(q.data.waiver_period_cap);
    setPreview(null);
  }, [q.data, scope]);
  const validate = (): string | null => {
    for (const f of FIELDS) if (!isDecimal(vals[f.key] ?? "")) return `${f.label} must be a number of 0 or more.`;
    if (compareDecimal(vals.price_tol_pct, "10") > 0) return "The price tolerance percent can be at most 10.";
    if (scope === "default" && (!isDecimal(limit) || !isDecimal(cap) || compareDecimal(cap, limit) < 0)) return "The 30-day cap must be at least the waiver limit.";
    return null;
  };
  const doPreview = useMutation({
    mutationFn: () => send<{ lines_rematched: number; exceptions_cleared: number }>("POST", "/api/v1/tolerances/preview", { ...vals, vendor_id: scope === "default" ? null : scope }),
    onSuccess: (p) => {
      setPreview(p);
      setConfirm(true);
    },
  });
  const save = useMutation({
    mutationFn: () => send("PUT", `/api/v1/tolerances/${scope}`, { ...vals, ...(scope === "default" ? { waiver_limit: limit, waiver_period_cap: cap } : {}) }),
    onSuccess: () => {
      setConfirm(false);
      qc.invalidateQueries({ queryKey: ["tolerances"] });
      qc.invalidateQueries({ queryKey: ["exceptions"] });
      toast("Saved as a new version. Affected lines are being re-matched.");
    },
  });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorState error={q.error} />;
  const d = q.data!;
  const name = (id: string | null) => (id ? vendors.data?.items.find((v) => v.id === id)?.name ?? "Supplier" : "Account default");
  return (
    <>
      <PageHead title="Tolerances" crumbs={<Link to="/settings">Settings</Link>} lede={editable ? "Each save creates a new version; earlier results keep the version they used." : "Read only for your role."} />
      <NarrowNote />
      <Banner tone="warn">
        <p>{d.receipt_note}</p>
      </Banner>
      <section className="panel" aria-labelledby="tol-h">
        <div className="panel-head">
          <h2 id="tol-h">Values</h2>
          <div className="field" style={{ margin: 0 }}>
            <label htmlFor="tol-scope" className="sr-only">
              Applies to
            </label>
            <select id="tol-scope" value={scope} onChange={(e) => setScope(e.target.value)}>
              <option value="default">Account default</option>
              {(vendors.data?.items ?? []).map((v) => (
                <option key={v.id} value={v.id}>
                  {v.name}
                  {d.vendors.some((t) => t.vendor_id === v.id) ? " (override)" : ""}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div className="panel-body">
          <div className="inline-form">
            {FIELDS.map((f) => (
              <Field key={f.key} label={f.label} hint={f.hint}>
                {(ids) => (
                  <input id={ids.id} inputMode="decimal" size={8} value={vals[f.key] ?? ""} disabled={!editable} aria-describedby={ids.describedBy} onChange={(e) => setVals({ ...vals, [f.key]: e.target.value })} />
                )}
              </Field>
            ))}
          </div>
          {scope === "default" && (
            <div className="inline-form">
              <Field label="Clerk waiver limit per item (CAD)">{(f) => <input id={f.id} inputMode="decimal" size={8} value={limit} disabled={!editable} onChange={(e) => setLimit(e.target.value)} />}</Field>
              <Field label="Clerk waiver cap per 30 days (CAD)">{(f) => <input id={f.id} inputMode="decimal" size={8} value={cap} disabled={!editable} onChange={(e) => setCap(e.target.value)} />}</Field>
            </div>
          )}
          {err && (
            <p className="error-text" role="alert">
              {err}
            </p>
          )}
          {editable && (
            <button
              className="btn primary"
              onClick={() => {
                const e = validate();
                setErr(e);
                if (!e) doPreview.mutate();
              }}
              disabled={doPreview.isPending}
            >
              Review and save
            </button>
          )}
        </div>
      </section>
      <section style={{ marginTop: 16 }} aria-labelledby="hist-h">
        <h2 id="hist-h" style={{ marginBottom: 8 }}>
          Change history
        </h2>
        {d.history.length === 0 ? (
          <p className="muted">No changes yet; the rule set's defaults apply.</p>
        ) : (
          <div className="table-wrap">
            <table className="compact">
              <thead>
                <tr>
                  <th scope="col">From</th>
                  <th scope="col">To</th>
                  <th scope="col">Applies to</th>
                  {FIELDS.map((f) => (
                    <th scope="col" key={f.key} className="num">
                      {f.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {d.history.map((t) => (
                  <tr key={t.id}>
                    <td>{when(t.valid_from)}</td>
                    <td>{t.valid_to ? when(t.valid_to) : "Current"}</td>
                    <td>{name(t.vendor_id)}</td>
                    {FIELDS.map((f) => (
                      <td key={f.key} className="num">
                        {String(t[f.key])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <Dialog
        open={confirm}
        title="Save tolerances"
        onClose={() => setConfirm(false)}
        footer={
          <>
            <button className="btn" data-safe onClick={() => setConfirm(false)}>
              Cancel
            </button>
            <button className="btn primary" disabled={save.isPending} onClick={() => save.mutate()}>
              Save new version
            </button>
          </>
        }
      >
        <p>
          This change will re-match {preview?.lines_rematched ?? 0} lines; an estimated {preview?.exceptions_cleared ?? 0} exceptions would now pass. A missing
          receiving record stays an exception whatever the tolerance.
        </p>
        {save.error && <p className="error-text">{errorText(save.error)}</p>}
      </Dialog>
    </>
  );
}

/** S-16: who is in, invitations, and support access (not built yet in the API). */
export function UsersPage() {
  usePageTitle("Users and support access");
  const qc = useQueryClient();
  const { me } = useSession();
  const users = useQuery({ queryKey: ["users"], queryFn: () => get<Page<UserRow>>("/api/v1/users") });
  const invites = useQuery({ queryKey: ["invitations"], queryFn: () => get<Page<Invitation>>("/api/v1/invitations") });
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("clerk");
  const [change, setChange] = useState<{ u: UserRow; role?: string; status?: string } | null>(null);
  const invite = useMutation({
    mutationFn: () => send("POST", "/api/v1/invitations", { email: email.trim(), role }),
    onSuccess: () => {
      setEmail("");
      qc.invalidateQueries({ queryKey: ["invitations"] });
      toast("Invitation sent. It works once and expires in 7 days.");
    },
  });
  const revoke = useMutation({
    mutationFn: (id: string) => send("DELETE", `/api/v1/invitations/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["invitations"] }),
  });
  const patch = useMutation({
    mutationFn: (c: { u: UserRow; role?: string; status?: string }) => send("PATCH", `/api/v1/memberships/${c.u.membership_id}`, { role: c.role, status: c.status }),
    onSuccess: () => {
      setChange(null);
      qc.invalidateQueries({ queryKey: ["users"] });
      toast("Saved.");
    },
  });
  if (users.isLoading) return <Loading />;
  if (users.error) return <ErrorState error={users.error} />;
  const controllers = (users.data?.items ?? []).filter((u) => u.role === "controller" && u.status === "active").length;
  return (
    <>
      <PageHead title="Users and support access" crumbs={<Link to="/settings">Settings</Link>} />
      <div className="stack">
        <form
          className="panel"
          onSubmit={(e) => {
            e.preventDefault();
            if (/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim())) invite.mutate();
          }}
        >
          <div className="panel-head">
            <h2>Invite</h2>
          </div>
          <div className="panel-body inline-form">
            <Field label="Work email">{(f) => <input id={f.id} type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />}</Field>
            <Field label="Role">
              {(f) => (
                <select id={f.id} value={role} onChange={(e) => setRole(e.target.value)}>
                  <option value="clerk">Clerk</option>
                  <option value="controller">Controller</option>
                  <option value="viewer">Viewer</option>
                </select>
              )}
            </Field>
            <button className="btn primary" type="submit" disabled={invite.isPending}>
              Send invitation
            </button>
            {invite.error && <span className="error-text">{errorText(invite.error)}</span>}
          </div>
        </form>
        <div className="table-wrap">
          <table>
            <caption>Members</caption>
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col">Email</th>
                <th scope="col">Role</th>
                <th scope="col">Status</th>
                <th scope="col">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {(users.data?.items ?? []).map((u) => {
                const self = u.user_id === me?.user.id;
                const last = u.role === "controller" && controllers <= 1;
                return (
                  <tr key={u.membership_id}>
                    <td>{u.display_name}</td>
                    <td>{u.email}</td>
                    <td>
                      <select
                        aria-label={`Role of ${u.email}`}
                        value={u.role}
                        disabled={self || last || u.status !== "active"}
                        onChange={(e) => setChange({ u, role: e.target.value })}
                      >
                        <option value="controller">Controller</option>
                        <option value="clerk">Clerk</option>
                        <option value="viewer">Viewer</option>
                      </select>
                      {last && <div className="small muted">The last controller cannot be removed or demoted.</div>}
                      {self && !last && <div className="small muted">You cannot change your own role.</div>}
                    </td>
                    <td>
                      <StatusChip status={u.status} />
                    </td>
                    <td>
                      {u.status === "active" && !self && !last && (
                        <button className="btn small danger" onClick={() => setChange({ u, status: "deactivated" })}>
                          Deactivate
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div className="table-wrap">
          <table>
            <caption>Open invitations</caption>
            <thead>
              <tr>
                <th scope="col">Email</th>
                <th scope="col">Role</th>
                <th scope="col">Expires</th>
                <th scope="col">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {(invites.data?.items ?? []).map((i) => (
                <tr key={i.id}>
                  <td>{i.email}</td>
                  <td>{ROLES[i.role] ?? i.role}</td>
                  <td>{when(i.expires_at as string)}</td>
                  <td>
                    <button className="btn small" onClick={() => revoke.mutate(i.id)}>
                      Revoke
                    </button>
                  </td>
                </tr>
              ))}
              {(invites.data?.items ?? []).length === 0 && (
                <tr>
                  <td colSpan={4} className="muted">
                    No open invitations.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <section className="panel" aria-labelledby="support-h">
          <div className="panel-head">
            <h2 id="support-h">MatchDesk support access</h2>
          </div>
          <div className="panel-body">
            <p>Current grant: none. MatchDesk staff cannot see this account's data.</p>
            <p className="muted">Allowing support access for 24 hours or 7 days is not built yet.</p>
          </div>
        </section>
      </div>
      <Dialog
        open={!!change}
        title={change?.status ? "Deactivate user" : "Change role"}
        onClose={() => setChange(null)}
        footer={
          <>
            <button className="btn" data-safe onClick={() => setChange(null)}>
              Cancel
            </button>
            <button className={`btn ${change?.status ? "danger" : "primary"}`} disabled={patch.isPending} onClick={() => change && patch.mutate(change)}>
              {change?.status ? "Deactivate" : "Change role"}
            </button>
          </>
        }
      >
        <p>
          {change?.status
            ? `Deactivate ${change.u.email}? Their sessions end at once.`
            : `Change ${change?.u.email} from ${ROLES[change?.u.role ?? ""]} to ${ROLES[change?.role ?? ""]}?`}
        </p>
        {patch.error && <p className="error-text">{errorText(patch.error)}</p>}
      </Dialog>
    </>
  );
}
