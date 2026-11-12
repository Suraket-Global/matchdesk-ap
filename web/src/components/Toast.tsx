import { useEffect, useState } from "react";
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
    const timers = new Set<number>();
    push = (text, tone) => {
      const id = ++seq;
      setItems((s) => [...s.slice(-2), { id, text, tone }]);
      const t = window.setTimeout(() => setItems((s) => s.filter((i) => i.id !== id)), 6000);
      timers.add(t);
    };
    return () => {
      push = null;
      timers.forEach((t) => window.clearTimeout(t));
    };
  }, []);
  return (
    <div className="toasts" role="status" aria-live="polite">
      {items.map((i) => (
        <div key={i.id} className={`toast ${i.tone === "error" ? "error" : ""}`}>
          {i.tone === "error" ? <AlertCircle size={18} aria-hidden="true" /> : <CheckCircle2 size={18} aria-hidden="true" />}
          {i.text}
        </div>
      ))}
    </div>
  );
}
