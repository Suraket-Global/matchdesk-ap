import { Link, useSearchParams } from "react-router-dom";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { get } from "../api/client";
import type { InvoiceSummary, Page, Vendor } from "../api/types";
import { Empty, ErrorState, Loading, PageHead, StatusChip, usePageTitle } from "../components/ui";
import { money } from "../lib/decimal";
import { day, plural } from "../lib/format";

const STATES: [string, string][] = [
  ["", "All states"],
  ["succeeded", "Ready"],
  ["needs_review", "Needs review"],
  ["queued", "Queued"],
  ["running", "Processing"],
  ["failed", "Failed"],
];

/** S-09 list: every document with its state; filters in the URL. */
export function InvoicesPage() {
  usePageTitle("Invoices");
  const [params, setParams] = useSearchParams();
  const state = params.get("state") ?? "";
  const vendor = params.get("vendor") ?? "";
  const qs = new URLSearchParams({ limit: "200" });
  if (state) qs.set("document_state", state);
  if (vendor) qs.set("vendor_id", vendor);
  const list = useInfiniteQuery({
    queryKey: ["invoices", "list", state, vendor],
    queryFn: ({ pageParam }) => get<Page<InvoiceSummary>>(`/api/v1/invoices?${qs}${pageParam ? `&cursor=${pageParam}` : ""}`),
    initialPageParam: "",
    getNextPageParam: (l) => l.next_cursor ?? undefined,
  });
  const vendors = useQuery({ queryKey: ["vendors"], queryFn: () => get<Page<Vendor>>("/api/v1/vendors") });
  const set = (k: string, v: string) => {
    const p = new URLSearchParams(params);
    if (v) p.set(k, v);
    else p.delete(k);
    setParams(p);
  };
  const rows = (list.data?.pages ?? [])
    .flatMap((p) => p.items)
    .sort((a, b) => (a.doc_date ?? "").localeCompare(b.doc_date ?? "") || (a.doc_number ?? "").localeCompare(b.doc_number ?? ""));
  return (
    <>
      <PageHead title="Invoices" lede="Invoices and credit notes in document-date order." />
      <div className="inline-form panel panel-body" style={{ marginBottom: 12 }}>
        <div className="field">
          <label htmlFor="i-state">State</label>
          <select id="i-state" value={state} onChange={(e) => set("state", e.target.value)}>
            {STATES.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="i-vendor">Supplier</label>
          <select id="i-vendor" value={vendor} onChange={(e) => set("vendor", e.target.value)}>
            <option value="">All suppliers</option>
            {(vendors.data?.items ?? []).map((v) => (
              <option key={v.id} value={v.id}>
                {v.name}
              </option>
            ))}
          </select>
        </div>
      </div>
      {list.isLoading && <Loading />}
      {list.error && <ErrorState error={list.error} retry={() => list.refetch()} />}
      {list.data && rows.length === 0 && (
        <div className="panel">
          <Empty title="No documents">
            <p>
              <Link to="/intake">Upload invoices</Link>
            </p>
          </Empty>
        </div>
      )}
      {rows.length > 0 && (
        <div className="table-wrap">
          <table className="stack-sm">
            <thead>
              <tr>
                <th scope="col">Document</th>
                <th scope="col">Date</th>
                <th scope="col">Supplier</th>
                <th scope="col">PO</th>
                <th scope="col" className="num">
                  Total (CAD)
                </th>
                <th scope="col">State</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((i) => (
                <tr key={i.id}>
                  <td data-label="Document">
                    <Link to={i.displayed_state === "needs review" ? `/invoices/${i.id}/review` : `/invoices/${i.id}`}>
                      {i.doc_type === "credit_note" ? "Credit note " : ""}
                      {i.doc_number ?? "No number read"}
                    </Link>
                  </td>
                  <td data-label="Date">{day(i.doc_date)}</td>
                  <td data-label="Supplier">{i.vendor_name ?? <span className="muted">Not identified</span>}</td>
                  <td data-label="PO">{i.po_number}</td>
                  <td data-label="Total (CAD)" className="num">{money(i.total)}</td>
                  <td data-label="State">
                    <StatusChip status={i.displayed_state ?? "queued"} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {rows.length > 0 && <p className="muted small" style={{ marginTop: 8 }}>{plural(rows.length, "document")}</p>}
      {list.hasNextPage && (
        <button className="btn" onClick={() => list.fetchNextPage()}>
          Load more
        </button>
      )}
    </>
  );
}
