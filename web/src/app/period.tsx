import { createContext, useContext, useState, type ReactNode } from "react";
import { lastMonth } from "../lib/format";

// The test month the screens work on (top bar period selector). Held in memory only: the app keeps
// nothing in browser storage (App-flow.md 4.3); a reload starts at the month in the address, else last month.
const PeriodContext = createContext<{ month: string; setMonth: (m: string) => void } | null>(null);

/** The month a link or a reload carries in its address (?period= or ?month=), if any. Read from the
 * address, not from storage, so a reloaded or shared page opens on the month it showed. */
export function monthFromAddress(search: string = typeof window === "undefined" ? "" : window.location.search): string | null {
  const q = new URLSearchParams(search);
  const m = q.get("period") ?? q.get("month");
  return m && /^\d{4}-(0[1-9]|1[0-2])$/.test(m) ? m : null;
}

export function PeriodProvider({ children }: { children: ReactNode }) {
  const [month, set] = useState(() => monthFromAddress() ?? lastMonth());
  const setMonth = (m: string) => {
    if (/^\d{4}-\d{2}$/.test(m)) set(m);
  };
  return <PeriodContext.Provider value={{ month, setMonth }}>{children}</PeriodContext.Provider>;
}

/** The selected test month as YYYY-MM; last month until someone picks another. */
export function usePeriod(): { month: string; setMonth: (m: string) => void } {
  return useContext(PeriodContext) ?? { month: lastMonth(), setMonth: () => undefined };
}
