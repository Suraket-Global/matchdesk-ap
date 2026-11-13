import { useCallback, useEffect, useRef, useState, type CSSProperties, type KeyboardEvent, type PointerEvent, type RefObject } from "react";

/** Widths of the three S-09 panes (document, comparison, actions) as shares of 100 (B12). */
export type PaneWidths = [number, number, number];

export const DEFAULT_WIDTHS: PaneWidths = [36, 40, 24];
/** The smallest share each pane keeps, so no pane can be dragged shut. */
export const MIN_WIDTHS: PaneWidths = [20, 26, 18];
export const STORAGE_KEY = "matchdesk.s09.panes";
const STEP = 2;
const BIG_STEP = 10;

function round(n: number): number {
  return Math.round(n * 10) / 10;
}

/** Move the boundary after pane ``index`` (0: document|comparison, 1: comparison|actions) by
 * ``delta`` shares; the two neighbours trade width and each keeps its minimum. */
export function movePane(w: PaneWidths, index: 0 | 1, delta: number): PaneWidths {
  const a = index;
  const b = index + 1;
  const lo = MIN_WIDTHS[a] - w[a];
  const hi = w[b] - MIN_WIDTHS[b];
  const d = Math.min(Math.max(delta, lo), hi);
  const next = [...w] as PaneWidths;
  next[a] = round(w[a] + d);
  next[b] = round(w[b] - d);
  return next;
}

/** A stored value is used only when it is three numbers above their minimums summing to 100. */
export function parseWidths(raw: string | null): PaneWidths | null {
  if (!raw) return null;
  try {
    const v: unknown = JSON.parse(raw);
    if (!Array.isArray(v) || v.length !== 3 || !v.every((n) => typeof n === "number" && Number.isFinite(n))) return null;
    const w = v as PaneWidths;
    if (w.some((n, i) => n < MIN_WIDTHS[i]) || Math.abs(w[0] + w[1] + w[2] - 100) > 0.5) return null;
    return w;
  } catch {
    return null;
  }
}

function readStored(): PaneWidths {
  try {
    return parseWidths(window.sessionStorage.getItem(STORAGE_KEY)) ?? DEFAULT_WIDTHS;
  } catch {
    return DEFAULT_WIDTHS;
  }
}

function store(w: PaneWidths | null): void {
  try {
    if (w === null) window.sessionStorage.removeItem(STORAGE_KEY);
    else window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(w));
  } catch {
    // Storage blocked (private window, site data cleared): the widths last for this page only.
  }
}

/** The pane widths of S-09, remembered for this browser tab (sessionStorage). */
export function usePaneWidths() {
  const [widths, setWidths] = useState<PaneWidths>(readStored);
  const update = useCallback((next: PaneWidths) => {
    setWidths(next);
    store(next);
  }, []);
  const reset = useCallback(() => {
    setWidths(DEFAULT_WIDTHS);
    store(null);
  }, []);
  const style = {
    "--match-cols": `minmax(0, ${widths[0]}fr) var(--splitter-w) minmax(0, ${widths[1]}fr) var(--splitter-w) minmax(240px, ${widths[2]}fr)`,
  } as CSSProperties;
  return { widths, update, reset, style };
}

const LABELS = ["Resize the document and comparison panes", "Resize the comparison and actions panes"];

/** A vertical drag handle between two panes. Arrow keys move it (Shift for a larger step), Home and
 * End go to the limits, a double click or Enter resets every pane. */
export function PaneSeparator({
  index,
  widths,
  onChange,
  onReset,
  gridRef,
}: {
  index: 0 | 1;
  widths: PaneWidths;
  onChange: (w: PaneWidths) => void;
  onReset: () => void;
  gridRef: RefObject<HTMLElement | null>;
}) {
  const drag = useRef<{ x: number; start: PaneWidths; width: number } | null>(null);
  const [active, setActive] = useState(false);
  // The boundary's position from the left edge, in shares of 100: what a screen reader announces.
  const position = round(index === 0 ? widths[0] : widths[0] + widths[1]);
  const min = round(index === 0 ? MIN_WIDTHS[0] : widths[0] + MIN_WIDTHS[1]);
  const max = round(index === 0 ? widths[0] + widths[1] - MIN_WIDTHS[1] : 100 - MIN_WIDTHS[2]);

  useEffect(() => () => document.body.classList.remove("is-resizing"), []);

  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    const step = e.shiftKey ? BIG_STEP : STEP;
    let delta: number | null = null;
    if (e.key === "ArrowLeft") delta = -step;
    else if (e.key === "ArrowRight") delta = step;
    else if (e.key === "Home") delta = -100;
    else if (e.key === "End") delta = 100;
    else if (e.key === "Enter") {
      e.preventDefault();
      onReset();
      return;
    }
    if (delta === null) return;
    e.preventDefault();
    onChange(movePane(widths, index, delta));
  }

  function onPointerDown(e: PointerEvent<HTMLDivElement>) {
    if (e.button !== 0) return;
    const width = gridRef.current?.getBoundingClientRect().width ?? 0;
    if (width <= 0) return;
    drag.current = { x: e.clientX, start: widths, width };
    e.currentTarget.setPointerCapture?.(e.pointerId);
    setActive(true);
    document.body.classList.add("is-resizing");
  }

  function onPointerMove(e: PointerEvent<HTMLDivElement>) {
    const d = drag.current;
    if (!d) return;
    onChange(movePane(d.start, index, ((e.clientX - d.x) / d.width) * 100));
  }

  function end(e: PointerEvent<HTMLDivElement>) {
    if (!drag.current) return;
    drag.current = null;
    e.currentTarget.releasePointerCapture?.(e.pointerId);
    setActive(false);
    document.body.classList.remove("is-resizing");
  }

  return (
    <div
      className={`pane-splitter${active ? " active" : ""}`}
      style={{ gridArea: index === 0 ? "s1" : "s2" }}
      role="separator"
      aria-orientation="vertical"
      aria-label={LABELS[index]}
      aria-valuenow={position}
      aria-valuemin={min}
      aria-valuemax={max}
      aria-valuetext={`${Math.round(position)} percent from the left`}
      tabIndex={0}
      title="Drag to resize. Double-click to reset."
      onKeyDown={onKeyDown}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={end}
      onPointerCancel={end}
      onDoubleClick={onReset}
    >
      <span className="pane-splitter-grip" aria-hidden="true" />
    </div>
  );
}
