import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { errorText, get, send } from "../api/client";
import type { Alias, ExceptionPage, Item, Page, Vendor } from "../api/types";
import { useSession } from "../app/session";
import { Banner, Dialog, Empty, ErrorState, Field, Loading, NarrowNote, PageHead, StatusChip, toast, usePageTitle } from "../components/ui";
import { divide, isDecimal, multiply, qty } from "../lib/decimal";
import { plural, when } from "../lib/format";

interface Suggestion {
  item_id: string;
  basis: string;
  score: string;
  item_name?: string;
  item_sku?: string;
}

const BASIS: Record<string, string> = {
  earlier_alias: "same code",
  sku: "same code",
  description_similarity: "similar description",
};

/** The conversion entered with a live worked example on the user's own numbers (DD-12). */
export function WorkedExample(props: { factor: string; supUom: string; itemUom: string; exQty: string; exPrice: string }) {
  const { factor, supUom, itemUom, exQty, exPrice } = props;
  if (!isDecimal(factor) || !isDecimal(exQty) || !isDecimal(exPrice) || /^0+(\.0+)?$/.test(factor)) return null;
  const units = qty(multiply(exQty, factor, 4));
  const per = divide(exPrice, factor, 2);
  return (
    <p className="workings" style={{ padding: "8px 12px" }} aria-live="polite">
      <span className="sentence" style={{ fontSize: 14 }}>
        {exQty} {supUom || "supplier units"} × {qty(factor)} = {units} {itemUom || "our units"}; {exPrice} per {supUom || "supplier unit"} = {per} per{" "}
        {itemUom || "our unit"}
      </span>
    </p>
  );
}

