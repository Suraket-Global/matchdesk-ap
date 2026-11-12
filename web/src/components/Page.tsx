import { useEffect, useRef, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { ChevronLeft, ChevronRight } from "lucide-react";

export interface Crumb {
  to?: string;
  label: string;
}

/** Breadcrumb trail; the last item is the current page and is not a link. */
export function Breadcrumbs({ items }: { items: Crumb[] }) {
  return (
    <nav className="crumbs" aria-label="Breadcrumb">
      <ol>
        {items.map((c, i) => (
          <li key={i}>
            {i > 0 && <ChevronRight size={14} aria-hidden="true" />}
            {c.to ? <Link to={c.to}>{c.label}</Link> : <span aria-current="page">{c.label}</span>}
          </li>
        ))}
      </ol>
    </nav>
  );
}

/** Title, one-line description, breadcrumbs and page actions. Focus lands on the title after navigation. */
export function PageHeader(props: { title: ReactNode; lede?: ReactNode; crumbs?: ReactNode | Crumb[]; actions?: ReactNode; headingRef?: React.RefObject<HTMLHeadingElement> }) {
  const own = useRef<HTMLHeadingElement>(null);
  const ref = props.headingRef ?? own;
  useEffect(() => {
    if (document.activeElement === document.body || document.activeElement?.id === "main") ref.current?.focus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const crumbs = Array.isArray(props.crumbs) ? <Breadcrumbs items={props.crumbs as Crumb[]} /> : props.crumbs ? <nav className="crumbs" aria-label="Breadcrumb">{props.crumbs}</nav> : null;
  return (
    <div className="page-head">
      <div>
        {crumbs}
        <h1 ref={ref} tabIndex={-1}>
          {props.title}
        </h1>
        {props.lede && <p className="lede">{props.lede}</p>}
      </div>
      {props.actions && <div className="actions">{props.actions}</div>}
    </div>
  );
}

/** Previous and next page controls with a range sentence. */
export function Pagination({ page, pageSize, total, onPage }: { page: number; pageSize: number; total: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const from = total ? (page - 1) * pageSize + 1 : 0;
  const to = Math.min(total, page * pageSize);
  return (
    <nav className="pagination" aria-label="Pagination">
      <span>
        {from}–{to} of {total}
      </span>
      <div className="actions">
        <button className="btn small" disabled={page <= 1} onClick={() => onPage(page - 1)}>
          <ChevronLeft size={14} aria-hidden="true" />
          Previous
        </button>
        <span className="muted">
          Page {page} of {pages}
        </span>
        <button className="btn small" disabled={page >= pages} onClick={() => onPage(page + 1)}>
          Next
          <ChevronRight size={14} aria-hidden="true" />
        </button>
      </div>
    </nav>
  );
}

/** A horizontal progress stepper: done steps carry a tick, the current step is announced. */
export function Stepper({ steps, current }: { steps: { label: string; sub?: string; done: boolean }[]; current: number }) {
  const done = steps.filter((s) => s.done).length;
  return (
    <>
      <div className="progress" role="progressbar" aria-label="Setup progress" aria-valuemin={0} aria-valuemax={steps.length} aria-valuenow={done} style={{ marginBottom: 16 }}>
        <span style={{ width: `${(done / steps.length) * 100}%` }} />
      </div>
      <ol className="stepper">
        {steps.map((s, i) => (
          <li key={i} className={[s.done && "done", i === current && "current"].filter(Boolean).join(" ")} aria-current={i === current ? "step" : undefined}>
            <span className="bullet" aria-hidden="true">
              {s.done ? "✓" : i + 1}
            </span>
            <span className="step-text">
              <span className="sr-only">{s.done ? "Done: " : i === current ? "Current: " : "To do: "}</span>
              <span className="step-label">{s.label}</span>
              {s.sub && <span className="step-sub">{s.sub}</span>}
            </span>
          </li>
        ))}
      </ol>
    </>
  );
}


