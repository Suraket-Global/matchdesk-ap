import { useMemo, useState, type ReactNode } from "react";
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";
import { EmptyState, TableSkeleton } from "./States";

export interface Column<T> {
  key: string;
  header: ReactNode;
  /** Plain text of the header, used as the cell label when the table stacks at phone width. */
  label?: string;
  cell: (row: T) => ReactNode;
  /** Right-aligned with tabular figures (money and quantities). */
  numeric?: boolean;
  /** A comparable value enables sorting on this column. */
  sortValue?: (row: T) => string | number | bigint;
  className?: string;
}

export interface DataTableProps<T> {
  rows: T[] | undefined;
  columns: Column<T>[];
  rowKey: (row: T) => string;
  caption?: string;
  loading?: boolean;
  empty?: ReactNode;
  footer?: ReactNode;
  /** Selection: the set of selected keys and its setter. Adds a checkbox column. */
  selected?: Set<string>;
  onSelectedChange?: (next: Set<string>) => void;
  rowLabel?: (row: T) => string;
  onRowClick?: (row: T) => void;
  initialSort?: { key: string; dir: "asc" | "desc" };
  /** Stack rows into labelled cards at phone width instead of scrolling. */
  stackOnPhone?: boolean;
  stickyHeader?: boolean;
}

function cmp(a: string | number | bigint, b: string | number | bigint): number {
  if (typeof a === "string" && typeof b === "string") return a.localeCompare(b);
  return a < b ? -1 : a > b ? 1 : 0;
}

/** The one data table: sticky header, sorting, row hover, selection, right-aligned money,
 * loading skeleton and empty state. Scrolls inside its own container, never the page. */
export function DataTable<T>(p: DataTableProps<T>) {
  const [sort, setSort] = useState(p.initialSort ?? null);
  const rows = useMemo(() => {
    const r = p.rows ?? [];
    const col = sort && p.columns.find((c) => c.key === sort.key);
    if (!col?.sortValue) return r;
    const s = [...r].sort((a, b) => cmp(col.sortValue!(a), col.sortValue!(b)));
    return sort!.dir === "desc" ? s.reverse() : s;
  }, [p.rows, p.columns, sort]);
  if (p.loading) return <TableSkeleton />;
  if (!rows.length) return <div className="panel">{p.empty ?? <EmptyState title="Nothing here yet" />}</div>;
  const sel = p.selected;
  const allOn = !!sel && rows.every((r) => sel.has(p.rowKey(r)));
  const toggle = (k: string) => {
    if (!sel || !p.onSelectedChange) return;
    const n = new Set(sel);
    if (n.has(k)) n.delete(k);
    else n.add(k);
    p.onSelectedChange(n);
  };
  return (
    <div className={`table-wrap ${p.stickyHeader ? "sticky" : ""}`} tabIndex={0} role="region" aria-label={p.caption ?? "Table"}>
      <table className={p.stackOnPhone ? "stack-sm" : undefined}>
        {p.caption && <caption className="sr-only">{p.caption}</caption>}
        <thead>
          <tr>
            {sel && (
              <th scope="col" className="check">
                <input
                  type="checkbox"
                  aria-label="Select all rows"
                  checked={allOn}
                  onChange={() => p.onSelectedChange?.(allOn ? new Set() : new Set(rows.map(p.rowKey)))}
                />
              </th>
            )}
            {p.columns.map((c) => {
              const dir = sort?.key === c.key ? sort.dir : null;
              return (
                <th
                  key={c.key}
                  scope="col"
                  className={[c.numeric && "num", c.className].filter(Boolean).join(" ") || undefined}
                  aria-sort={dir ? (dir === "asc" ? "ascending" : "descending") : c.sortValue ? "none" : undefined}
                >
                  {c.sortValue ? (
                    <button
                      type="button"
                      className="sort"
                      onClick={() => setSort({ key: c.key, dir: dir === "desc" ? "asc" : "desc" })}
                    >
                      {c.header}
                      {dir === "asc" ? <ArrowUp size={12} aria-hidden="true" /> : dir === "desc" ? <ArrowDown size={12} aria-hidden="true" /> : <ArrowUpDown size={12} aria-hidden="true" />}
                    </button>
                  ) : (
                    c.header
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const k = p.rowKey(r);
            const on = sel?.has(k) ?? false;
            return (
              <tr
                key={k}
                className={[p.onRowClick && "row-link", on && "selected"].filter(Boolean).join(" ") || undefined}
                aria-selected={sel ? on : undefined}
                onClick={
                  p.onRowClick
                    ? (e) => {
                        if ((e.target as HTMLElement).closest("input,a,button,select")) return;
                        p.onRowClick!(r);
                      }
                    : undefined
                }
              >
                {sel && (
                  <td className="check" data-label="Select">
                    <input type="checkbox" aria-label={`Select ${p.rowLabel?.(r) ?? k}`} checked={on} onChange={() => toggle(k)} />
                  </td>
                )}
                {p.columns.map((c) => (
                  <td key={c.key} data-label={c.label ?? (typeof c.header === "string" ? c.header : "")} className={[c.numeric && "num", c.className].filter(Boolean).join(" ") || undefined}>
                    {c.cell(r)}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
        {p.footer && <tfoot>{p.footer}</tfoot>}
      </table>
    </div>
  );
}
