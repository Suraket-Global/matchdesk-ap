import { Link, useSearchParams } from "react-router-dom";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { download, get } from "../api/client";
import type { AuditEvent, Page, UserRow } from "../api/types";
import { Empty, ErrorState, Loading, PageHead, toast, usePageTitle } from "../components/ui";
import { when } from "../lib/format";

function words(action: string): string {
  return action.replace(/[._]/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

function brief(v: Record<string, unknown> | null): string {
  if (!v) return "";
  return Object.entries(v)
    .map(([k, x]) => `${k.replace(/_/g, " ")}: ${typeof x === "object" ? JSON.stringify(x) : String(x)}`)
    .join("; ");
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
      {rows.length > 0 && (
        <div className="table-wrap">
          <table className="compact">
            <thead>
              <tr>
                <th scope="col">Time</th>
                <th scope="col">Actor</th>
                <th scope="col">Action</th>
                <th scope="col">Record</th>
                <th scope="col">Before</th>
                <th scope="col">After</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((e) => (
                <tr key={e.id}>
                  <td style={{ whiteSpace: "nowrap" }}>{when(e.occurred_at)}</td>
                  <td>{e.actor_name ?? e.actor_type}</td>
                  <td>{words(e.action)}</td>
                  <td>
                    {e.entity_type.replace(/_/g, " ")}
                    {e.entity_id && (
                      <div>
                        <Link to={`/audit?record=${e.entity_id}`} className="small">
                          History of this record
                        </Link>
                      </div>
                    )}
                  </td>
                  <td className="small">{brief(e.before)}</td>
                  <td className="small">{brief(e.after)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {list.hasNextPage && (
        <button className="btn" style={{ marginTop: 12 }} onClick={() => list.fetchNextPage()}>
          Load more
        </button>
      )}
    </>
  );
}
