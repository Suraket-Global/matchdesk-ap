// B12: the account's billable units by month. The controller sees on S-16 the figures the operator
// sees on S-18 (one table for both), without a price.
import { useQuery } from "@tanstack/react-query";
import { get } from "../api/client";
import type { Usage, UsageMonth } from "../api/types";
import { useSession } from "../app/session";
import { ErrorState, Loading } from "../components/ui";
import { plural } from "../lib/format";

const MONTH = new Intl.DateTimeFormat("en-GB", { month: "long", year: "numeric" });

export function monthWord(month: string): string {
  return MONTH.format(new Date(`${month}T12:00:00`));
}

export function UsageTable({ items }: { items: UsageMonth[] }) {
  if (items.length === 0)
    return (
      <p className="muted" style={{ margin: 0 }}>
        None yet. One unit per invoice or credit note, in the month it is first read.
      </p>
    );
  return (
    <table className="compact">
      <caption className="sr-only">Billable units by month</caption>
      <thead>
        <tr>
          <th scope="col">Month</th>
          <th scope="col" className="num">Invoices</th>
          <th scope="col" className="num">Credit notes</th>
          <th scope="col" className="num">Units</th>
        </tr>
      </thead>
      <tbody>
        {items.map((u) => (
          <tr key={u.month}>
            <td>{monthWord(u.month)}</td>
            <td className="num">{u.invoice}</td>
            <td className="num">{u.credit_note}</td>
            <td className="num">{u.units}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** S-16 "Usage" (controller): the same figures as the operator's console. */
export function UsagePanel() {
  const { can } = useSession();
  const q = useQuery({ queryKey: ["usage"], queryFn: () => get<Usage>("/api/v1/usage"), enabled: can("read_usage") });
  if (!can("read_usage")) return null;
  return (
    <section className="panel" aria-labelledby="my-usage-h">
      <div className="panel-head">
        <h2 id="my-usage-h">Usage</h2>
        {q.data && <span className="muted small">{plural(q.data.total_units ?? 0, "billable unit")} in all</span>}
      </div>
      <div className="panel-body stack">
        <p className="muted small" style={{ margin: 0 }}>
          One unit is one invoice or credit note, counted once in the month it was first read, however often it is
          corrected or matched again. A document deleted later stays counted: it was read.
        </p>
        {q.isLoading && <Loading label="Loading usage" />}
        {q.error && <ErrorState error={q.error} retry={() => q.refetch()} />}
        {q.data && <UsageTable items={q.data.items ?? []} />}
      </div>
    </section>
  );
}
