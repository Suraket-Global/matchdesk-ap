import { useEffect, useState } from "react";
import { AlertTriangle, Download, FileBarChart, HelpCircle, PackageCheck, PackageX, ShieldCheck } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { download, errorText, get, getAll, send } from "../api/client";
import type { Page, Refund, Report } from "../api/types";
import { useSession } from "../app/session";
import { usePeriod } from "../app/period";
import { Banner, Dialog, Empty, ErrorState, Loading, PageHead, StatusChip, toast, usePageTitle } from "../components/ui";
import { cad, cadCents, compareDecimal, formatCents, money, sumCents } from "../lib/decimal";
import { day, monthName, monthRange, plural, when } from "../lib/format";
import { typeWord, zeroCounted } from "../lib/words";
import { PilotSection, usePilot } from "./Pilot";
import { queueLink } from "../lib/queue";
import { OutcomesSection, useOutcomes } from "./ReportOutcomes";

type Finding = NonNullable<Report["findings"]>[number];

/** Queue status in the report's words; the same words as the CSV export. */
const STATUS_WORDS: Record<string, string> = {
  open: "Not yet: open in the queue",
  pending_approval: "Not yet: waiting for approval",
  resolved: "Not yet: resolved",
  waived: "Waived",
};

const byAmount = (a: Finding, b: Finding) => compareDecimal(b.amount, a.amount) || a.id.localeCompare(b.id);

function pct(v: string | null | undefined): string {
  return `${money(v).replace(/\.00$/, "")}%`;
}

function reportStatus(r: Report): string {
  return r.status === "approved" ? "approved" : r.status === "superseded" ? "superseded" : "draft";
}

