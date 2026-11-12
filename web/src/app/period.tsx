import { createContext, useContext, useState, type ReactNode } from "react";
import { lastMonth } from "../lib/format";

// The test month the screens work on (top bar period selector). Held in memory only: the app keeps
// nothing in browser storage (App-flow.md 4.3), so a reload starts again at last month.
const PeriodContext = createContext<{ month: string; setMonth: (m: string) => void } | null>(null);

export function PeriodProvider({ children }: { children: ReactNode }) {
  const [month, set] = useState(lastMonth);
  const setMonth = (m: string) => {
    if (/^\d{4}-\d{2}$/.test(m)) set(m);
  };
  return <PeriodContext.Provider value={{ month, setMonth }}>{children}</PeriodContext.Provider>;
}

/** The selected test month as YYYY-MM; last month until someone picks another. */
export function usePeriod(): { month: string; setMonth: (m: string) => void } {
  return useContext(PeriodContext) ?? { month: lastMonth(), setMonth: () => undefined };
}
