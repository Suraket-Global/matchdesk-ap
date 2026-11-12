import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { errorText, get, send } from "../api/client";
import type { QboConnection, SyncRun } from "../api/types";
import { useSession } from "../app/session";
import { Banner, Dialog, ErrorState, Field, Loading, PageHead, StatusChip, toast, usePageTitle } from "../components/ui";
import { lastMonth, monthRange, when } from "../lib/format";

const READS = "purchase orders, bills, vendor credits, vendors and items";

/** S-04. Controller connects and disconnects; controller and clerk start a read; viewer reads status. */
export function QuickbooksPage() {
  usePageTitle("QuickBooks connection");
  const { can } = useSession();
  const qc = useQueryClient();
  const [params] = useSearchParams();
  const result = params.get("result");
  const conn = useQuery({ queryKey: ["qbo", "connection"], queryFn: () => get<QboConnection>("/api/v1/qbo/connection") });
  const [confirmConnect, setConfirmConnect] = useState(false);
  const [confirmDisconnect, setConfirmDisconnect] = useState(false);
  const ym = lastMonth();
  const [start, setStart] = useState(monthRange(ym).start);
  const [end, setEnd] = useState(monthRange(ym).end);
  const [run, setRun] = useState<SyncRun | null>(null);
  const connect = useMutation({
    mutationFn: () => send<{ authorization_url: string }>("POST", "/api/v1/qbo/connection/authorize"),
    onSuccess: (r) => window.location.assign(r.authorization_url),
  });
  const disconnect = useMutation({
    mutationFn: () => send<QboConnection>("DELETE", "/api/v1/qbo/connection"),
    onSuccess: () => {
      setConfirmDisconnect(false);
      qc.invalidateQueries({ queryKey: ["qbo"] });
      toast("QuickBooks disconnected.");
    },
  });
  const sync = useMutation({
    mutationFn: () => send<SyncRun>("POST", "/api/v1/qbo/sync-runs", { mode: "date_range", range_start: start, range_end: end }),
    onSuccess: (r) => setRun(r),
  });
  const status = useQuery({
    queryKey: ["sync-run", run?.id],
    queryFn: () => get<SyncRun>(`/api/v1/qbo/sync-runs/${run?.id}`),
    enabled: !!run,
    // Stops on a finished run, and on an error so a failing request is not repeated forever (review, minor).
    refetchInterval: (q) => (q.state.error || (q.state.data && ["succeeded", "failed"].includes(q.state.data.state)) ? false : 2000),
    retry: 2,
  });
  if (conn.isLoading) return <Loading />;
  if (conn.error) return <ErrorState error={conn.error} retry={() => conn.refetch()} />;
  const c = conn.data!;
  const connected = c.status === "connected";
  const recorded = c.mode !== "intuit";
  const running = status.data && !["succeeded", "failed"].includes(status.data.state);
  const counts = (status.data?.counts ?? null) as Record<string, number> | null;
  return (
    <>
      <PageHead
        title="QuickBooks connection"
        crumbs={<a href="/settings">Settings</a>}
        lede="MatchDesk only reads. It never creates or changes anything in QuickBooks."
      />
      {recorded && (
        <Banner tone="warn">
          <p>
            <strong>Recorded-response mode.</strong> This server reads invented QuickBooks responses recorded for the demo, not
            a real QuickBooks company. The live connection is not built: it needs the owner&apos;s Intuit developer account and
            the sandbox check (task T-1.1.1). The step that remains is to run that check, then write the live reader from what
            it records.
          </p>
        </Banner>
      )}
      {result === "connected" && <Banner tone="ok">Connected. Read the test month to bring in its purchase orders.</Banner>}
      {result === "refused" && <Banner tone="warn">Connection was cancelled. Nothing changed.</Banner>}
      <div className="grid-2">
        <section className="panel" aria-labelledby="conn-h">
          <div className="panel-head">
            <h2 id="conn-h">Connection</h2>
            <StatusChip status={connected ? "connected" : "disconnected"} />
          </div>
          <div className="panel-body">
            <dl className="facts">
              <dt>Company</dt>
              <dd>{c.company_name ?? "None"}</dd>
              <dt>Last successful read</dt>
              <dd>{when(c.last_success_at) || "Not yet"}</dd>
              <dt>Permission granted</dt>
              <dd>{c.scopes_granted ?? "None"}</dd>
              {c.delete_after && (
                <>
                  <dt>Copied data deleted on</dt>
                  <dd>{when(c.delete_after)}</dd>
                </>
              )}
            </dl>
            <p className="muted small" style={{ marginTop: 12 }}>
              MatchDesk reads {READS}.
            </p>
            {can("connect_qbo") && (
              <div className="actions" style={{ marginTop: 12 }}>
                {!connected && (
                  <button className="btn primary" disabled={recorded} onClick={() => setConfirmConnect(true)}>
                    Connect to QuickBooks
                  </button>
                )}
                {connected && (
                  <button className="btn danger" onClick={() => setConfirmDisconnect(true)}>
                    Disconnect
                  </button>
                )}
              </div>
            )}
            {!connected && recorded && can("connect_qbo") && (
              <p className="muted small">In recorded-response mode the connection is made by make seed-demo.</p>
            )}
          </div>
        </section>
        {can("start_sync") && (
          <section className="panel" aria-labelledby="read-h">
            <div className="panel-head">
              <h2 id="read-h">Read now</h2>
            </div>
            <div className="panel-body">
              <div className="inline-form">
                <Field label="From">{(f) => <input id={f.id} type="date" value={start} onChange={(e) => setStart(e.target.value)} />}</Field>
                <Field label="To">{(f) => <input id={f.id} type="date" value={end} onChange={(e) => setEnd(e.target.value)} />}</Field>
                <button className="btn" disabled={!connected || sync.isPending || !!running} onClick={() => sync.mutate()}>
                  Read now
                </button>
              </div>
              <div role="status" aria-live="polite" style={{ marginTop: 12 }}>
                {running && <p>Reading from QuickBooks… {status.data?.pages_read ? `${status.data.pages_read} pages so far.` : ""}</p>}
                {status.data?.state === "succeeded" && (
                  <p>
                    Read finished.{" "}
                    {counts &&
                      Object.entries(counts)
                        .map(([k, v]) => `${v} ${k.replace(/_/g, " ")}`)
                        .join(", ")}
                  </p>
                )}
                {status.data?.state === "failed" && (
                  <p className="error-text">The read failed ({String(status.data.error_code ?? "unknown")}). The last good copy stays in use.</p>
                )}
              </div>
              {sync.error && <p className="error-text">{errorText(sync.error)}</p>}
            </div>
          </section>
        )}
      </div>
      <Dialog
        open={confirmConnect}
        title="Connect to QuickBooks"
        onClose={() => setConfirmConnect(false)}
        footer={
          <>
            <button className="btn" data-safe onClick={() => setConfirmConnect(false)}>
              Cancel
            </button>
            <button className="btn primary" onClick={() => connect.mutate()} disabled={connect.isPending}>
              Continue to Intuit
            </button>
          </>
        }
      >
        <p>
          You will choose the company on Intuit's page. MatchDesk reads {READS}, and keeps a copy to match against. It never
          writes to QuickBooks. The copy is deleted 30 days after you disconnect.
        </p>
        {connect.error && <p className="error-text">{errorText(connect.error)}</p>}
      </Dialog>
      <Dialog
        open={confirmDisconnect}
        title="Disconnect QuickBooks"
        onClose={() => setConfirmDisconnect(false)}
        footer={
          <>
            <button className="btn" data-safe onClick={() => setConfirmDisconnect(false)}>
              Keep connected
            </button>
            <button className="btn danger" onClick={() => disconnect.mutate()} disabled={disconnect.isPending}>
              Disconnect
            </button>
          </>
        }
      >
        <p>
          Matching on QuickBooks data stops at once. Approved reports stay exportable for 30 days, then the copied QuickBooks
          data is deleted. Reconnecting needs your consent on Intuit's page again.
        </p>
        {disconnect.error && <p className="error-text">{errorText(disconnect.error)}</p>}
      </Dialog>
    </>
  );
}
