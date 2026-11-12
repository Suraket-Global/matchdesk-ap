import { useEffect, useState, type ReactNode } from "react";
import { AlertOctagon, Inbox, RotateCw } from "lucide-react";

/** An empty state: an icon, what is missing, and one clear next action. */
export function EmptyState({ icon, title, children, action }: { icon?: ReactNode; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="state">
      <span className="state-icon" aria-hidden="true">
        {icon ?? <Inbox size={22} />}
      </span>
      <h2>{title}</h2>
      {children}
      {action && <div className="actions">{action}</div>}
    </div>
  );
}

/** A skeleton that appears only after 400 ms, so fast loads do not flash (design.md 7). */
export function Skeleton({ label = "Loading", lines = 4 }: { label?: string; lines?: number }) {
  const show = useDelayed(400);
  return (
    <div role="status" aria-live="polite" className="skeleton">
      <span className="sr-only">{label}…</span>
      {show && Array.from({ length: lines }, (_, i) => <span key={i} style={{ width: `${[82, 96, 70, 90, 64][i % 5]}%` }} />)}
    </div>
  );
}

/** Table-shaped skeleton for list screens. */
export function TableSkeleton({ rows = 6, label = "Loading" }: { rows?: number; label?: string }) {
  const show = useDelayed(400);
  return (
    <div role="status" aria-live="polite">
      <span className="sr-only">{label}…</span>
      {show && (
        <div className="sk-table" aria-hidden="true">
          {Array.from({ length: rows + 1 }, (_, i) => (
            <div className="sk-row" key={i}>
              {[0, 1, 2, 3].map((c) => (
                <span key={c} className="sk" style={{ width: `${[60, 80, 50, 70][(i + c) % 4]}%`, height: i ? 12 : 10 }} />
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** An error with what happened and a retry. */
export function ErrorPanel({ message, retry }: { message: ReactNode; retry?: () => void }) {
  return (
    <div className="banner error" role="alert">
      <AlertOctagon size={18} aria-hidden="true" />
      <div>
        <p>{message}</p>
      </div>
      {retry && (
        <button className="btn small" onClick={retry}>
          <RotateCw size={14} aria-hidden="true" />
          Retry
        </button>
      )}
    </div>
  );
}

function useDelayed(ms: number): boolean {
  const [show, setShow] = useState(false);
  useEffect(() => {
    const t = window.setTimeout(() => setShow(true), ms);
    return () => window.clearTimeout(t);
  }, [ms]);
  return show;
}
