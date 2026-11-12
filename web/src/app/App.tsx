import { useEffect, useRef, useState, type ReactNode } from "react";
import { Navigate, NavLink, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { SessionProvider, useSession } from "./session";
import { NAV_GROUPS } from "./routes";
import { PeriodProvider, usePeriod } from "./period";
import { get, lastServerContact, send } from "../api/client";
import type { Approval, ExceptionPage, Page, QboConnection } from "../api/types";
import {
  AlertCircle,
  ArrowLeftRight,
  BarChart3,
  Building2,
  CalendarDays,
  CheckSquare,
  ChevronDown,
  FileText,
  History,
  Inbox,
  LifeBuoy,
  Link2,
  ListChecks,
  LogOut,
  Menu,
  PackageCheck,
  PanelLeftClose,
  PanelLeftOpen,
  SlidersHorizontal,
  Users,
  WifiOff,
  type LucideIcon,
} from "lucide-react";
import { Dialog, Loading, PageErrorBoundary, ToastHost } from "../components/ui";
import { LoginPage, VerifyPage } from "../routes/Login";
import { InvitePage } from "../routes/Invite";
import { ForbiddenPage, NotFoundPage, SignedOutPage } from "../routes/System";
import { OnboardingPage, useOnboarding } from "../routes/Onboarding";
import { QuickbooksPage } from "../routes/Quickbooks";
import { ReceivingListPage, ReceivingImportPage } from "../routes/Receiving";
import { IntakeListPage, BatchPage } from "../routes/Intake";
import { ReviewPage } from "../routes/Review";
import { ExceptionsPage } from "../routes/Exceptions";
import { InvoicesPage } from "../routes/Invoices";
import { MatchViewPage } from "../routes/MatchView";
import { PurchaseOrderPage } from "../routes/PurchaseOrder";
import { AliasesPage } from "../routes/Aliases";
import { ApprovalsPage } from "../routes/Approvals";
import { ReportsPage, ReportPage, WeeklyPage } from "../routes/Reports";
import { SettingsPage, TolerancesPage, UsersPage } from "../routes/Settings";
import { AuditPage } from "../routes/Audit";
import { OperatorPage } from "../routes/Operator";
import { ShortcutsProvider, useShortcuts } from "./shortcuts";

export function App() {
  return (
    <SessionProvider>
      <PeriodProvider>
      <ShortcutsProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/login/verify" element={<VerifyPage />} />
          <Route path="/invite" element={<InvitePage />} />
          <Route path="/signed-out" element={<SignedOutPage />} />
          <Route path="/*" element={<SignedIn />} />
        </Routes>
        <ToastHost />
      </ShortcutsProvider>
      </PeriodProvider>
    </SessionProvider>
  );
}

function SignedIn() {
  const { me, loading, expired } = useSession();
  const location = useLocation();
  if (loading) return <Loading label="Signing in" />;
  const back = location.pathname + location.search;
  if (expired) return <Navigate to={`/signed-out?expired=1&next=${encodeURIComponent(back)}`} replace />;
  if (!me) return <Navigate to={`/login?next=${encodeURIComponent(back)}`} replace />;
  if (me.user.is_operator && !me.active_tenant_id)
    return (
      <Shell>
        <Routes>
          <Route path="/operator/tenants/*" element={<OperatorPage />} />
          <Route path="*" element={<Navigate to="/operator/tenants" replace />} />
        </Routes>
      </Shell>
    );
  return (
    <Shell>
      <Routes>
        <Route path="/" element={<RootRedirect />} />
        <Route path="/onboarding" element={<OnboardingPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/settings/quickbooks" element={<QuickbooksPage />} />
        <Route path="/settings/tolerances" element={<TolerancesPage />} />
        <Route path="/settings/users" element={<Guard action="manage_users"><UsersPage /></Guard>} />
        <Route path="/receiving" element={<ReceivingListPage />} />
        <Route path="/receiving/imports/:importId" element={<ReceivingImportPage />} />
        <Route path="/intake" element={<IntakeListPage />} />
        <Route path="/intake/batches/:batchId" element={<BatchPage />} />
        <Route path="/invoices" element={<InvoicesPage />} />
        <Route path="/invoices/:invoiceId" element={<MatchViewPage />} />
        <Route path="/invoices/:invoiceId/review" element={<Guard action="correct_extraction"><ReviewPage /></Guard>} />
        <Route path="/exceptions" element={<ExceptionsPage />} />
        <Route path="/purchase-orders/:poId" element={<PurchaseOrderPage />} />
        <Route path="/aliases" element={<Guard action="edit_alias"><AliasesPage /></Guard>} />
        <Route path="/approvals" element={<Guard action="approve"><ApprovalsPage /></Guard>} />
        <Route path="/reports" element={<ReportsPage />} />
        <Route path="/reports/weekly" element={<WeeklyPage />} />
        <Route path="/reports/backtest/:reportId" element={<ReportPage />} />
        <Route path="/audit" element={<Guard action="read_audit"><AuditPage /></Guard>} />
        <Route path="/operator/tenants/*" element={<OperatorPage />} />
        <Route path="/forbidden" element={<ForbiddenPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </Shell>
  );
}

function Guard({ action, children }: { action: string; children: ReactNode }) {
  const { can } = useSession();
  return can(action) ? <>{children}</> : <ForbiddenPage />;
}

/** `/`: onboarding incomplete -> S-03; controller with pending approvals -> S-12; else S-08. */
function RootRedirect() {
  const { can } = useSession();
  const onboarding = useOnboarding();
  const approvals = useQuery({
    queryKey: ["approvals", "pending"],
    queryFn: () => get<Page<Approval>>("/api/v1/approvals?status=pending"),
    enabled: can("approve"),
  });
  if (onboarding.loading || (can("approve") && approvals.isLoading)) return <Loading />;
  if (!onboarding.complete) return <Navigate to="/onboarding" replace />;
  if (can("approve") && (approvals.data?.items.length ?? 0) > 0) return <Navigate to="/approvals" replace />;
  return <Navigate to="/exceptions" replace />;
}

const NAV_ICONS: Record<string, LucideIcon> = {
  exceptions: AlertCircle,
  invoices: FileText,
  intake: Inbox,
  receiving: PackageCheck,
  approvals: CheckSquare,
  reports: BarChart3,
  onboarding: ListChecks,
  quickbooks: Link2,
  aliases: ArrowLeftRight,
  tolerances: SlidersHorizontal,
  users: Users,
  audit: History,
};

function Shell({ children }: { children: ReactNode }) {
  const { me, role, can, offline } = useSession();
  const location = useLocation();
  const qbo = useQuery({
    queryKey: ["qbo", "connection"],
    queryFn: () => get<QboConnection>("/api/v1/qbo/connection"),
    enabled: !!me?.active_tenant_id,
    staleTime: 30_000,
  });
  const pending = useQuery({
    queryKey: ["approvals", "pending"],
    queryFn: () => get<Page<Approval>>("/api/v1/approvals?status=pending"),
    enabled: can("approve"),
    refetchInterval: 30_000,
  });
  const open = useQuery({
    queryKey: ["exceptions", "open-count"],
    queryFn: () => get<ExceptionPage>("/api/v1/exceptions?limit=1&status=open"),
    enabled: !!me?.active_tenant_id,
    refetchInterval: 30_000,
  });
  const [collapsed, setCollapsed] = useState(false); // in memory only: no browser storage (App-flow 4.3)
  const [navOpen, setNavOpen] = useState(false);
  const mainRef = useRef<HTMLElement>(null);
  useEffect(() => {
    window.scrollTo(0, 0);
    setNavOpen(false);
  }, [location.pathname]);
  const qboOk = qbo.data?.status === "connected";
  const openCount = Object.values(open.data?.type_counters ?? {}).reduce((a, b) => a + b, 0);
  const counts: Record<string, number> = { "/exceptions": openCount, "/approvals": pending.data?.items.length ?? 0 };
  const countWords: Record<string, string> = { "/exceptions": "open", "/approvals": "waiting" };
  const wide = /^\/invoices\/[^/]+(\/review)?$/.test(location.pathname);
  return (
    <div className={`shell ${collapsed ? "collapsed" : ""} ${navOpen ? "nav-open" : ""}`}>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <aside className="sidebar" aria-label="Sidebar">
        <div className="sidebar-head">
          <NavLink to="/" className="brand" aria-label="MatchDesk home">
            <img className="brand-mark" src="/favicon.svg" alt="" />
            <span className="brand-word">MatchDesk</span>
          </NavLink>
        </div>
        {me?.active_tenant_id && (
          <nav aria-label="Main">
            {NAV_GROUPS.map((g) => {
              const items = g.items.filter((n) => role && n.roles.includes(role));
              if (!items.length) return null;
              return (
                <div className="nav-group" key={g.label}>
                  <h2>{g.label}</h2>
                  <ul>
                    {items.map((n) => {
                      const I = NAV_ICONS[n.icon ?? ""] ?? FileText;
                      const c = counts[n.to] ?? 0;
                      const descId = `nav-count-${n.icon}`;
                      return (
                        <li key={n.to}>
                          <NavLink to={n.to} className="nav-link" aria-describedby={c > 0 ? descId : undefined} title={collapsed ? n.label : undefined}>
                            <I size={17} aria-hidden="true" />
                            <span className="label">{n.label}</span>
                            {c > 0 && (
                              <>
                                <span className={`nav-count ${n.to === "/approvals" ? "alert" : ""}`} aria-hidden="true">
                                  {c}
                                </span>
                                <span className="sr-only" id={descId}>
                                  {c} {countWords[n.to]}
                                </span>
                              </>
                            )}
                          </NavLink>
                        </li>
                      );
                    })}
                  </ul>
                </div>
              );
            })}
          </nav>
        )}
        <div className="sidebar-foot">
          <button className="btn ghost small collapse-toggle" aria-pressed={collapsed} onClick={() => setCollapsed((c) => !c)} aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}>
            {collapsed ? <PanelLeftOpen size={16} aria-hidden="true" /> : <PanelLeftClose size={16} aria-hidden="true" />}
            <span className="label">Collapse</span>
          </button>
        </div>
      </aside>
      <div className="scrim" onClick={() => setNavOpen(false)} aria-hidden="true" />
      <div className="workspace">
        <header className="topbar">
          <button className="btn ghost icon-btn menu-toggle" aria-label="Open navigation" aria-expanded={navOpen} onClick={() => setNavOpen((o) => !o)}>
            <Menu size={18} aria-hidden="true" />
          </button>
          <div className="company">
            <Building2 size={16} aria-hidden="true" className="muted" />
            <TenantSwitcher />
          </div>
          <div className="spacer" />
          {me?.active_tenant_id && <PeriodPicker />}
          {me?.active_tenant_id && (
            <NavLink to="/settings/quickbooks" className="qbo-status" aria-label={qboOk ? "QuickBooks connected" : qbo.data ? "QuickBooks not connected" : "QuickBooks"}>
              <span className={`dot ${qboOk ? "ok" : qbo.data ? "bad" : ""}`} aria-hidden="true" />
              <span className="label">{qboOk ? "QuickBooks connected" : qbo.data ? "QuickBooks not connected" : "QuickBooks"}</span>
            </NavLink>
          )}
          <UserMenu />
        </header>
        {offline && (
          <div className="offline-banner" role="alert">
            <WifiOff size={16} aria-hidden="true" />
            <p>Connection lost. Uploaded files and saved work are safe. Trying again…</p>
          </div>
        )}
        <main id="main" ref={mainRef} tabIndex={-1} className={wide ? "wide" : undefined}>
          <PageErrorBoundary resetKey={location.pathname}>{children}</PageErrorBoundary>
        </main>
      </div>
      <IdleGuard />
    </div>
  );
}

function PeriodPicker() {
  const { month, setMonth } = usePeriod();
  return (
    <label className="period">
      <CalendarDays size={16} aria-hidden="true" />
      <span className="lbl">Period</span>
      <input type="month" aria-label="Period" value={month} onChange={(e) => setMonth(e.target.value)} />
    </label>
  );
}

function TenantSwitcher() {
  const { me, tenantName, signedIn } = useSession();
  const navigate = useNavigate();
  if (!me || me.memberships.length < 2) return <span className="account">{tenantName ?? "MatchDesk operator"}</span>;
  return (
    <select
      aria-label="Account"
      value={me.active_tenant_id ?? ""}
      onChange={async (e) => {
        const fresh = await send<typeof me>("PUT", "/api/v1/me/active-tenant", { tenant_id: e.target.value });
        signedIn(fresh);
        navigate("/", { replace: true });
      }}
    >
      {me.memberships.map((m) => (
        <option key={m.tenant_id} value={m.tenant_id}>
          {m.tenant_name}
        </option>
      ))}
    </select>
  );
}

function initials(name: string): string {
  const parts = name.replace(/@.*/, "").split(/[\s._-]+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase() || "?";
}

function UserMenu() {
  const { me, role, signOut } = useSession();
  const { enabled, setEnabled } = useShortcuts();
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const wrap = useRef<HTMLDivElement>(null);
  const [theme, setTheme] = useState<string>(document.documentElement.dataset.theme ?? "system");
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (!wrap.current?.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);
  useEffect(() => {
    if (theme === "system") delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = theme;
  }, [theme]);
  if (!me) return null;
  const name = me.user.display_name || me.user.email;
  return (
    <div className="menu-wrap" ref={wrap}>
      <button className="user-button" aria-expanded={open} aria-haspopup="true" onClick={() => setOpen((o) => !o)}>
        <span className="avatar" aria-hidden="true">
          {initials(name)}
        </span>
        <span className="uname">{name}</span>
        <ChevronDown size={14} aria-hidden="true" className="muted" />
      </button>
      {open && (
        <div className="menu">
          <div className="who">
            <strong>{me.user.display_name}</strong>
            <div className="muted small">{me.user.email}</div>
            <div className="muted small">{role ? role.charAt(0).toUpperCase() + role.slice(1) : "Operator"}</div>
          </div>
          <label>
            <span>Single-key shortcuts (J, K, X, Enter)</span>
            <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
          </label>
          <label>
            Theme
            <select value={theme} onChange={(e) => setTheme(e.target.value)} aria-label="Theme">
              <option value="system">Same as device</option>
              <option value="light">Light</option>
              <option value="dark">Dark</option>
            </select>
          </label>
          <hr />
          <a href="mailto:support@matchdesk.invalid">
            <LifeBuoy size={16} aria-hidden="true" />
            Help and contact
          </a>
          <button
            onClick={async () => {
              setOpen(false);
              // Leave the signed-in routes first, so they do not redirect to sign-in meanwhile.
              navigate("/signed-out", { replace: true });
              await signOut();
            }}
          >
            <LogOut size={16} aria-hidden="true" />
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}

/** Two minutes before the 60-minute idle limit, ask; "Stay signed in" resets the server timer. */
function IdleGuard() {
  const { signOut, me } = useSession();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [warn, setWarn] = useState(false);
  useEffect(() => {
    const IDLE = 60 * 60_000;
    const t = window.setInterval(() => {
      const left = lastServerContact() + IDLE - Date.now();
      if (left <= 0) {
        window.clearInterval(t);
        navigate(`/signed-out?expired=1&next=${encodeURIComponent(location.pathname + location.search)}`);
        void signOut(); // ends the server session and clears every cached read (review W8)
      } else if (left <= 2 * 60_000) setWarn(true);
    }, 5_000);
    return () => window.clearInterval(t);
  }, [navigate, qc, me, signOut]);
  return (
    <Dialog
      open={warn}
      title="Stay signed in?"
      onClose={() => setWarn(false)}
      footer={
        <>
          <button
            className="btn"
            onClick={async () => {
              setWarn(false);
              navigate("/signed-out");
              await signOut();
            }}
          >
            Sign out now
          </button>
          <button
            className="btn primary"
            data-safe
            onClick={async () => {
              await send("POST", "/api/v1/auth/session/extend");
              setWarn(false);
            }}
          >
            Stay signed in
          </button>
        </>
      }
    >
      <p role="alert">You will be signed out in 2 minutes because there has been no activity. Stay signed in?</p>
    </Dialog>
  );
}
