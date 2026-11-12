import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

// Single-key shortcuts (J, K, X, Enter) can be turned off in the user menu and never fire while a
// text field has focus (WCAG 2.1.4). The choice lives in memory for this tab only.
const Ctx = createContext<{ enabled: boolean; setEnabled: (v: boolean) => void }>({
  enabled: true,
  setEnabled: () => undefined,
});

export function ShortcutsProvider({ children }: { children: ReactNode }) {
  const [enabled, setEnabled] = useState(true);
  return <Ctx.Provider value={{ enabled, setEnabled }}>{children}</Ctx.Provider>;
}

export function useShortcuts() {
  return useContext(Ctx);
}

function typing(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el) return false;
  const tag = el.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el.isContentEditable || !!el.closest("dialog[open]");
}

/** Bind single keys while shortcuts are on and nobody is typing. */
export function useKeys(map: Record<string, (e: KeyboardEvent) => void>, active = true): void {
  const { enabled } = useShortcuts();
  useEffect(() => {
    if (!enabled || !active) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey || typing(e.target)) return;
      const fn = map[e.key] ?? map[e.key.toLowerCase()];
      if (fn) {
        e.preventDefault();
        fn(e);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [enabled, active, map]);
}
