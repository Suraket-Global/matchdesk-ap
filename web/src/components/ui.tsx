import { Component, useEffect, useId, useRef, useState, type ErrorInfo, type ReactNode } from "react";
import { errorText } from "../api/client";

/* ------------------------------------------------------------ page title and focus (App-flow 5) */

/** Sets "<object> · <screen> · MatchDesk" and moves focus to the main heading on route change. */
export function usePageTitle(screen: string, object?: string | null): void {
  useEffect(() => {
    document.title = [object, screen, "MatchDesk"].filter(Boolean).join(" · ");
  }, [screen, object]);
}

export function PageHead(props: {
  title: ReactNode;
  lede?: ReactNode;
  crumbs?: ReactNode;
  actions?: ReactNode;
}) {
  const ref = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    // Focus after navigation lands on the page's main heading, unless something else took it.
    if (document.activeElement === document.body || document.activeElement?.id === "main") ref.current?.focus();
  }, []);
  return (
    <div className="page-head">
      <div>
        {props.crumbs && <nav className="crumbs" aria-label="Breadcrumb">{props.crumbs}</nav>}
        <h1 ref={ref} tabIndex={-1}>
          {props.title}
        </h1>
        {props.lede && <p className="lede">{props.lede}</p>}
      </div>
      {props.actions && <div className="actions">{props.actions}</div>}
    </div>
  );
}

/* ------------------------------------------------------------ icons (never without their word) */

const PATHS: Record<string, string> = {
  tick: "M2.5 6.5 5 9l4.5-6",
  cross: "M3 3l6 6M9 3 3 9",
  absent: "M6 2.2v4.6M6 9.2v.4",
  clock: "M6 3.2V6l2 1.3",
  dash: "M3 6h6",
  draft: "M3 9l.6-2.4L8 2.2l1.8 1.8-4.4 4.4z",
  lock: "M3.5 5.5h5v4h-5zM4.5 5.5V4a1.5 1.5 0 0 1 3 0v1.5",
  stack: "M2 4.5 6 2.5l4 2-4 2zM2 7.5l4 2 4-2",
};

export function Icon({ name }: { name: keyof typeof PATHS | string }) {
  const round = name === "absent" || name === "clock";
  return (
    <svg viewBox="0 0 12 12" aria-hidden="true" focusable="false">
      {round && <circle cx="6" cy="6" r="5" fill="none" stroke="currentColor" strokeWidth="1.4" />}
      <path d={PATHS[name] ?? PATHS.dash} fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/* ------------------------------------------------------------ status chip (DD-03, design 6) */

type Tone = "matched" | "exception" | "absent" | "draft" | "approved" | "waived" | "neutral";

const CHIP: Record<string, { tone: Tone; icon: string; word: string }> = {
  matched: { tone: "matched", icon: "tick", word: "Matched" },
  charge_ok: { tone: "neutral", icon: "dash", word: "Charge allowed" },
  exception: { tone: "exception", icon: "cross", word: "Exception" },
  open: { tone: "exception", icon: "cross", word: "Exception" },
  receipt_absent: { tone: "absent", icon: "absent", word: "Receipt absent" },
  unverified: { tone: "absent", icon: "absent", word: "Unverified" },
  pending_approval: { tone: "draft", icon: "clock", word: "Pending approval" },
  pending: { tone: "draft", icon: "clock", word: "Pending approval" },
  waived: { tone: "waived", icon: "dash", word: "Waived" },
  resolved: { tone: "neutral", icon: "tick", word: "Resolved" },
  auto_closed: { tone: "neutral", icon: "dash", word: "Closed by a re-match" },
  needs_review: { tone: "draft", icon: "draft", word: "Needs review" },
  "needs review": { tone: "draft", icon: "draft", word: "Needs review" },
  draft: { tone: "draft", icon: "draft", word: "Draft" },
  approved: { tone: "approved", icon: "lock", word: "Approved" },
  returned: { tone: "neutral", icon: "dash", word: "Returned" },
  superseded: { tone: "waived", icon: "stack", word: "Superseded" },
  stale: { tone: "draft", icon: "clock", word: "Out of date" },
  not_evaluated: { tone: "neutral", icon: "dash", word: "Not matched yet" },
  ready: { tone: "matched", icon: "tick", word: "Ready" },
  queued: { tone: "neutral", icon: "clock", word: "Queued" },
  processing: { tone: "neutral", icon: "clock", word: "Processing" },
  failed: { tone: "exception", icon: "cross", word: "Failed" },
  "duplicate file": { tone: "absent", icon: "stack", word: "Duplicate file" },
  succeeded: { tone: "matched", icon: "tick", word: "Imported" },
  voided: { tone: "waived", icon: "dash", word: "Voided" },
  active: { tone: "matched", icon: "tick", word: "Active" },
  retired: { tone: "waived", icon: "dash", word: "Retired" },
  deactivated: { tone: "waived", icon: "dash", word: "Deactivated" },
  connected: { tone: "matched", icon: "tick", word: "Connected" },
  disconnected: { tone: "waived", icon: "dash", word: "Not connected" },
};

export function StatusChip({ status, word }: { status: string; word?: string }) {
  const c = CHIP[status] ?? { tone: "neutral" as Tone, icon: "dash", word: status.replace(/_/g, " ") };
  // Green is used only for a line that passed every check (design.md 5).
  return (
    <span className={`chip ${c.tone}`}>
      <Icon name={c.icon} />
      {word ?? c.word}
    </span>
  );
}

/* ------------------------------------------------------------ data states */

export function Loading({ label = "Loading" }: { label?: string }) {
  // A spinner or skeleton only after 400 ms (design.md 7).
  const [show, setShow] = useState(false);
  useEffect(() => {
    const t = window.setTimeout(() => setShow(true), 400);
    return () => window.clearTimeout(t);
  }, []);
  return (
    <div role="status" aria-live="polite" className="skeleton">
      <span className="sr-only">{label}…</span>
      {show && [80, 95, 70, 90].map((w, i) => <span key={i} style={{ width: `${w}%` }} />)}
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="state">
      <h2>{title}</h2>
      {children}
    </div>
  );
}

export function ErrorState({ error, retry }: { error: unknown; retry?: () => void }) {
  return (
    <div className="banner error" role="alert">
      <p>{errorText(error)}</p>
      {retry && (
        <button className="btn small" onClick={retry}>
          Retry
        </button>
      )}
    </div>
  );
}

export function Banner({
  tone = "info",
  children,
  onDismiss,
  role,
}: {
  tone?: "info" | "warn" | "error" | "ok" | "draft" | "approved";
  children: ReactNode;
  onDismiss?: () => void;
  role?: "alert" | "status";
}) {
  return (
    <div className={`banner ${tone}`} role={role ?? (tone === "error" ? "alert" : undefined)}>
      <div>{children}</div>
      {onDismiss && (
        <button className="btn small ghost" onClick={onDismiss} aria-label="Dismiss">
          Dismiss
        </button>
      )}
    </div>
  );
}

/* ------------------------------------------------------------ dialog (design 6: confirm dialog) */

export function Dialog(props: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const opener = useRef<Element | null>(null);
  const titleId = useId();
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (props.open && !d.open) {
      opener.current = document.activeElement;
      d.showModal();
      // Focus starts on the safe button: the first one marked data-safe, else the first button.
      const safe = d.querySelector<HTMLElement>("[data-safe]") ?? d.querySelector<HTMLElement>(".modal-foot button");
      safe?.focus();
    } else if (!props.open && d.open) {
      d.close();
      if (opener.current instanceof HTMLElement && document.contains(opener.current)) opener.current.focus();
    }
  }, [props.open]);
  return (
    <dialog
      ref={ref}
      className="modal"
      aria-labelledby={titleId}
      onCancel={(e) => {
        e.preventDefault();
        props.onClose();
      }}
    >
      <div className="modal-head">
        <h2 id={titleId}>{props.title}</h2>
      </div>
      <div className="modal-body">{props.children}</div>
      <div className="modal-foot">{props.footer}</div>
    </dialog>
  );
}

