// One word per thing (design.md section 9). Exception types, statuses and resolution codes as
// the people using the screens say them.

export const EXCEPTION_TYPES: Record<string, string> = {
  receipt_absent: "Receipt absent",
  qty_over_received: "Invoiced above received",
  qty_over_ordered: "Invoiced above ordered",
  price_variance: "Price variance",
  duplicate: "Duplicate",
  possible_duplicate: "Possible duplicate",
  no_po: "No purchase order",
  alias_unconfirmed: "Alias not confirmed",
  po_line_not_found: "PO line not found",
  uom_unresolved: "Unit not converted",
  history_incomplete: "History incomplete",
  unmatched_charge: "Charge not on the PO",
  credit_unlinked: "Credit note not linked",
  extraction_unverified: "Extraction not confirmed",
  currency_unsupported: "Currency not supported",
};

export const SUB_REASONS: Record<string, string> = {
  not_received: "Not received: your log covers this order and shows nothing",
  supplier_slip_only: "Supplier slip only",
  no_evidence: "No receiving evidence",
  returned_no_credit: "Returned, credit not yet received",
};

export const EXCEPTION_STATUS: Record<string, string> = {
  open: "Exception",
  pending_approval: "Pending approval",
  resolved: "Resolved",
  waived: "Waived",
  auto_closed: "Closed by a re-match",
};

export const RESOLUTION_CODES: Record<string, string> = {
  confirmed_overbilling: "Confirmed overbilling",
  confirmed_short_shipment: "Confirmed short shipment",
  source_corrected: "Source corrected",
  waived: "Waive",
  confirmed_not_received: "Confirm not received",
  resolved_by_credit: "Resolved by a credit note",
  confirmed_duplicate: "Is a duplicate",
  not_a_duplicate: "Not a duplicate",
};

export const RESOLUTION_HINTS: Record<string, string> = {
  confirmed_overbilling: "The supplier billed more than is owed. It stays in the report as a finding.",
  confirmed_short_shipment: "Fewer goods came than were invoiced.",
  source_corrected: "The document or the receiving record was wrong and has been corrected.",
  waived: "Accept the difference. Needs a note; above the limit it goes to your controller.",
  confirmed_not_received: "Controller only: the goods never came.",
  resolved_by_credit: "A credit note covers the difference.",
  confirmed_duplicate: "This invoice was already billed.",
  not_a_duplicate: "A separate, genuine invoice.",
};

export const CONTROLLER_ONLY_CODES = new Set(["confirmed_not_received", "confirmed_duplicate", "not_a_duplicate"]);

export const VALUE_CLASS: Record<string, string> = {
  finding_candidate: "Finding",
  open_undecided: "Open",
  unverified: "Unverified",
  none: "No value",
};

export const DOC_STATES: Record<string, string> = {
  queued: "Queued",
  processing: "Processing",
  ready: "Ready",
  "needs review": "Needs review",
  failed: "Failed",
  "duplicate file": "Duplicate file",
};

export const FAILURE_CODES: Record<string, string> = {
  password_protected: "Password-protected PDF. Remove the password and upload it again.",
  too_many_pages: "More than 60 pages. Split the file and upload the parts.",
  unreadable: "This file could not be read. Check it opens, then upload it again.",
  not_supported: "Not a PDF or image.",
};

export const EVIDENCE_CLASSES: Record<string, { name: string; explain: string }> = {
  A: {
    name: "Warehouse record",
    explain: "Your warehouse's own receiving log, or QuickBooks item receipts entered by the receiver before the bill.",
  },
  B: {
    name: "Signed delivery document",
    explain: "A delivery document your receiver signed or marked with counts.",
  },
  C: {
    name: "Supplier document only",
    explain: "The supplier's packing slip with no receiver marks. Shown for reference; it never counts as a receipt.",
  },
};

export const ROLES: Record<string, string> = {
  controller: "Controller",
  clerk: "Clerk",
  viewer: "Viewer",
  operator: "Operator",
  support_reader: "Support (read only)",
};

export function typeWord(t: string): string {
  return EXCEPTION_TYPES[t] ?? t.replace(/_/g, " ");
}
