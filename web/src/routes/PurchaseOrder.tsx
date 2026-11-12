import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { errorText, get, send } from "../api/client";
import type { InvoiceDetail, InvoiceSummary, Page, PurchaseOrder } from "../api/types";
import { useSession } from "../app/session";
import { Banner, ErrorState, Loading, PageHead, toast, usePageTitle } from "../components/ui";
import { money, price, qty } from "../lib/decimal";
import { day, plural, when } from "../lib/format";

/** S-10: everything that happened on one purchase order. */
export function PurchaseOrderPage() {
  const { poId } = useParams();
  const { can } = useSession();
  const q = useQuery({
    queryKey: ["purchase-order", poId],
    queryFn: () => get<PurchaseOrder>(`/api/v1/purchase-orders/${poId}`),
    // While the affected lines are being matched again, the banner updates by itself.
    refetchInterval: (query) => (query.state.data?.changed_in_quickbooks && !query.state.data.changed_in_quickbooks.rematched_at ? 3000 : false),
  });
  usePageTitle("Purchase order", q.data ? `PO ${q.data.po_number}` : null);
  const invoices = useQuery({
    queryKey: ["invoices", "po", q.data?.vendor_id],
    queryFn: () => get<Page<InvoiceSummary>>(`/api/v1/invoices?limit=200&vendor_id=${q.data?.vendor_id}`),
    enabled: !!q.data,
  });
  const onPo = (invoices.data?.items ?? []).filter((i) => i.po_number === q.data?.po_number);
  // Line totals come from the same match results S-09 shows (one detail read per document).
  const details = useQuery({
    queryKey: ["po-details", poId, onPo.map((i) => i.id).join()],
    queryFn: () => Promise.all(onPo.map((i) => get<InvoiceDetail>(`/api/v1/invoices/${i.id}`))),
    enabled: onPo.length > 0,
  });
  const reread = useMutation({
    mutationFn: () => send("POST", "/api/v1/qbo/sync-runs", { mode: "po_references", po_references: [q.data?.po_number] }),
    onSuccess: () => toast("Reading this purchase order from QuickBooks again."),
  });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorState error={q.error} retry={() => q.refetch()} />;
  const po = q.data!;
  const openByLine = new Map<string, number>();
  const timeline: { date: string; text: string; link?: string }[] = [];
  for (const d of details.data ?? []) {
    timeline.push({ date: d.doc_date ?? "", text: `${d.doc_type === "credit_note" ? "Credit note" : "Invoice"} ${d.doc_number}`, link: `/invoices/${d.id}` });
    for (const l of d.lines) {
      const pl = l.purchase_order?.line_id;
      if (!pl) continue;
      const open = d.exceptions.filter((x) => x.invoice_line_id === l.id && (x.status === "open" || x.status === "pending_approval")).length;
      openByLine.set(pl, (openByLine.get(pl) ?? 0) + open);
    }
  }
  const sumQty = (lineId: string, kind: "invoice" | "credit_note") => {
    const vals: string[] = [];
    for (const d of details.data ?? []) {
      if (d.doc_type !== kind) continue;
      for (const l of d.lines) if (l.purchase_order?.line_id === lineId && l.qty) vals.push(l.qty);
    }
    return addQty(vals);
  };
  for (const ln of po.lines ?? []) {
    // receipts are listed per invoice line; take them from any detail that has this PO line
    for (const d of details.data ?? [])
      for (const l of d.lines)
        if (l.purchase_order?.line_id === ln.id)
          for (const r of l.receipts ?? []) if (!timeline.some((t) => t.text.includes(`row ${r.source_row}`) && t.date === r.received_date))
            timeline.push({ date: r.received_date, text: `Receipt ${qty(r.qty)} ${ln.uom ?? ""}, ${r.source_file} row ${r.source_row}${r.counts ? "" : " (not counted)"}`, link: `/receiving/imports/${r.receiving_import_id}` });
  }
  timeline.sort((a, b) => a.date.localeCompare(b.date));
  return (
    <>
      <PageHead
        title={`PO ${po.po_number}`}
        crumbs={<Link to="/invoices">Invoices</Link>}
        lede={`${po.vendor_name ?? ""} · ${day(po.txn_date)} · ${po.qbo_status ?? "status not read"} · total ${money(po.total)}`}
        actions={
          can("start_sync") && (
            <button className="btn" onClick={() => reread.mutate()} disabled={reread.isPending}>
              Read again from QuickBooks
            </button>
          )
        }
      />
      {reread.error && <p className="error-text">{errorText(reread.error)}</p>}
      {po.changed_in_quickbooks && <ChangedInQuickBooks change={po.changed_in_quickbooks} />}
      <div className="table-wrap">
        <table className="stack-sm">
          <thead>
            <tr>
              <th scope="col">Line</th>
              <th scope="col">Item</th>
              <th scope="col" className="num">Ordered</th>
              <th scope="col" className="num">Received independently</th>
              <th scope="col" className="num">Invoiced</th>
              <th scope="col" className="num">Credited</th>
              <th scope="col" className="num">Net invoiced</th>
              <th scope="col" className="num">Price</th>
              <th scope="col" className="num">Open exceptions</th>
            </tr>
          </thead>
          <tbody>
            {(po.lines ?? []).map((l) => {
              const inv = sumQty(l.id, "invoice");
              const cr = sumQty(l.id, "credit_note");
              return (
                <tr key={l.id}>
                  <td data-label="Line" className="num">{l.line_no}</td>
                  <td data-label="Item">
                    {l.description ?? l.charge_kind ?? ""}
                    {l.removed_at && <div className="muted small">No longer returned by QuickBooks (last copy shown)</div>}
                  </td>
                  <td data-label="Ordered" className="num">
                    {qty(l.qty_ordered)} {l.uom}
                  </td>
                  <td data-label="Received independently" className="num">
                    {qty(l.qty_received_counting)} <span className="muted small">({plural(l.counting_receipt_lines, "line")})</span>
                  </td>
                  <td data-label="Invoiced" className="num">{inv}</td>
                  <td data-label="Credited" className="num">{cr}</td>
                  <td data-label="Net invoiced" className="num">{subQty(inv, cr)}</td>
                  <td data-label="Price" className="num">{price(l.unit_price)}</td>
                  <td data-label="Open exceptions" className="num">{openByLine.get(l.id) ?? 0}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <section style={{ marginTop: 16 }} aria-labelledby="tl-h">
        <h2 id="tl-h" style={{ marginBottom: 8 }}>
          Timeline
        </h2>
        {details.isLoading && <Loading />}
        <ol className="panel panel-body" style={{ margin: 0, paddingLeft: 32 }}>
          {timeline.map((t, i) => (
            <li key={i}>
              {day(t.date)}: {t.link ? <Link to={t.link}>{t.text}</Link> : t.text}
            </li>
          ))}
          {timeline.length === 0 && <li className="muted">No invoices or receipts on this purchase order yet.</li>}
        </ol>
      </section>
    </>
  );
}

/** Exact decimal sums of quantity strings, for display. */
function addQty(values: string[]): string {
  const scale = 4;
  const toInt = (v: string) => {
    const [i, f = ""] = v.split(".");
    return BigInt(i + f.padEnd(scale, "0").slice(0, scale));
  };
  const total = values.reduce((a, v) => a + toInt(v), 0n);
  return fmt(total, scale);
}

function subQty(a: string, b: string): string {
  const scale = 4;
  const toInt = (v: string) => {
    const [i, f = ""] = (v || "0").split(".");
    return BigInt(i + f.padEnd(scale, "0").slice(0, scale));
  };
  return fmt(toInt(a) - toInt(b), scale);
}

function fmt(n: bigint, scale: number): string {
  const neg = n < 0n;
  const s = (neg ? -n : n).toString().padStart(scale + 1, "0");
  const out = `${s.slice(0, -scale)}.${s.slice(-scale)}`.replace(/\.?0+$/, "");
  return (neg ? "-" : "") + out;
}

const FIELD_WORDS: Record<string, string> = { qty_ordered: "Ordered", unit_price: "Unit price", uom: "Unit", item_id: "Item", description: "Description", line_no: "Line number" };

/** S-10 (B9): a QuickBooks read changed or removed lines that had already been matched. */
function ChangedInQuickBooks({ change }: { change: NonNullable<PurchaseOrder["changed_in_quickbooks"]> }) {
  const show = (k: string, v: unknown) => (v === null || v === undefined || v === "" ? "none" : k === "unit_price" ? price(String(v)) : k === "qty_ordered" ? qty(String(v)) : k === "item_id" ? "another item" : String(v));
  return (
    <Banner tone="warn" role="status">
      <div className="po-changes" data-testid="changed-in-quickbooks">
        <p>
          <strong>Changed in QuickBooks</strong> since these lines were matched: read {when(change.detected_at)}.{" "}
          {change.rematched_at ? `The affected lines were matched again ${when(change.rematched_at)}.` : "The affected lines are being matched again…"}
        </p>
        <ul className="plain-list">
          {change.changes.map((c) => (
            <li key={c.po_line_id}>
              Line {c.line_no ?? "?"}:{" "}
              {c.change === "removed"
                ? `deleted in QuickBooks (was ${show("qty_ordered", c.before.qty_ordered)} ${c.before.uom ?? ""} at ${show("unit_price", c.before.unit_price)}). Shown as "No longer returned by QuickBooks".`
                : Object.keys(c.before)
                    .filter((k) => String(c.before[k] ?? "") !== String(c.after?.[k] ?? ""))
                    .map((k) => `${FIELD_WORDS[k] ?? k} ${show(k, c.before[k])} → ${show(k, c.after?.[k])}`)
                    .join("; ")}
            </li>
          ))}
        </ul>
      </div>
    </Banner>
  );
}
