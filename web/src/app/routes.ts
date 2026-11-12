// One route table: navigation, breadcrumbs and links are built from it (App-flow.md section 6).
export interface NavItem {
  to: string;
  label: string;
  roles: string[];
}

const ALL = ["controller", "clerk", "viewer", "support_reader"];

export const NAV: NavItem[] = [
  { to: "/exceptions", label: "Exceptions", roles: ALL },
  { to: "/invoices", label: "Invoices", roles: ALL },
  { to: "/intake", label: "Intake", roles: ALL },
  { to: "/receiving", label: "Receiving", roles: ALL },
  { to: "/aliases", label: "Aliases", roles: ["controller", "clerk"] },
  { to: "/reports", label: "Reports", roles: ALL },
  { to: "/approvals", label: "Approvals", roles: ["controller"] },
  { to: "/settings", label: "Settings", roles: ALL },
];

export const SETTINGS_NAV: NavItem[] = [
  { to: "/onboarding", label: "Onboarding checklist", roles: ALL },
  { to: "/settings/quickbooks", label: "QuickBooks connection", roles: ALL },
  { to: "/settings/tolerances", label: "Tolerances", roles: ALL },
  { to: "/settings/users", label: "Users and support access", roles: ["controller"] },
  { to: "/audit", label: "Audit log", roles: ["controller", "support_reader"] },
];

export const ROUTE_PATHS = [
  "/login",
  "/login/verify",
  "/invite",
  "/onboarding",
  "/settings/quickbooks",
  "/receiving",
  "/receiving/imports/:importId",
  "/intake",
  "/intake/batches/:batchId",
  "/invoices/:invoiceId/review",
  "/exceptions",
  "/invoices",
  "/invoices/:invoiceId",
  "/purchase-orders/:poId",
  "/aliases",
  "/approvals",
  "/reports",
  "/reports/backtest/:reportId",
  "/reports/weekly",
  "/settings/tolerances",
  "/settings/users",
  "/audit",
  "/operator/tenants",
  "/operator/tenants/:tenantId",
  "/signed-out",
  "/forbidden",
];