/** S-13 list: one row per version; create or refresh a draft for a month. */
export function ReportsPage() {
  usePageTitle("Back-test reports");
  const { can } = useSession();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const period = usePeriod();
  const [month, setMonth] = useState(period.month);
  // Follows the top-bar period when it changes, not only on mount (B6 review minor).
  useEffect(() => setMonth(period.month), [period.month]);
  // B10: the server sorts by period and version and pages by that key; every page can be loaded.
  const list = useInfiniteQuery({
    queryKey: ["reports", "pages"],
    queryFn: ({ pageParam }) => get<Page<Report>>(`/api/v1/reports/backtest?limit=200${pageParam ? `&cursor=${encodeURIComponent(pageParam)}` : ""}`),
    initialPageParam: "",
    getNextPageParam: (l) => l.next_cursor ?? undefined,
  });
  const create = useMutation({
    mutationFn: () => send<Report>("POST", "/api/v1/reports/backtest", { period_start: monthRange(month).start, period_end: monthRange(month).end }),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["reports"] });
      navigate(`/reports/backtest/${r.id}`);
    },
  });
  const rows = (list.data?.pages ?? []).flatMap((p) => p.items);
  const pilot = usePilot();
  const governingId = pilot.data?.governing?.report_id;
  const latest = rows[0];
  const draftWaiting = rows.find((x) => x.status === "draft");
  return (
    <>
      <PageHead
        title="Back-test reports"
        lede="The controller reviews a draft, approves one version, and exports it. Approved figures never change."
        actions={
          <Link className="btn" to="/reports/weekly">
            Weekly summary
          </Link>
        }
      />
      {can("draft_report") && (
        <div className="inline-form panel panel-body" style={{ marginBottom: 16 }}>
          <div className="field">
            <label htmlFor="r-month">Test month</label>
            <input id="r-month" type="month" value={month} onChange={(e) => e.target.value && setMonth(e.target.value)} />
          </div>
          <button className="btn primary" onClick={() => create.mutate()} disabled={create.isPending}>
            {create.isPending ? "Creating draft…" : `Create draft for ${monthName(month)}`}
          </button>
          {create.error && <span className="error-text">{errorText(create.error)}</span>}
        </div>
      )}
      {latest && (
        <p className="next-decision" role="status">
          {draftWaiting ? (
            <>
              <strong>Next decision:</strong> draft version {draftWaiting.version_no} for {monthName(draftWaiting.period_start.slice(0, 7))} is waiting for approval.{" "}
              <Link to={`/reports/backtest/${draftWaiting.id}`}>Review the draft</Link>
            </>
          ) : governingId ? (
            <>
              <strong>Governing version:</strong> {(() => {
                const g = rows.find((x) => x.id === governingId);
                return g ? `${monthName(g.period_start.slice(0, 7))}, version ${g.version_no}. The refund is decided on it alone.` : "set on the pilot record.";
              })()}
            </>
          ) : (
            <>
              <strong>Next decision:</strong> choose the governing version on an approved report (section 7).
            </>
          )}
        </p>
      )}
      {list.isLoading && <Loading />}
      {list.error && <ErrorState error={list.error} />}
      {list.data && rows.length === 0 && (
        <div className="panel">
          <Empty title="No report yet" icon={<FileBarChart size={22} />}>
            <p>Create a draft for the test month when its invoices and receiving records are loaded.</p>
          </Empty>
        </div>
      )}
      {rows.length > 0 && (
        <div className="table-wrap">
          <table className="stack-sm">
            <thead>
              <tr>
                <th scope="col">Period</th>
                <th scope="col" className="num">Version</th>
                <th scope="col">Status</th>
                <th scope="col" className="num">Flagged discrepancies (CAD)</th>
                <th scope="col" className="num">of which not received</th>
                <th scope="col" className="num">Unverified (CAD)</th>
                <th scope="col">Data cut-off</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td data-label="Period">
                    <Link to={`/reports/backtest/${r.id}`}>
                      {day(r.period_start)} to {day(r.period_end)}
                    </Link>
                  </td>
                  <td className="num" data-label="Version">{r.version_no}</td>
                  <td data-label="Status">
                    <StatusChip status={reportStatus(r)} />
                    {r.id === governingId && <span className="gov-tag">Governing</span>}
                    {r.is_stale && r.status === "approved" && <div className="small muted">Out of date</div>}
                  </td>
                  <td className="num" data-label="Flagged discrepancies (CAD)">{formatCents(sumCents([r.findings_amount, r.not_received_amount]))}</td>
                  <td className="num" data-label="of which not received">{money(r.not_received_amount)}</td>
                  <td className="num" data-label="Unverified (CAD)">{money(r.unverified_amount)}</td>
                  <td data-label="Data cut-off">{when(r.data_cutoff_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {list.hasNextPage && (
        <button className="btn" style={{ marginTop: 12 }} onClick={() => list.fetchNextPage()} disabled={list.isFetchingNextPage}>
          {list.isFetchingNextPage ? "Loading…" : "Show older versions"}
        </button>
      )}
    </>
  );
}

function FindingsTable({ rows, caption, showPaid = true, period }: { rows: Finding[]; caption: string; showPaid?: boolean; period?: { start: string; end: string } }) {
  if (!rows.length) return <p className="muted">None.</p>;
  return (
    <div className="table-wrap">
      <table className="compact stack-sm">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr>
            <th scope="col">Type</th>
            <th scope="col">Supplier</th>
            <th scope="col">Document</th>
            <th scope="col">PO</th>
            <th scope="col">Item</th>
            {showPaid && <th scope="col">Paid</th>}
            <th scope="col">Confirmed by the controller</th>
            <th scope="col" className="num">Amount (CAD)</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((f) => {
            const s = f.snapshot as Record<string, string | null>;
            return (
              <tr key={f.id}>
                <td data-label="Type">
                  {typeWord(f.type)}
                  {s.sub_reason === "not_received" ? <div className="small muted">Not received</div> : null}
                </td>
                <td data-label="Supplier">{s.vendor_name}</td>
                <td data-label="Document">
                  <Link to={`${period ? queueLink({ from: period.start, to: period.end, status: "open,pending_approval,resolved,waived" }) : "/exceptions?status=open,pending_approval,resolved,waived"}&sel=${f.exception_id}`}>{s.doc_number}</Link>
                  {s.line_no ? ` line ${s.line_no}` : ""}
                </td>
                <td data-label="PO">{s.po_number}</td>
                <td data-label="Item">{s.supplier_item_code}</td>
                {showPaid && <td data-label="Paid">{f.paid_status === "unknown" ? "Not known" : f.paid_status === "paid" ? "Already paid" : "Not yet paid"}</td>}
                <td data-label="Confirmed by the controller">
                  {s.resolution_code === "confirmed_overbilling" || s.resolution_code === "confirmed_not_received" ? (
                    "Yes"
                  ) : (
                    <span className="muted">{STATUS_WORDS[s.status ?? ""] ?? "Not yet"}</span>
                  )}
                </td>
                <td data-label="Amount (CAD)" className="num">
                  {money(f.amount)}
                  {zeroCounted({ reported_amount: f.amount, variance_amount: s.variance_amount ?? null }) && (
                    <div className="small muted">counted under another exception on this line</div>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
        <tfoot>
          <tr>
            <td colSpan={showPaid ? 7 : 6}>{plural(rows.length, "item")}</td>
            <td className="num">{formatCents(sumCents(rows.map((r) => r.amount)))}</td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

/** S-13 report: draft versus approved at a glance (DD-04), seven sections, approve, export. */
export function ReportPage() {
  const { reportId } = useParams();
  const { can } = useSession();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const q = useQuery({ queryKey: ["report", reportId], queryFn: () => get<Report>(`/api/v1/reports/backtest/${reportId}`) });
  const r = q.data;
  const pilot = usePilot();
  const users = useQuery({
    queryKey: ["users"],
    queryFn: () => get<Page<{ user_id: string; display_name: string | null; email: string }>>("/api/v1/users"),
    enabled: can("manage_users") && !!r?.approved_by,
  });
  const approver = users.data?.items.find((u) => u.user_id === r?.approved_by);
  usePageTitle("Back-test report", r ? `${monthName(r.period_start.slice(0, 7))} v${r.version_no}` : null);
  const list = useQuery({ queryKey: ["reports", "all"], queryFn: () => getAll<Report>("/api/v1/reports/backtest?limit=200") });
  const refund = useQuery({
    queryKey: ["refund", reportId],
    queryFn: () => get<Refund>(`/api/v1/reports/backtest/${reportId}/refund-evaluation`),
    enabled: r?.status === "approved",
  });
  const outcomes = useOutcomes(reportId, !!r && pilot.data?.governing?.report_id === r.id);
  const [approveOpen, setApproveOpen] = useState(false);
  const [reviewed, setReviewed] = useState(false);
  const [exporting, setExporting] = useState<string | null>(null);
  const refresh = useMutation({
    mutationFn: () => send<Report>("POST", "/api/v1/reports/backtest", { period_start: r!.period_start, period_end: r!.period_end }),
    onSuccess: (n) => {
      qc.invalidateQueries({ queryKey: ["reports"] });
      navigate(`/reports/backtest/${n.id}`);
      toast(`Draft version ${n.version_no} is ready for review.`, "success");
    },
  });
  const approve = useMutation({
    mutationFn: () => send<Report>("POST", `/api/v1/reports/backtest/${reportId}/approve`),
    onSuccess: () => {
      setApproveOpen(false);
      qc.invalidateQueries({ queryKey: ["report", reportId] });
      qc.invalidateQueries({ queryKey: ["reports"] });
      toast("Report approved. Its figures are now frozen.", "success");
    },
  });
  const [exportFailed, setExportFailed] = useState<{ format: "pdf" | "csv"; reason: string } | null>(null);
  async function exportAs(format: "pdf" | "csv") {
    setExporting(format);
    setExportFailed(null);
    try {
      await download(`/api/v1/reports/backtest/${reportId}/export?format=${format}`, `backtest.${format}`);
    } catch (err) {
      // B10 (item 9): the reason and a retry next to the export buttons, not a toast.
      setExportFailed({ format, reason: errorText(err) });
    } finally {
      setExporting(null);
    }
  }
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorState error={q.error} retry={() => q.refetch()} />;
  if (!r) return null;
  const f = r.findings ?? [];
  const S = r.totals.sections;
  const findings = f.filter((x) => x.section === "finding");
  const notReceived = f.filter((x) => x.section === "not_received");
  const unverified = f.filter((x) => x.section === "unverified");
  const waived = f.filter((x) => x.section === "waived");
  const open = f.filter((x) => x.section === "open");
  // Every exception of this version still open (or waiting for approval), whatever its section:
  // the same count the queue shows (review W2).
  const stillOpen = f.filter((x) => ["open", "pending_approval"].includes(String((x.snapshot as Record<string, unknown>).status)));
  const flaggedCount = findings.length + notReceived.length;
  const flagged = sumCents([...findings, ...notReceived].map((x) => x.amount));
  const confirmed = [...findings, ...notReceived].filter((x) => (x.snapshot as Record<string, unknown>).resolution_code === "confirmed_overbilling");
  const byTypeMap = new Map<string, Finding[]>();
  for (const x of findings) byTypeMap.set(x.type, [...(byTypeMap.get(x.type) ?? []), x]);
  // Stable order: largest amount first, then the type's name (B6 review minor).
  const total = (xs: Finding[]) => sumCents(xs.map((x) => x.amount));
  const byType = [...byTypeMap.entries()].sort((a, b) => (total(b[1]) > total(a[1]) ? 1 : total(b[1]) < total(a[1]) ? -1 : typeWord(a[0]).localeCompare(typeWord(b[0]))));
  const bySupplier = new Map<string, Finding[]>();
  for (const x of [...findings, ...notReceived]) {
    const v = String((x.snapshot as Record<string, unknown>).vendor_name ?? "Unknown");
    bySupplier.set(v, [...(bySupplier.get(v) ?? []), x]);
  }
  const newer = (list.data?.items ?? []).find((o) => o.period_start === r.period_start && o.version_no > r.version_no);
  const isGoverning = pilot.data?.governing?.report_id === r.id;
  const counts = isGoverning ? outcomes.data?.totals : undefined;
  const declaration = (r.totals.no_receiving_declaration ?? null) as { declared_by_name: string | null; declared_at: string } | null;
  const inconsistent = (r.totals.inconsistent_documents ?? []) as { invoice_id: string; doc_number: string | null; vendor_name: string | null; note: string | null }[];
  const ALL_STATUSES = "open,pending_approval,resolved,waived";
  const blocking = r.blocking ?? [];
  return (
    <div className="report">
      <PageHead
        title={`Back-test ${monthName(r.period_start.slice(0, 7))}`}
        crumbs={<Link to="/reports">Back-test reports</Link>}
        lede={`${day(r.period_start)} to ${day(r.period_end)}. Data cut-off: ${when(r.data_cutoff_at)}`}
        actions={
          <>
            <button className="btn" onClick={() => exportAs("pdf")} disabled={!!exporting}>
              <Download size={16} aria-hidden="true" />
              {exporting === "pdf" ? "Preparing your file…" : "Export PDF"}
            </button>
            <button className="btn" onClick={() => exportAs("csv")} disabled={!!exporting}>
              <Download size={16} aria-hidden="true" />
              {exporting === "csv" ? "Preparing your file…" : "Export CSV"}
            </button>
            {exportFailed && (
              <span className="download-failed" role="alert">
                <span className="error-text small">
                  {exportFailed.format.toUpperCase()} download failed: {exportFailed.reason}
                </span>
                <button className="btn small" onClick={() => exportAs(exportFailed.format)}>
                  Retry download
                </button>
              </span>
            )}
            {can("draft_report") && (r.status === "draft" || (r.status === "approved" && (r.is_stale || r.changed_since_cutoff))) && (
              <button className="btn" onClick={() => refresh.mutate()} disabled={refresh.isPending}>
                {refresh.isPending ? "Generating…" : r.status === "draft" ? "Refresh draft" : "Create a new draft version"}
              </button>
            )}
            {can("approve_report") && r.status === "draft" && (
              <button className="btn primary" onClick={() => setApproveOpen(true)}>
                <ShieldCheck size={16} aria-hidden="true" />
                Approve version {r.version_no}
              </button>
            )}
          </>
        }
      />
      {r.status === "draft" && (
        <Banner tone="draft">
          <p>
            <strong>DRAFT · version {r.version_no} · figures may change.</strong> Exports carry DRAFT on every page.
          </p>
        </Banner>
      )}
      {r.status === "approved" && (
        <Banner tone="approved">
          <p>
            <strong>
              APPROVED{approver ? ` by ${approver.display_name || approver.email}` : ""} on {when(r.approved_at)} · version {r.version_no}
              {isGoverning ? " · GOVERNING VERSION: the refund is decided on this version" : ""}
            </strong>
            {(r.is_stale || r.changed_since_cutoff) && " · results changed after its data cut-off; you can create a new draft version."}
          </p>
        </Banner>
      )}
      {r.status === "superseded" && (
        <Banner tone="info">
          <p>
            <strong>SUPERSEDED</strong>
            {newer ? (
              <>
                {" "}
                by <Link to={`/reports/backtest/${newer.id}`}>version {newer.version_no}</Link>
              </>
            ) : null}
            . Figures are frozen.
          </p>
        </Banner>
      )}
      {refresh.error && <Banner tone="error">{errorText(refresh.error)}</Banner>}
      {r.status === "draft" && blocking.length > 0 && (
        <Banner tone="warn">
          <p>
            <strong>Before this version can be approved:</strong>
          </p>
          <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
            {blocking.map((b) => (
              <li key={b}>{b}</li>
            ))}
          </ul>
          <p className="small" style={{ marginTop: 6 }}>
            <Link to="/intake">Invoice intake</Link> · <Link to="/approvals">Approvals</Link> · <Link to="/exceptions">Exceptions</Link>. Then choose Refresh draft.
          </p>
        </Banner>
      )}

      <div className="cards">
        <div>
          <span className="muted small"><AlertTriangle size={14} aria-hidden="true" style={{ verticalAlign: "-2px", marginRight: 6 }} />Flagged discrepancies</span>
          <span className="big">{cadCents(flagged)}</span>
          <span className="small">
            {plural(flaggedCount, "item")}: findings {cad(r.findings_amount)} + not received {cad(r.not_received_amount)}
          </span>
        </div>
        <div>
          <span className="muted small"><PackageX size={14} aria-hidden="true" style={{ verticalAlign: "-2px", marginRight: 6 }} />of which not received</span>
          <span className="big">{cad(r.not_received_amount)}</span>
          <span className="small">{plural(S.not_received?.count ?? 0, "line")}</span>
        </div>
        <div>
          <span className="muted small"><HelpCircle size={14} aria-hidden="true" style={{ verticalAlign: "-2px", marginRight: 6 }} />Unverified, not checkable</span>
          <span className="big">{cad(r.unverified_amount)}</span>
          <span className="small">{plural(S.unverified?.count ?? 0, "item")}</span>
        </div>
        <div>
          <span className="muted small"><PackageCheck size={14} aria-hidden="true" style={{ verticalAlign: "-2px", marginRight: 6 }} />Receipt coverage</span>
          <span className="big">{pct(r.receipt_coverage_pct)}</span>
          <span className="small">of invoiced PO lines have a counting receipt</span>
        </div>
      </div>
      <dl className="three-counts" aria-label="Three separate counts">
        <div>
          <dt>Flagged by the rules</dt>
          <dd>
            <span className="num">{cadCents(flagged)}</span> <span className="muted small">{plural(flaggedCount, "item")}</span>
          </dd>
        </div>
        <div>
          <dt>Confirmed by the controller</dt>
          <dd>
            {counts ? (
              <>
                <span className="num">{cad(counts.controller_confirmed.amount)}</span>{" "}
                <span className="muted small">{plural(counts.controller_confirmed.count, "item")} recorded</span>
              </>
            ) : (
              <>
                <span className="num">{cadCents(sumCents(confirmed.map((c) => c.amount)))}</span>{" "}
                <span className="muted small">{plural(confirmed.length, "item")} resolved as confirmed</span>
              </>
            )}
          </dd>
        </div>
        <div>
          <dt>Credit recovered</dt>
          {counts ? (
            <dd data-testid="credit-recovered">
              <span className="num">{cad(counts.credit_recovered.amount)}</span>{" "}
              <span className="muted small">{plural(counts.credit_recovered.count, "item")} recorded</span>
            </dd>
          ) : (
            <dd className="muted">Recorded on the governing version</dd>
          )}
        </div>
      </dl>
      <p className="small muted three-note">
        Totals open the queue with this report&apos;s dates. The queue is live; this version is frozen at its data cut-off, so later resolutions show there, not here.
      </p>

      <section>
        <h2>1. Documents and lines</h2>
        <dl className="facts panel panel-body">
          <dt>Documents processed</dt>
          <dd>{r.totals.documents}</dd>
          <dt>Lines evaluated</dt>
          <dd>{r.totals.lines_evaluated}</dd>
          <dt>Lines matched</dt>
          <dd>{r.totals.lines_matched}</dd>
          {r.totals.stale_lines > 0 && (
            <>
              <dt>Lines with out-of-date results</dt>
              <dd>{r.totals.stale_lines}</dd>
            </>
          )}
        </dl>
      </section>
      <section>
        <h2>2. Flagged discrepancies</h2>
        <h3 style={{ margin: "8px 0" }}>By type</h3>
        <div className="table-wrap" style={{ marginBottom: 12 }}>
          <table className="compact">
            <thead>
              <tr>
                <th scope="col">Type</th>
                <th scope="col" className="num">Items</th>
                <th scope="col" className="num">Amount (CAD)</th>
              </tr>
            </thead>
            <tbody>
              {byType.map(([t, xs]) => (
                <tr key={t}>
                  <td>
                    <Link to={queueLink({ from: r.period_start, to: r.period_end, type: t, status: ALL_STATUSES })}>{typeWord(t)}</Link>
                  </td>
                  <td className="num">{xs.length}</td>
                  <td className="num">{formatCents(sumCents(xs.map((x) => x.amount)))}</td>
                </tr>
              ))}
              <tr>
                <td>Not received</td>
                <td className="num">{S.not_received?.count ?? 0}</td>
                <td className="num">{money(S.not_received?.amount)}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <h3 style={{ margin: "8px 0" }}>By supplier</h3>
        <div className="table-wrap" style={{ marginBottom: 12 }}>
          <table className="compact">
            <thead>
              <tr>
                <th scope="col">Supplier</th>
                <th scope="col" className="num">Items</th>
                <th scope="col" className="num">Amount (CAD)</th>
              </tr>
            </thead>
            <tbody>
              {[...bySupplier.entries()].sort((a, b) => (total(b[1]) > total(a[1]) ? 1 : total(b[1]) < total(a[1]) ? -1 : a[0].localeCompare(b[0]))).map(([v, xs]) => (
                <tr key={v}>
                  <td>{v}</td>
                  <td className="num">{xs.length}</td>
                  <td className="num">{formatCents(sumCents(xs.map((x) => x.amount)))}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="small muted">
          Paid split:{" "}
          {Object.entries(r.totals.paid_split)
            .map(([k, v]) => `${k === "unknown" ? "payment not known" : k === "paid" ? "already paid" : "not yet paid"} ${cad(v)}`)
            .join(", ") || "none"}
          .
        </p>
        <FindingsTable rows={[...findings, ...notReceived].sort(byAmount)} caption="Flagged discrepancies" period={{ start: r.period_start, end: r.period_end }} />
      </section>
      <section>
        <h2>3. Receipt coverage and what could not be checked</h2>
        <dl className="facts panel panel-body">
          <dt>Invoiced PO lines with a counting receipt</dt>
          <dd>{pct(r.receipt_coverage_pct)}</dd>
          <dt>of which from a signed delivery document (B)</dt>
          <dd>{pct(r.coverage_class_b_pct)}</dd>
          <dt>Invoiced PO lines inside a complete warehouse log (A)</dt>
          <dd>
            {pct(r.coverage_class_a_pct)}
            <div className="small muted">Includes lines the log shows as not received, so it can be higher than receipt coverage.</div>
          </dd>
          <dt>Lines with supplier slips only</dt>
          <dd>{r.class_c_only_lines}</dd>
          <dt>Unverified</dt>
          <dd>
            {plural(S.unverified?.count ?? 0, "item")}, {cad(r.unverified_amount)}
          </dd>
          <dt>Purchase-order history read from</dt>
          <dd>{day(r.history_read_from) || "Not recorded"}</dd>
        </dl>
        {declaration && (
          <Banner tone="warn">
            <p>
              <strong>No warehouse receiving records</strong>, declared by {declaration.declared_by_name ?? "the controller"} on {day(declaration.declared_at)}.
              Every invoiced line is receipt absent and unverified; price, ordered-quantity and duplicate checks ran. This report is a two-way match only.
            </p>
          </Banner>
        )}
        <p className="small" style={{ marginTop: 8 }}>
          A missing receiving record is never treated as received. Where the receiving log covers the order and shows nothing, the line is "not received";
          otherwise it is unverified and is not counted as a finding.
        </p>
        <FindingsTable rows={unverified} caption="Unverified items" showPaid={false} period={{ start: r.period_start, end: r.period_end }} />
      </section>
      <section>
        <h2>4. Waived items</h2>
        <FindingsTable rows={waived} caption="Waived items" showPaid={false} period={{ start: r.period_start, end: r.period_end }} />
      </section>
      <section>
        <h2>5. Undecided items</h2>
        <p className="small muted" style={{ margin: "0 0 8px" }}>
          Possible duplicates, possible credits and items waiting for an approval: not counted until someone decides them.{" "}
          {stillOpen.length > 0 &&
            `${plural(stillOpen.length, "item")} still open in the exception queue ${stillOpen.length === 1 ? "is" : "are"} counted in the sections above with ${stillOpen.length === 1 ? "its" : "their"} queue status.`}
        </p>
        <FindingsTable rows={[...open].sort(byAmount)} caption="Undecided items" showPaid={false} period={{ start: r.period_start, end: r.period_end }} />
      </section>
      <section>
        <h2>6. Documents with self-inconsistent totals and duplicates</h2>
        {!("inconsistent_documents" in r.totals) ? null : inconsistent.length > 0 ? (
          <ul className="plain-list panel panel-body" aria-label="Confirmed although they do not add up">
            {inconsistent.map((d) => (
              <li key={d.invoice_id}>
                <Link to={`/invoices/${d.invoice_id}`}>{d.doc_number ?? "No number"}</Link>
                {d.vendor_name ? ` (${d.vendor_name})` : ""}: confirmed although the document does not add up. Note: <q>{d.note ?? "none"}</q>
              </li>
            ))}
          </ul>
        ) : (
          <p className="small muted">No document was confirmed with figures that do not add up.</p>
        )}
        <FindingsTable rows={f.filter((x) => x.type === "duplicate" || x.type === "possible_duplicate" || (x.snapshot as Record<string, unknown>).label === "inconsistent_total")} caption="Inconsistent or duplicate documents" showPaid={false} period={{ start: r.period_start, end: r.period_end }} />
      </section>
      <section>
        <h2>7. Pilot terms and refund calculation</h2>
        {r.status !== "approved" && (
          <p>
            The refund is decided only on the approved, governing version. This draft shows qualifying discrepancies of {cad(r.qualifying_amount)}; the figure can still
            change.
          </p>
        )}
        {r.status === "approved" && refund.data && (
          <p className="workings" style={{ display: "block" }}>
            <span className="sentence">
              Qualifying discrepancies in this version: {cad(refund.data.qualifying_total)}. Threshold {cad(refund.data.threshold)}.{" "}
              {refund.data.refund_due ? "Refund applies." : "No refund."} Unverified because no receiving evidence: {cad(refund.data.unverified_total)}.
            </span>
          </p>
        )}
        <PilotSection r={r} />
      </section>
      <OutcomesSection report={r} flagged={[...findings, ...notReceived]} />

      <Dialog
        open={approveOpen}
        title={`Approve version ${r.version_no}`}
        onClose={() => setApproveOpen(false)}
        footer={
          <>
            <button className="btn" data-safe onClick={() => setApproveOpen(false)}>
              Cancel
            </button>
            <button className="btn primary" disabled={!reviewed || blocking.length > 0 || approve.isPending} onClick={() => approve.mutate()}>
              Approve version {r.version_no}
            </button>
          </>
        }
      >
        {blocking.length > 0 && (
          <div className="banner warn">
            <div>
              <p>
                <strong>This version cannot be approved yet:</strong>
              </p>
              <ul style={{ margin: 0, paddingLeft: 18 }}>
                {blocking.map((b) => (
                  <li key={b}>{b}</li>
                ))}
              </ul>
            </div>
          </div>
        )}
        <p>
          Approve version {r.version_no} of the {monthName(r.period_start.slice(0, 7))} back-test. Flagged discrepancies {cadCents(flagged)} (findings{" "}
          {cad(r.findings_amount)} + not received {cad(r.not_received_amount)}). Unverified because no receiving evidence: {cad(r.unverified_amount)} on{" "}
          {plural(S.unverified?.count ?? 0, "item")}. {plural(stillOpen.length, "item")} still open in the exception queue{" "}
          {stillOpen.length === 1 ? "is" : "are"} reported in those sections with {stillOpen.length === 1 ? "its" : "their"} queue status; undecided items (section 5):{" "}
          {open.length}. Approved figures cannot be changed; later corrections create a new version.
        </p>
        <label className="choice">
          <input type="checkbox" checked={reviewed} onChange={(e) => setReviewed(e.target.checked)} />
          <span>I have reviewed the waived items ({waived.length}).</span>
        </label>
        {approve.error && <p className="error-text">{errorText(approve.error)}</p>}
      </Dialog>
    </div>
  );
}