/** S-11: record once that this supplier's code is our item, and in which unit. */
export function AliasesPage() {
  usePageTitle("Alias and unit map");
  const { can } = useSession();
  const qc = useQueryClient();
  const [params] = useSearchParams();
  const list = useQuery({ queryKey: ["aliases"], queryFn: () => get<Page<Alias>>("/api/v1/aliases") });
  const vendors = useQuery({ queryKey: ["vendors"], queryFn: () => get<Page<Vendor>>("/api/v1/vendors") });
  const unconfirmed = useQuery({
    queryKey: ["exceptions", "alias_unconfirmed"],
    queryFn: () => get<ExceptionPage>("/api/v1/exceptions?limit=200&status=open&type=alias_unconfirmed,uom_unresolved,po_line_not_found"),
  });
  const [vendorId, setVendorId] = useState(params.get("vendor") ?? "");
  const [code, setCode] = useState(params.get("code") ?? "");
  const [description, setDescription] = useState(params.get("description") ?? "");
  const [itemQuery, setItemQuery] = useState("");
  const [itemId, setItemId] = useState("");
  const [factor, setFactor] = useState("1");
  const [supUom, setSupUom] = useState("");
  const [itemUom, setItemUom] = useState("");
  const [exQty, setExQty] = useState("5");
  const [exPrice, setExPrice] = useState("50.40");
  const [retire, setRetire] = useState<Alias | null>(null);
  const [reason, setReason] = useState("");
  const [filter, setFilter] = useState("all");
  const [formErr, setFormErr] = useState<string | null>(null);
  const items = useQuery({
    queryKey: ["items", itemQuery],
    queryFn: () => get<Page<Item>>(`/api/v1/items?limit=20${itemQuery ? `&q=${encodeURIComponent(itemQuery)}` : ""}`),
  });
  const sugg = useQuery({
    queryKey: ["alias-suggestions", vendorId, code, description],
    queryFn: () =>
      get<Page<Suggestion>>(
        `/api/v1/aliases/suggestions?vendor_id=${vendorId}&code=${encodeURIComponent(code)}${description ? `&description=${encodeURIComponent(description)}` : ""}`,
      ),
    enabled: !!vendorId && !!code.trim() && can("edit_alias"),
  });
  useEffect(() => {
    setVendorId(params.get("vendor") ?? "");
    setCode(params.get("code") ?? "");
    setDescription(params.get("description") ?? "");
  }, [params]);
  const create = useMutation({
    mutationFn: () =>
      send<Alias & { approval_id: string | null }>("POST", "/api/v1/aliases", {
        vendor_id: vendorId,
        supplier_item_code: code.trim(),
        item_id: itemId,
        conversion_factor: factor.trim(),
        supplier_uom: supUom.trim() || null,
        item_uom: itemUom.trim() || null,
        supplier_description: description.trim() || null,
      }),
    onSuccess: (a) => {
      qc.invalidateQueries({ queryKey: ["aliases"] });
      qc.invalidateQueries({ queryKey: ["exceptions"] });
      qc.invalidateQueries({ queryKey: ["approvals"] });
      toast(
        a.status === "pending_approval"
          ? "Alias saved. Lines using this alias stay in exceptions until your controller approves the conversion."
          : "Alias confirmed. Lines using it are being re-matched; your controller sees it for review.",
      );
      setCode("");
      setDescription("");
      setItemId("");
      setFactor("1");
    },
    onError: (e) => setFormErr(errorText(e)),
  });
  const retireIt = useMutation({
    mutationFn: (a: Alias) => send("POST", `/api/v1/aliases/${a.id}/deactivate`, { reason }, { ifMatch: a.version }),
    onSuccess: () => {
      setRetire(null);
      setReason("");
      qc.invalidateQueries({ queryKey: ["aliases"] });
      qc.invalidateQueries({ queryKey: ["exceptions"] });
      toast("Alias retired. Lines that used it are being re-matched.");
    },
  });
  const rows = useMemo(() => (list.data?.items ?? []).filter((a) => filter === "all" || a.status === filter), [list.data, filter]);
  const unconfirmedCodes = useMemo(() => {
    const seen = new Map<string, { vendor_id: string; vendor_name: string; code: string; description: string; n: number }>();
    for (const e of unconfirmed.data?.items ?? []) {
      if (!e.supplier_item_code || !e.vendor_id) continue;
      const k = `${e.vendor_id}|${e.supplier_item_code}`;
      const cur = seen.get(k) ?? { vendor_id: e.vendor_id, vendor_name: e.vendor_name ?? "", code: e.supplier_item_code, description: e.description ?? "", n: 0 };
      cur.n += 1;
      seen.set(k, cur);
    }
    return [...seen.values()];
  }, [unconfirmed.data]);
  function submit() {
    setFormErr(null);
    if (!vendorId || !code.trim() || !itemId) return setFormErr("Choose the supplier, the supplier's code and our item.");
    if (!isDecimal(factor) || /^0+(\.0+)?$/.test(factor.trim())) return setFormErr("The conversion must be a positive number, for example 1 or 12.");
    create.mutate();
  }
  const chosenItem = (items.data?.items ?? []).find((i) => i.id === itemId);
  return (
    <>
      <PageHead title="Alias and unit map" lede="A supplier's item code mapped once to our item and unit. Conversions other than 1 need the controller." />
      <NarrowNote />
      {unconfirmedCodes.length > 0 && (
        <Banner tone="draft">
          <p>
            <strong>Unconfirmed codes seen on invoices:</strong>{" "}
            {unconfirmedCodes.map((c, i) => (
              <span key={c.code + c.vendor_id}>
                {i > 0 && ", "}
                <button
                  className="btn small"
                  onClick={() => {
                    setVendorId(c.vendor_id);
                    setCode(c.code);
                    setDescription(c.description);
                  }}
                >
                  {c.code} ({c.vendor_name}, {plural(c.n, "line")})
                </button>
              </span>
            ))}
          </p>
        </Banner>
      )}
      {can("edit_alias") && (
        <section className="panel wide-only" aria-labelledby="new-h" style={{ marginBottom: 16 }}>
          <div className="panel-head">
            <h2 id="new-h">Confirm an alias</h2>
          </div>
          <div className="panel-body grid-2">
            <div>
              <Field label="Supplier">
                {(f) => (
                  <select id={f.id} value={vendorId} onChange={(e) => setVendorId(e.target.value)}>
                    <option value="">Choose the supplier</option>
                    {(vendors.data?.items ?? []).map((v) => (
                      <option key={v.id} value={v.id}>
                        {v.name}
                      </option>
                    ))}
                  </select>
                )}
              </Field>
              <Field label="Supplier item code">{(f) => <input id={f.id} type="text" value={code} onChange={(e) => setCode(e.target.value)} />}</Field>
              <Field label="Supplier description">{(f) => <input id={f.id} type="text" value={description} onChange={(e) => setDescription(e.target.value)} />}</Field>
              <Field label="Find our item" hint={chosenItem ? `Chosen: ${chosenItem.sku ?? ""} ${chosenItem.name}` : "Search by SKU or name, then choose."}>
                {(f) => <input id={f.id} type="search" value={itemQuery} onChange={(e) => setItemQuery(e.target.value)} aria-describedby={f.describedBy} />}
              </Field>
              <Field label="Our item">
                {(f) => (
                  <select id={f.id} value={itemId} onChange={(e) => setItemId(e.target.value)}>
                    <option value="">Choose our item</option>
                    {(items.data?.items ?? []).map((i) => (
                      <option key={i.id} value={i.id}>
                        {i.sku ? `${i.sku} · ` : ""}
                        {i.name}
                      </option>
                    ))}
                  </select>
                )}
              </Field>
            </div>
            <div>
              {(sugg.data?.items ?? []).length > 0 && (
                <div className="field">
                  <span className="label">Suggestions (nothing is saved until you confirm)</span>
                  {sugg.data!.items.slice(0, 5).map((s) => (
                    <div key={s.item_id} className="panel" style={{ padding: "8px 12px", display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
                      <span>
                        {s.item_sku ? `${s.item_sku} · ` : ""}
                        {s.item_name} <span className="muted small">({BASIS[s.basis] ?? s.basis})</span>
                      </span>
                      <button className="btn small" onClick={() => setItemId(s.item_id)}>
                        Use this
                      </button>
                    </div>
                  ))}
                </div>
              )}
              <div className="inline-form">
                <Field label="Supplier unit">{(f) => <input id={f.id} type="text" size={6} value={supUom} onChange={(e) => setSupUom(e.target.value)} />}</Field>
                <Field label="Our unit">{(f) => <input id={f.id} type="text" size={6} value={itemUom} onChange={(e) => setItemUom(e.target.value)} />}</Field>
                <Field label="Conversion (our units per supplier unit)">
                  {(f) => <input id={f.id} inputMode="decimal" size={8} value={factor} onChange={(e) => setFactor(e.target.value)} aria-invalid={!isDecimal(factor)} />}
                </Field>
              </div>
              <div className="inline-form">
                <Field label="Example quantity">{(f) => <input id={f.id} inputMode="decimal" size={6} value={exQty} onChange={(e) => setExQty(e.target.value)} />}</Field>
                <Field label="Example price per supplier unit">{(f) => <input id={f.id} inputMode="decimal" size={8} value={exPrice} onChange={(e) => setExPrice(e.target.value)} />}</Field>
              </div>
              <WorkedExample factor={factor} supUom={supUom} itemUom={itemUom} exQty={exQty} exPrice={exPrice} />
              {isDecimal(factor) && factor.trim() !== "1" && !/^1\.0*$/.test(factor.trim()) && (
                <p className="muted">Lines using this alias stay in exceptions until your controller approves the conversion.</p>
              )}
              {formErr && (
                <p className="error-text" role="alert">
                  {formErr}
                </p>
              )}
              <button className="btn primary" onClick={submit} disabled={create.isPending}>
                Confirm alias
              </button>
            </div>
          </div>
        </section>
      )}
      <div className="inline-form" style={{ marginBottom: 8 }}>
        <div className="field">
          <label htmlFor="a-filter">Show</label>
          <select id="a-filter" value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="all">All aliases</option>
            <option value="active">Active</option>
            <option value="pending_approval">Pending approval</option>
            <option value="retired">Retired</option>
          </select>
        </div>
      </div>
      {list.isLoading && <Loading />}
      {list.error && <ErrorState error={list.error} />}
      {list.data && rows.length === 0 && (
        <div className="panel">
          <Empty title="No aliases yet">
            <p>Codes seen on invoices that have no alias appear above.</p>
          </Empty>
        </div>
      )}
      {rows.length > 0 && (
        <div className="table-wrap">
          <table className="stack-sm">
            <thead>
              <tr>
                <th scope="col">Supplier</th>
                <th scope="col">Supplier code</th>
                <th scope="col">Our item</th>
                <th scope="col">Supplier unit</th>
                <th scope="col">Our unit</th>
                <th scope="col" className="num">Conversion</th>
                <th scope="col">Status</th>
                <th scope="col">Created by</th>
                <th scope="col">Approved by</th>
                <th scope="col">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((a) => (
                <tr key={a.id}>
                  <td data-label="Supplier">{a.vendor_name}</td>
                  <td data-label="Supplier code">
                    {a.supplier_item_code}
                    {a.supplier_description && <div className="muted small">{a.supplier_description}</div>}
                  </td>
                  <td data-label="Our item">{[a.item_sku, a.item_name].filter(Boolean).join(" · ")}</td>
                  <td data-label="Supplier unit">{a.supplier_uom}</td>
                  <td data-label="Our unit">{a.item_uom}</td>
                  <td data-label="Conversion" className="num">{qty(a.conversion_factor)}</td>
                  <td data-label="Status">
                    <StatusChip status={a.status} />
                  </td>
                  <td data-label="Created by">
                    {a.created_by_name}
                    <div className="muted small">{when(a.valid_from)}</div>
                  </td>
                  <td data-label="Approved by">{a.approved_by_name ?? <span className="muted">{a.status === "active" && a.conversion_factor.startsWith("1.") ? "1:1, no approval needed" : ""}</span>}</td>
                  <td data-label="Actions">
                    {a.status !== "retired" && can("edit_alias") && (
                      <button className="btn small" onClick={() => setRetire(a)}>
                        Retire
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Dialog
        open={!!retire}
        title="Retire alias"
        onClose={() => setRetire(null)}
        footer={
          <>
            <button className="btn" data-safe onClick={() => setRetire(null)}>
              Keep it
            </button>
            <button className="btn danger" disabled={!reason.trim() || retireIt.isPending} onClick={() => retire && retireIt.mutate(retire)}>
              Retire alias
            </button>
          </>
        }
      >
        <p>
          Retire {retire?.supplier_item_code} → {retire?.item_sku}. Every line that used it is re-matched, and an approved report that relied on it is flagged as out of date.
        </p>
        <Field label="Reason (required)">{(f) => <textarea id={f.id} value={reason} onChange={(e) => setReason(e.target.value)} />}</Field>
        {retireIt.error && <p className="error-text">{errorText(retireIt.error)}</p>}
      </Dialog>
    </>
  );
}
