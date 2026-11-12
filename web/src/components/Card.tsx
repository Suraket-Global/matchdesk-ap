import type { ReactNode } from "react";

/** A bordered surface with an optional header row (title and actions) and footer. */
export function Card(props: { title?: ReactNode; titleId?: string; actions?: ReactNode; footer?: ReactNode; children: ReactNode; className?: string; flush?: boolean }) {
  return (
    <section className={`panel ${props.className ?? ""}`} aria-labelledby={props.title ? props.titleId : undefined}>
      {(props.title || props.actions) && (
        <div className="panel-head">
          {props.title && <h2 id={props.titleId}>{props.title}</h2>}
          {props.actions && <div className="actions">{props.actions}</div>}
        </div>
      )}
      {props.flush ? props.children : <div className="panel-body">{props.children}</div>}
      {props.footer && <div className="card-foot">{props.footer}</div>}
    </section>
  );
}

/** One figure with its label and a short qualifier. Money is set in tabular figures. */
export function StatCard(props: { label: ReactNode; value: ReactNode; sub?: ReactNode; icon?: ReactNode; tone?: "danger" | "success" | "neutral" }) {
  return (
    <div className={`stat ${props.tone && props.tone !== "neutral" ? `tone-${props.tone}` : ""}`}>
      <span className="k">
        {props.icon}
        {props.label}
      </span>
      <span className="v">{props.value}</span>
      {props.sub && <span className="s">{props.sub}</span>}
    </div>
  );
}