/* ------------------------------------------------------------ toast and live status */

let toastFn: ((text: string) => void) | null = null;
export function toast(text: string): void {
  toastFn?.(text);
}

export function ToastHost() {
  const [text, setText] = useState<string | null>(null);
  useEffect(() => {
    let t: number | undefined;
    toastFn = (s) => {
      setText(s);
      window.clearTimeout(t);
      t = window.setTimeout(() => setText(null), 6000);
    };
    return () => {
      toastFn = null;
      window.clearTimeout(t);
    };
  }, []);
  return (
    <div role="status" aria-live="polite">
      {text && <div className="toast">{text}</div>}
    </div>
  );
}

/* ------------------------------------------------------------ form field */

export function Field(props: {
  label: string;
  hint?: ReactNode;
  error?: string | null;
  children: (ids: { id: string; describedBy: string | undefined; invalid: boolean }) => ReactNode;
}) {
  const id = useId();
  const hintId = props.hint ? `${id}-hint` : undefined;
  const errId = props.error ? `${id}-err` : undefined;
  return (
    <div className="field">
      <label htmlFor={id}>{props.label}</label>
      {props.children({ id, describedBy: [hintId, errId].filter(Boolean).join(" ") || undefined, invalid: !!props.error })}
      {props.hint && (
        <span className="hint" id={hintId}>
          {props.hint}
        </span>
      )}
      {props.error && (
        <span className="error" id={errId}>
          {props.error}
        </span>
      )}
    </div>
  );
}

/** A polite live region that announces at most once every 15 seconds (design 11, 4.1.3). */
export function ThrottledStatus({ text, final }: { text: string; final?: boolean }) {
  const [said, setSaid] = useState(text);
  const last = useRef(0);
  useEffect(() => {
    const now = Date.now();
    if (final || now - last.current >= 15_000) {
      setSaid(text);
      last.current = now;
    }
  }, [text, final]);
  return (
    <div className="sr-only" role="status" aria-live="polite">
      {said}
    </div>
  );
}

export function NarrowNote() {
  return <p className="narrow-note banner warn">Open in a wider window to work on this.</p>;
}

/* ------------------------------------------------------------ error boundary */


export class PageErrorBoundary extends Component<{ children: ReactNode; resetKey: string }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch(_error: Error, _info: ErrorInfo) {
    /* shown on screen; nothing is sent anywhere */
  }
  componentDidUpdate(prev: { resetKey: string }) {
    if (prev.resetKey !== this.props.resetKey && this.state.failed) this.setState({ failed: false });
  }
  render() {
    if (this.state.failed)
      return (
        <div className="banner error" role="alert">
          <p>This page could not be shown. Your saved work is safe on the server. Reload the page; if it happens again, note the time and tell support.</p>
          <button className="btn small" onClick={() => window.location.reload()}>
            Reload
          </button>
        </div>
      );
    return this.props.children;
  }
}
