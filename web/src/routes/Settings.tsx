import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { errorText, get, send } from "../api/client";
import type { Invitation, Page, SupportGrant, Tolerance, UserRow, Vendor } from "../api/types";
import { useSession } from "../app/session";
import { SETTINGS_NAV } from "../app/routes";
import { Banner, Dialog, ErrorState, Field, Loading, PageHead, StatusChip, toast, usePageTitle } from "../components/ui";
import { AMOUNT_INPUT, compareDecimal, money, multiply, numberError, plainNumber, type NumberRules } from "../lib/decimal";
import { plural, when } from "../lib/format";
import { ROLES } from "../lib/words";
import { AccountDataPanel } from "./AccountData";
import { UsagePanel } from "./Usage";

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

const TOL_INPUT: NumberRules = { places: 4, whole: 10 };

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
    for (const f of FIELDS) {
      const e = numberError(vals[f.key], TOL_INPUT);
      if (e || !plainNumber(vals[f.key], TOL_INPUT)) return `${f.label}: ${e ?? "type a number of 0 or more."}`;
    }
    if (compareDecimal(plainNumber(vals.price_tol_pct, TOL_INPUT), "10") > 0) return "The price tolerance percent can be at most 10.";
    if (scope === "default") {
      const l = plainNumber(limit, AMOUNT_INPUT);
      const c = plainNumber(cap, AMOUNT_INPUT);
      if (!l || !c) return `Waiver limit and cap: ${numberError(limit, AMOUNT_INPUT) ?? numberError(cap, AMOUNT_INPUT) ?? "type both amounts."}`;
      if (compareDecimal(c, l) < 0) return "The 30-day cap must be at least the waiver limit.";
    }
    return null;
  };
  // Sent as plain decimals ("1,000" -> "1000"); validate() has refused anything that cannot be read.
  const plainVals = () => Object.fromEntries(FIELDS.map((f) => [f.key, plainNumber(vals[f.key], TOL_INPUT)]));
  // B10 (outside QA item 14): a live example on the last valid values, and the lines a save would
  // re-match, previewed while typing (the preview changes nothing).
  const invalid = validate();
  const lastValid = useRef<Record<string, string> | null>(null);
  if (!invalid && Object.keys(vals).length) lastValid.current = plainVals();
  const [live, setLive] = useState<{ lines_rematched: number; exceptions_cleared: number } | null>(null);
  const liveKey = invalid ? "" : JSON.stringify([scope, plainVals()]);
  useEffect(() => {
    if (!editable || !liveKey) return;
    let gone = false;
    const t = window.setTimeout(() => {
      send<{ lines_rematched: number; exceptions_cleared: number }>("POST", "/api/v1/tolerances/preview", { ...JSON.parse(liveKey)[1], vendor_id: scope === "default" ? null : scope })
        .then((p) => !gone && setLive(p))
        .catch(() => !gone && setLive(null));
    }, 500);
    return () => {
      gone = true;
      window.clearTimeout(t);
    };
  }, [liveKey, editable, scope]);
  const doPreview = useMutation({
    mutationFn: () => send<{ lines_rematched: number; exceptions_cleared: number }>("POST", "/api/v1/tolerances/preview", { ...plainVals(), vendor_id: scope === "default" ? null : scope }),
    onSuccess: (p) => {
      setPreview(p);
      setConfirm(true);
    },
  });
  const save = useMutation({
    mutationFn: () =>
      send("PUT", `/api/v1/tolerances/${scope}`, { ...plainVals(), ...(scope === "default" ? { waiver_limit: plainNumber(limit, AMOUNT_INPUT), waiver_period_cap: plainNumber(cap, AMOUNT_INPUT) } : {}) }),
    onSuccess: () => {
      setConfirm(false);
      qc.invalidateQueries({ queryKey: ["tolerances"] });
      qc.invalidateQueries({ queryKey: ["exceptions"] });
      toast("Saved as a new version. Affected lines are being re-matched.", "info");
    },
  });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorState error={q.error} />;
  const d = q.data!;
  const name = (id: string | null) => (id ? vendors.data?.items.find((v) => v.id === id)?.name ?? "Supplier" : "Account default");
  return (
    <>
      <PageHead title="Tolerances" crumbs={<Link to="/settings">Settings</Link>} lede={editable ? "Each save creates a new version; earlier results keep the version they used." : "Read only for your role."} />
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
          <div className="form-grid">
            {FIELDS.map((f) => (
              <Field key={f.key} label={f.label} hint={f.hint}>
                {(ids) => (
                  <>
                    <input
                      id={ids.id}
                      inputMode="decimal"
                      className="num"
                      value={vals[f.key] ?? ""}
                      disabled={!editable}
                      aria-invalid={numberError(vals[f.key], TOL_INPUT) ? true : undefined}
                      aria-describedby={ids.describedBy}
                      onChange={(e) => setVals({ ...vals, [f.key]: e.target.value })}
                    />
                    {numberError(vals[f.key], TOL_INPUT) && <span className="error-text small">{numberError(vals[f.key], TOL_INPUT)}</span>}
                  </>
                )}
              </Field>
            ))}
          </div>
          {scope === "default" && (
            <div className="form-grid form-grid-gap">
              <Field label="Clerk waiver limit per item (CAD)">{(f) => <input id={f.id} inputMode="decimal" className="num" value={limit} disabled={!editable} onChange={(e) => setLimit(e.target.value)} />}</Field>
              <Field label="Clerk waiver cap per 30 days (CAD)">{(f) => <input id={f.id} inputMode="decimal" className="num" value={cap} disabled={!editable} onChange={(e) => setCap(e.target.value)} />}</Field>
            </div>
          )}
          <ToleranceExample values={lastValid.current} invalid={invalid} />
          {err && (
            <p className="error-text" role="alert">
              {err}
            </p>
          )}
          {editable && (
            <div className="save-row">
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
              <p className="small" data-testid="tolerance-consequence" aria-live="polite">
                {invalid
                  ? "Fix the value marked above to see which lines a save would re-match."
                  : live
                    ? `Saving re-matches ${plural(live.lines_rematched, "line")}; about ${plural(live.exceptions_cleared, "exception")} would then pass. Earlier results keep the version they used.`
                    : "Checking which lines a save would re-match…"}
              </p>
            </div>
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
          This change will re-match {plural(preview?.lines_rematched ?? 0, "line")}; an estimated {plural(preview?.exceptions_cleared ?? 0, "exception")} would now pass. A missing
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
      toast("Invitation sent. It works once and expires in 7 days.", "success");
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
      toast("Saved.", "success");
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
          <table className="stack-sm">
            <caption>Members</caption>
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col">Email</th>
                <th scope="col">Role</th>
                <th scope="col">Status</th>
                <th scope="col">Last sign-in</th>
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
                    <td data-label="Name">{u.display_name}</td>
                    <td data-label="Email">{u.email}</td>
                    <td data-label="Role">
                      <label className="sr-only" htmlFor={`role-${u.membership_id}`}>
                        Role of {u.email}
                      </label>
                      <select
                        id={`role-${u.membership_id}`}
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
                    <td data-label="Status">
                      <StatusChip status={u.status} />
                    </td>
                    <td data-label="Last sign-in">{u.last_sign_in_at ? when(u.last_sign_in_at) : <span className="muted">Never</span>}</td>
                    <td data-label="Actions">
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
          <table className="stack-sm">
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
                  <td data-label="Email">{i.email}</td>
                  <td data-label="Role">{ROLES[i.role] ?? i.role}</td>
                  <td data-label="Expires">{when(i.expires_at as string)}</td>
                  <td data-label="Actions">
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
        <SupportAccessPanel />
        <UsagePanel />
        <AccountDataPanel />
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

function hoursWord(h: number): string {
  return h % 24 === 0 ? plural(h / 24, "day") : plural(h, "hour");
}

/** S-16: MatchDesk support asks; a controller grants, declines or ends read-only access (T-5.1.5). */
function SupportAccessPanel() {
  const qc = useQueryClient();
  const grants = useQuery({ queryKey: ["support-grants"], queryFn: () => get<Page<SupportGrant>>("/api/v1/support-grants") });
  const [pick, setPick] = useState<{ g: SupportGrant; decision: "grant" | "decline" | "end" } | null>(null);
  const decide = useMutation({
    mutationFn: (x: { g: SupportGrant; decision: string }) => send<SupportGrant>("POST", `/api/v1/support-grants/${x.g.id}/decision`, { decision: x.decision }),
    onSuccess: (g) => {
      setPick(null);
      qc.invalidateQueries({ queryKey: ["support-grants"] });
      toast(g.status === "active" ? `Support access granted until ${when(g.ends_at)}.` : g.status === "declined" ? "Request declined." : "Support access ended.", "success");
    },
  });
  const items = grants.data?.items ?? [];
  const active = items.filter((g) => g.status === "active");
  const requested = items.filter((g) => g.status === "requested");
  const past = items.filter((g) => !["active", "requested"].includes(g.status)).slice(0, 5);
  return (
    <section className="panel" aria-labelledby="support-h">
      <div className="panel-head">
        <h2 id="support-h">MatchDesk support access</h2>
      </div>
      <div className="panel-body stack">
        <p style={{ margin: 0 }}>
          {active.length
            ? `MatchDesk support can read this account until ${when(active[0].ends_at)}. It can never change anything, and every visit is in the audit log.`
            : "Current access: none. MatchDesk staff cannot see this account's data unless you grant it here."}
        </p>
        {grants.isLoading && <Loading />}
        {[...active, ...requested].map((g) => (
          <div key={g.id} className="grant-row">
            <div>
              <StatusChip status={g.status} />{" "}
              <strong>{g.requested_by_name ?? "MatchDesk support"}</strong> {g.status === "active" ? "has" : "asks for"} {hoursWord(g.hours_requested)} of read-only access.
              <div className="small muted">
                Reason: {g.reason}. Asked {when(g.requested_at)}
                {g.status === "active" ? `; granted by ${g.granted_by_name ?? "a controller"}, ends ${when(g.ends_at)}` : ""}.
              </div>
            </div>
            <div className="actions">
              {g.status === "requested" && (
                <>
                  <button className="btn small" onClick={() => setPick({ g, decision: "decline" })}>
                    Decline
                  </button>
                  <button className="btn small primary" onClick={() => setPick({ g, decision: "grant" })}>
                    Grant {hoursWord(g.hours_requested)}
                  </button>
                </>
              )}
              {g.status === "active" && (
                <button className="btn small danger" onClick={() => setPick({ g, decision: "end" })}>
                  End access now
                </button>
              )}
            </div>
          </div>
        ))}
        {past.length > 0 && (
          <details>
            <summary className="small">Earlier requests ({past.length})</summary>
            <ul className="plain-list small" style={{ marginTop: 8 }}>
              {past.map((g) => (
                <li key={g.id}>
                  {g.status === "declined" ? "Declined" : "Ended"}: {hoursWord(g.hours_requested)} asked {when(g.requested_at)} ({g.reason})
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>
      <Dialog
        open={!!pick}
        title={pick?.decision === "grant" ? "Grant support access?" : pick?.decision === "decline" ? "Decline the request?" : "End support access now?"}
        onClose={() => setPick(null)}
        footer={
          <>
            <button className="btn" data-safe onClick={() => setPick(null)}>
              Cancel
            </button>
            <button
              className={`btn ${pick?.decision === "end" ? "danger" : "primary"}`}
              disabled={decide.isPending}
              onClick={() => pick && decide.mutate(pick)}
            >
              {pick?.decision === "grant" ? "Grant access" : pick?.decision === "decline" ? "Decline" : "End access"}
            </button>
          </>
        }
      >
        <p>
          {pick?.decision === "grant"
            ? `MatchDesk support will be able to read this account's documents, exceptions and reports for ${hoursWord(pick.g.hours_requested)}, until about ${when(new Date(Date.now() + pick.g.hours_requested * 3_600_000).toISOString())}. It cannot change anything, and you can end it at any time.`
            : pick?.decision === "decline"
              ? "MatchDesk support will not be able to read this account. They can ask again."
              : "MatchDesk support loses access at once."}
        </p>
        {decide.error && <p className="error-text">{errorText(decide.error)}</p>}
      </Dialog>
    </section>
  );
}

/** "A PO price of CAD 10.00 passes up to CAD 10.25 per unit": the tolerances on one invented line,
 * from the last valid values (B10, item 14). */
export function ToleranceExample({ values, invalid }: { values: Record<string, string> | null; invalid: string | null }) {
  if (!values) return null;
  const price = "10.00";
  const byPct = multiply(price, values.price_tol_pct || "0", 4);
  const pct = multiply(byPct, "0.01", 4);
  const allowance = compareDecimal(values.price_tol_abs || "0", pct) >= 0 ? values.price_tol_abs || "0" : pct;
  const ceiling = addDecimal(price, allowance);
  const qtyMax = addDecimal("100", values.qty_tolerance || "0");
  return (
    <div className="tol-example" data-testid="tolerance-example" aria-live="polite">
      {invalid && <p className="error-text small">Not valid yet: {invalid} The example below uses the last valid values.</p>}
      <p className="small">
        <strong>Example:</strong> a PO price of CAD {price} passes up to CAD {money(ceiling)} per unit; 100 received passes when up to {qtyMax.replace(/\.?0+$/, "")} are invoiced;
        a freight or fee line not on the PO passes up to CAD {money(values.charge_allowance || "0")}.
      </p>
    </div>
  );
}

function addDecimal(a: string, b: string): string {
  // a + b exactly, via the same integer arithmetic as the other helpers (no floats).
  const scale = 6;
  const toInt = (v: string) => {
    const neg = v.startsWith("-");
    const [i, f = ""] = v.replace("-", "").split(".");
    const n = BigInt((i || "0") + f.padEnd(scale, "0").slice(0, scale));
    return neg ? -n : n;
  };
  const n = toInt(a) + toInt(b);
  const s = (n < 0n ? -n : n).toString().padStart(scale + 1, "0");
  return `${n < 0n ? "-" : ""}${s.slice(0, -scale)}.${s.slice(-scale)}`;
}
