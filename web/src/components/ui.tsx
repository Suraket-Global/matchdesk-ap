import { Component, useEffect, useRef, useState, type ErrorInfo, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { AlertOctagon, AlertTriangle, CheckCircle2, Info, Lock, PenLine, SearchX } from "lucide-react";
import { ApiError, errorText } from "../api/client";
import { iconFor } from "./Badge";
import { PageHeader, type Crumb } from "./Page";
import { EmptyState, ErrorPanel, Skeleton } from "./States";

/* Compatibility layer: screens import from here; the components themselves live in this folder
   (Button, Form, Badge, Card, DataTable, Tabs, Overlay, Toast, Tooltip, Page, FileDropzone, States). */

export { Dialog, Drawer } from "./Overlay";
export { toast, ToastHost } from "./Toast";
export { Field } from "./Form";
export { StatusPill as StatusChip } from "./Badge";

/** Sets "<object> · <screen> · MatchDesk" as the document title. */
export function usePageTitle(screen: string, object?: string | null): void {
  useEffect(() => {
    document.title = [object, screen, "MatchDesk"].filter(Boolean).join(" · ");
  }, [screen, object]);
}

export function PageHead(props: { title: ReactNode; lede?: ReactNode; crumbs?: ReactNode | Crumb[]; actions?: ReactNode }) {
  return <PageHeader {...props} />;
}

export function Icon({ name }: { name: string }) {
  const I = iconFor(name);
  return <I size={12} aria-hidden="true" strokeWidth={2.5} />;
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return <Skeleton label={label} />;
}

export function Empty({ title, children, icon, action }: { title: string; children?: ReactNode; icon?: ReactNode; action?: ReactNode }) {
  return (
    <EmptyState title={title} icon={icon} action={action}>
      {children}
    </EmptyState>
  );
}

export function ErrorState({ error, retry }: { error: unknown; retry?: () => void }) {
  // An unknown or foreign record is the not-found page (S-19), identical either way (review, minor).
  if (error instanceof ApiError && error.status === 404)
    return (
      <>
        <PageHeader title="Not found" lede="This page or record does not exist, or you do not have access to it." />
        <div className="panel">
          <EmptyState title="Nothing at this address" icon={<SearchX size={22} />} action={<Link className="btn primary" to="/exceptions">Go to the exception queue</Link>} />
        </div>
      </>
    );
  return <ErrorPanel message={errorText(error)} retry={retry} />;
}

const BANNER_ICON = { info: Info, warn: AlertTriangle, error: AlertOctagon, ok: CheckCircle2, draft: PenLine, approved: Lock };

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
  const I = BANNER_ICON[tone];
  return (
    <div className={`banner ${tone}`} role={role ?? (tone === "error" ? "alert" : undefined)}>
      <I size={18} aria-hidden="true" />
      <div>{children}</div>
      {onDismiss && (
        <button className="btn small ghost" onClick={onDismiss} aria-label="Dismiss">
          Dismiss
        </button>
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
          <AlertOctagon size={18} aria-hidden="true" />
          <p style={{ flex: 1 }}>This page could not be shown. Your saved work is safe on the server. Reload the page; if it happens again, note the time and tell support.</p>
          <button className="btn small" onClick={() => window.location.reload()}>
            Reload
          </button>
        </div>
      );
    return this.props.children;
  }
}
