import { useCallback, useEffect, useState } from "react";
import { AlertCircle, CheckCircle2 } from "lucide-react";

type Tone = "success" | "error";
interface Item {
  id: number;
  text: string;
  tone: Tone;
}

let push: ((text: string, tone: Tone) => void) | null = null;
let seq = 0;

/** Announces a short result ("Resolved", "Approved") politely and shows it for six seconds. */
export function toast(text: string, tone: Tone = "success"): void {
  push?.(text, tone);
}

export function ToastHost() {
  const [items, setItems] = useState<Item[]>([]);
  useEffect(() => {
    push = (text, tone) => setItems((s) => [...s.slice(-2), { id: ++seq, text, tone }]);
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

/** Each toast owns its six-second timer, so a re-mounted host never leaves one on screen for good
 * (B6 review minor: "Confirmed. Matching…" stayed). */
function ToastItem({ item, onDone }: { item: Item; onDone: (id: number) => void }) {
  useEffect(() => {
    const t = window.setTimeout(() => onDone(item.id), 6000);
    return () => window.clearTimeout(t);
  }, [item.id, onDone]);
  return (
    <div className={`toast ${item.tone === "error" ? "error" : ""}`}>
      {item.tone === "error" ? <AlertCircle size={18} aria-hidden="true" /> : <CheckCircle2 size={18} aria-hidden="true" />}
      {item.text}
    </div>
  );
}
