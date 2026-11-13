import { useCallback, useEffect, useState } from "react";
import { AlertCircle, CheckCircle2, Info, X } from "lucide-react";

/** B10 (outside QA item 9): the tone is required, so a failure can no longer show the success
 * styling by default. "info" is neutral: work started, nothing finished yet. */
export type ToastTone = "success" | "error" | "info";
interface Item {
  id: number;
  text: string;
  tone: ToastTone;
}

let push: ((text: string, tone: ToastTone) => void) | null = null;
let seq = 0;
/** At most two at a time (B10, item 16): the newest replaces the oldest, so a stack never grows. */
export const MAX_TOASTS = 2;

/** Announces a short result ("Resolved", "Approved") and shows it for six seconds. An error stays
 * until it is dismissed; it never replaces the reason shown next to the control that failed. */
export function toast(text: string, tone: ToastTone): void {
  push?.(text, tone);
}

export function ToastHost() {
  const [items, setItems] = useState<Item[]>([]);
  useEffect(() => {
    push = (text, tone) => setItems((s) => [...s.filter((i) => i.text !== text).slice(-(MAX_TOASTS - 1)), { id: ++seq, text, tone }]);
    return () => {
      push = null;
    };
  }, []);
  const remove = useCallback((id: number) => setItems((s) => s.filter((i) => i.id !== id)), []);
  return (
    <div className="toasts" role="status" aria-live="polite">
      {items.map((i) => (
        <ToastItem key={i.id} item={i} onDone={remove} />
      ))}
    </div>
  );
}

const ICON = { success: CheckCircle2, error: AlertCircle, info: Info };

/** Each toast owns its six-second timer, so a re-mounted host never leaves one on screen for good
 * (B6 review minor: "Confirmed. Matching…" stayed). */
function ToastItem({ item, onDone }: { item: Item; onDone: (id: number) => void }) {
  useEffect(() => {
    if (item.tone === "error") return;
    const t = window.setTimeout(() => onDone(item.id), 6000);
    return () => window.clearTimeout(t);
  }, [item.id, item.tone, onDone]);
  const I = ICON[item.tone];
  return (
    <div className={`toast ${item.tone}`} data-tone={item.tone}>
      <I size={18} aria-hidden="true" />
      <span>{item.text}</span>
      <button type="button" className="toast-close" aria-label="Dismiss" onClick={() => onDone(item.id)}>
        <X size={14} aria-hidden="true" />
      </button>
    </div>
  );
}
