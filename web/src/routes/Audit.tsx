import { Fragment, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { download, get } from "../api/client";
import type { AuditEvent, Page, UserRow } from "../api/types";
import { Empty, ErrorState, Loading, PageHead, toast, usePageTitle } from "../components/ui";
import { when } from "../lib/format";
import { actionWord, changes, entityWord, type Change } from "../lib/audit";

function ChangeText({ c }: { c: Change }) {
  return (
    <>
      <span className="muted">{c.label}: </span>
      {c.before !== null && c.after !== null ? (
        <>
          {c.before} <span aria-label="changed to">→</span> {c.after}
        </>
      ) : (
        (c.after ?? `${c.before} (removed)`)
      )}
    </>
  );
}

/** S-17: who did what. No edit or delete control exists. Filters live in the URL. */
export function AuditPage() {
  usePageTitle("Audit log");
  const [params, setParams] = useSearchParams();
  const f = {
    actor_user_id: params.get("actor") ?? "",
    action: params.get("action") ?? "",
    entity_id: params.get("record") ?? "",
    since: params.get("since") ?? "",
    until: params.get("until") ?? "",
  };
  const qs = new URLSearchParams({ limit: "50" });
  if (f.actor_user_id) qs.set("actor_user_id", f.actor_user_id);
  if (f.action) qs.set("action", f.action);
  if (f.entity_id) qs.set("entity_id", f.entity_id);
  if (f.since) qs.set("since", `${f.since}T00:00:00`);
  if (f.until) qs.set("until", `${f.until}T23:59:59`);
  const list = useInfiniteQuery({
    queryKey: ["audit", qs.toString()],
    queryFn: ({ pageParam }) => get<Page<AuditEvent>>(`/api/v1/audit-events?${qs}${pageParam ? `&cursor=${encodeURIComponent(pageParam)}` : ""}`),
    initialPageParam: "",
    getNextPageParam: (l) => l.next_cursor ?? undefined,
  });
  const users = useQuery({ queryKey: ["users"], queryFn: () => get<Page<UserRow>>("/api/v1/users") });
  const set = (k: string, v: string) => {
    const p = new URLSearchParams(params);
    if (v) p.set(k, v);
    else p.delete(k);
    setParams(p);
  };
  const rows = (list.data?.pages ?? []).flatMap((p) => p.items);
  return (
    <>
      <PageHead
        title="Audit log"
        crumbs={<Link to="/settings">Settings</Link>}
        lede="Every change, with who made it and the values before and after."
        actions={
          <button
            className="btn"
            onClick={() => {
              const e = new URLSearchParams(qs);
              e.delete("limit");
              download(`/api/v1/audit-events/export?${e}`, "audit-log.csv").catch(() => toast("The export could not be prepared. Try again."));
            }}
          >
            Export CSV
          </button>
        }
      />
      <div className="inline-form panel panel-body" style={{ marginBottom: 12 }}>
        <div className="field">
          <label htmlFor="a-actor">Person</label>
          <select id="a-actor" value={f.actor_user_id} onChange={(e) => set("actor", e.target.value)}>
            <option value="">Everyone</option>
            {(users.data?.items ?? []).map((u) => (
              <option key={u.user_id} value={u.user_id}>
                {u.display_name || u.email}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="a-action">Action starts with</label>
          <input id="a-action" type="text" defaultValue={f.action} onBlur={(e) => set("action", e.target.value.trim())} placeholder="for example exception" />
        </div>
        <div className="field">
          <label htmlFor="a-record">Record ID</label>
          <input id="a-record" type="text" defaultValue={f.entity_id} onBlur={(e) => set("record", e.target.value.trim())} />
        </div>
        <div className="field">
          <label htmlFor="a-since">From</label>
          <input id="a-since" type="date" value={f.since} onChange={(e) => set("since", e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="a-until">To</label>
          <input id="a-until" type="date" value={f.until} onChange={(e) => set("until", e.target.value)} />
        </div>
      </div>
      {list.isLoading && <Loading />}
      {list.error && <ErrorState error={list.error} retry={() => list.refetch()} />}
      {list.data && rows.length === 0 && (
        <div className="panel">
          <Empty title="No events match these filters" />
        </div>
      )}
      {rows.length > 0 && <AuditTable rows={rows} />}
      {list.hasNextPage && (
        <button className="btn" style={{ marginTop: 12 }} onClick={() => list.fetchNextPage()}>
          Load more
        </button>
      )}
    </>
  );
}

/** Who, what, which record and what changed, in words. A row with more than two changes opens to
 * show all of them (B6 review M7: raw JSON, identifiers, an empty "Before" column, overflow). */
function AuditTable({ rows }: { rows: AuditEvent[] }) {
  const [open, setOpen] = useState<Set<string>>(new Set());
  const toggle = (id: string) =>
    setOpen((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  return (
    <div className="table-wrap">
      <table className="compact stack-sm audit-table">
        <caption className="sr-only">Audit events</caption>
        <thead>
          <tr>
            <th scope="col">Time</th>
            <th scope="col">Who</th>
            <th scope="col">What happened</th>
            <th scope="col">Changes</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((e) => {
            const cs = changes(e.before, e.after);
            const isOpen = open.has(e.id);
            const shown = isOpen ? cs : cs.slice(0, 2);
            return (
              <Fragment key={e.id}>
                <tr>
                  <td data-label="Time" className="nowrap">{when(e.occurred_at)}</td>
                  <td data-label="Who">{e.actor_name ?? (e.actor_type === "job" || e.actor_type === "system" ? "MatchDesk" : "Operator")}</td>
                  <td data-label="What happened">
                    <span className="cell-main">{actionWord(e.action)}</span>
                    <span className="cell-sub">
                      {entityWord(e.entity_type)}
                      {e.entity_id && (
                        <>
                          {" · "}
                          <Link to={`/audit?record=${e.entity_id}`}>history of this record</Link>
                        </>
                      )}
                    </span>
                  </td>
                  <td data-label="Changes" className="audit-changes">
                    {cs.length === 0 ? (
                      <span className="muted">No values recorded</span>
                    ) : (
                      <ul>
                        {shown.map((c) => (
                          <li key={c.key}>
                            <ChangeText c={c} />
                          </li>
                        ))}
                      </ul>
                    )}
                    {cs.length > 2 && (
                      <button type="button" className="btn small ghost" aria-expanded={isOpen} onClick={() => toggle(e.id)}>
                        {isOpen ? "Show fewer" : `Show all ${cs.length} changes`}
                      </button>
                    )}
                  </td>
                </tr>
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
