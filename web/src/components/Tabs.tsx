import { useId, useRef, type KeyboardEvent, type ReactNode } from "react";

export interface TabItem {
  id: string;
  label: ReactNode;
  count?: number;
}

/** ARIA tabs with arrow-key movement. The panel content is rendered by the caller for `value`. */
export function Tabs({ items, value, onChange, label, children }: { items: TabItem[]; value: string; onChange: (id: string) => void; label: string; children?: ReactNode }) {
  const base = useId();
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const onKey = (e: KeyboardEvent, i: number) => {
    const d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (!d) return;
    const n = (i + d + items.length) % items.length;
    onChange(items[n].id);
    refs.current[n]?.focus();
  };
  return (
    <>
      <div className="tabs" role="tablist" aria-label={label}>
        {items.map((t, i) => (
          <button
            key={t.id}
            ref={(el) => (refs.current[i] = el)}
            role="tab"
            id={`${base}-${t.id}`}
            aria-selected={t.id === value}
            aria-controls={`${base}-panel`}
            tabIndex={t.id === value ? 0 : -1}
            onClick={() => onChange(t.id)}
            onKeyDown={(e) => onKey(e, i)}
          >
            {t.label}
            {t.count !== undefined && <span className="nav-count">{t.count}</span>}
          </button>
        ))}
      </div>
      {children !== undefined && (
        <div role="tabpanel" id={`${base}-panel`} aria-labelledby={`${base}-${value}`}>
          {children}
        </div>
      )}
    </>
  );
}
