// Audit log in words (B6 review M7): record names, action names and values a person can read.
import { day, when } from "./format";

const ENTITY: Record<string, string> = {
  approval: "Approval",
  backtest_report: "Back-test report",
  document: "Document",
  exception: "Exception",
  invitation: "Invitation",
  invoice: "Invoice",
  item_alias: "Alias",
  match_run: "Match run",
  membership: "Membership",
  qbo_connection: "QuickBooks connection",
  receipt: "Delivery document",
  receiving_attestation: "Receiving attestation",
  receiving_import: "Receiving import",
  sync_run: "QuickBooks read",
  tenant: "Account",
  tolerance_rule: "Tolerance",
  user: "User",
  pilot_engagement: "Pilot record",
  support_grant: "Support access",
  inbound_message: "Emailed invoice",
  intake_sender: "Allowed sender",
  weekly_summary: "Weekly summary",
};

const ACTION: Record<string, string> = {
  "alias.created": "Alias created",
  "alias.retired": "Alias retired",
  "aliases.reviewed": "Aliases marked reviewed",
  "approval.requested": "Approval requested",
  "approval.withdrawn_by_rematch": "Approval withdrawn by a re-match",
  "exception.reopened": "Exception reopened",
  "exception.resolved": "Exception resolved",
  "exception.waiver_requested": "Waiver sent for approval",
  invitation_accepted: "Invitation accepted",
  invitation_created: "Invitation sent",
  invitation_revoked: "Invitation revoked",
  "invoice.confirmed": "Extraction confirmed",
  "invoice.corrected": "Extraction corrected",
  "match_run.stored": "Match results stored",
  membership_changed: "Role or access changed",
  "qbo.connected": "QuickBooks connected",
  "qbo.disconnected": "QuickBooks disconnected",
  "qbo.needs_reconnect": "QuickBooks needs reconnecting",
  "qbo.sync_succeeded": "QuickBooks read finished",
  "receiving.attested": "Receiving evidence attested",
  "receiving.committed": "Receiving file imported",
  "receiving.declared": "Receiving file declared",
  "receiving.receipt_confirmed": "Delivery document confirmed",
  "receiving.uploaded": "Receiving file uploaded",
  "receiving.voided": "Receiving import voided",
  "report.approved": "Report approved",
  "report.drafted": "Report draft created",
  sign_in: "Signed in",
  "tolerance.changed": "Tolerance changed",
  "waiver_limits.changed": "Waiver limits changed",
  "pilot.created": "Pilot record created",
  "pilot.updated": "Pilot record changed",
  "support_grant.requested": "Support access requested",
  "support_grant.granted": "Support access granted",
  "support_grant.ended": "Support access ended",
  "support_grant.entered": "Operator opened the account",
  "intake_email.held": "Emailed invoice held",
  "intake_email.processed": "Emailed invoice accepted",
  "intake_email.released": "Held email released",
  "intake_email.discarded": "Held email discarded",
  "intake_sender.added": "Allowed sender added",
  "intake_sender.removed": "Allowed sender removed",
  "weekly_summary.sent": "Weekly summary emailed",
};

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const UUID_IN = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi;

export function entityWord(t: string): string {
  return ENTITY[t] ?? sentence(t);
}

export function actionWord(a: string): string {
  return ACTION[a] ?? sentence(a);
}

function sentence(code: string): string {
  const s = code.replace(/[._]/g, " ").trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function keyWord(k: string): string {
  return sentence(k).replace(/\bqbo\b/i, "QuickBooks").replace(/\bpo\b/i, "PO").replace(/\bid\b/i, "").trim();
}

/** One value as words: records are counted, never shown as identifiers. */
export function valueWord(v: unknown): string {
  if (v === null || v === undefined || v === "") return "none";
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (typeof v === "number") return String(v);
  if (typeof v === "string") {
    if (UUID.test(v)) return "a record";
    if (/^\d{4}-\d{2}-\d{2}$/.test(v)) return day(v);
    if (/^\d{4}-\d{2}-\d{2}T/.test(v)) return when(v);
    if (/^[a-z]+(_[a-z]+)+$/.test(v)) return sentence(v).toLowerCase();
    return v.replace(UUID_IN, "…");
  }
  if (Array.isArray(v)) {
    if (v.length === 0) return "none";
    if (v.every((x) => typeof x === "string" && UUID.test(x))) return v.length === 1 ? "1 record" : `${v.length} records`;
    if (v.every((x) => typeof x !== "object" || x === null)) return v.map(valueWord).join(", ");
    return v.length === 1 ? "1 entry" : `${v.length} entries`;
  }
  const n = Object.keys(v as object).length;
  return n === 1 ? "1 value" : `${n} values`;
}

export interface Change {
  key: string;
  label: string;
  before: string | null;
  after: string | null;
}

/** Field-by-field changes: "before → after", or the value alone when there was no before. */
export function changes(before: Record<string, unknown> | null, after: Record<string, unknown> | null): Change[] {
  const keys = [...new Set([...Object.keys(before ?? {}), ...Object.keys(after ?? {})])];
  return keys
    .map((k) => ({
      key: k,
      label: keyWord(k) || "Record",
      before: before && k in before ? valueWord(before[k]) : null,
      after: after && k in after ? valueWord(after[k]) : null,
    }))
    .filter((c) => c.before !== c.after);
}
