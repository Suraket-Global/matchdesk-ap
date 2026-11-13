// Shapes of the B3/B4 API responses the screens read (TRD section 12). Money and quantities are strings.

export interface Me {
  user: { id: string; email: string; display_name: string | null; is_operator: boolean };
  memberships: { tenant_id: string; role: string; tenant_name: string }[];
  active_tenant_id: string | null;
  role: string | null;
  /** Set while an operator reads an account under a support grant (B7, S-18). */
  support?: { grant_id: string; tenant_name: string | null; ends_at: string | null } | null;
  idle_expires_at: string;
  absolute_expires_at: string;
  csrf_token: string;
}

export interface Page<T> {
  items: T[];
  next_cursor?: string | null;
}

export interface QboConnection {
  status: string;
  company_name: string | null;
  realm_id: string | null;
  scopes_granted: string | null;
  last_success_at: string | null;
  delete_after: string | null;
  version: number;
  mode?: string;
  /** B8: "demo_data" in recorded-response mode; the header and S-04 say so. */
  source?: "demo_data" | "intuit";
  /** B11: for an account in Intuit mode, which Intuit environment the server reads. */
  intuit_environment?: "sandbox" | "production" | null;
  last_sync?: {
    state: string;
    finished_at: string | null;
    error_code: string | null;
    started_at: string | null;
    skipped_currency?: { entity: string; currency: string; count: number }[];
    home_currency?: string | null;
  } | null;
}

export interface SyncRun {
  id: string;
  state: string;
  /** B11-1: documents not stored because their currency is not the account's. */
  skipped_currency?: { entity: string; currency: string; count: number }[];
  home_currency?: string | null;
  [k: string]: unknown;
}

export interface ExceptionItem {
  id: string;
  invoice_id: string;
  invoice_line_id: string | null;
  type: string;
  sub_reason: string | null;
  status: string;
  value_class: string;
  qualifying: boolean;
  resolution_code: string | null;
  resolution_note: string | null;
  resolved_by: string | null;
  variance_qty: string | null;
  variance_amount: string | null;
  reported_amount: string | null;
  possibly_credited: boolean;
  label: string | null;
  allowed_codes: string[];
  assigned_to?: string | null;
  assigned_to_name?: string | null;
  credit_decision?: "credited" | "not_credited" | null;
  credit_bill?: { doc_number: string | null; txn_date: string | null; total: string | null } | null;
  stale: boolean | null;
  version: number;
  vendor_id?: string | null;
  vendor_name?: string | null;
  doc_number?: string | null;
  doc_type?: string | null;
  doc_date?: string | null;
  po_number?: string | null;
  line_no?: number | null;
  supplier_item_code?: string | null;
  description?: string | null;
  line_amount?: string | null;
  raised_at?: string;
  resolved_at?: string | null;
}

export interface ExceptionPage extends Page<ExceptionItem> {
  counters: Record<string, number>;
  type_counters: Record<string, number>;
  /** B8: count and value of the whole filtered set, not of the rows loaded so far. */
  total_count: number;
  total_value: string;
}

export interface Neighbour {
  id: string;
  invoice_id: string;
  invoice_line_id: string | null;
  doc_number: string | null;
  type: string;
}

export interface Neighbours {
  previous: Neighbour | null;
  next: Neighbour | null;
  position: number | null;
  total: number;
}

/** B8: why a period's figures can or cannot be read (empty versus zero). */
export type MeasurementState = "awaiting_invoices" | "awaiting_receiving" | "no_receiving_records" | "processing" | "measured" | "unavailable";

/** States whose coverage figures are measured values (B9: with the declaration 0 % is measured). */
export const FIGURE_STATES: MeasurementState[] = ["measured", "no_receiving_records"];

export interface NoReceivingDeclaration {
  id: string;
  statement: string;
  declared_by: string;
  declared_by_name: string | null;
  declared_at: string;
}

export interface InvoiceSummary {
  id: string;
  document_id: string;
  doc_type: string;
  doc_number: string | null;
  doc_date: string | null;
  vendor_id: string | null;
  vendor_name: string | null;
  po_number: string | null;
  total: string | null;
  verification_status: string;
  document_state: string | null;
  displayed_state: string | null;
  version: number;
}

export interface Receipt {
  id: string;
  received_date: string;
  qty: string;
  source_file: string;
  source_row: number;
  receiving_import_id: string;
  evidence_class: string;
  evidence_words: string;
  receiver_ref: string | null;
  counts: boolean;
  not_counted_reason: string | null;
}

export interface HistoryDoc {
  invoice_id: string | null;
  doc_type: string;
  doc_number: string | null;
  doc_date: string | null;
  qty: string | null;
  source: "document" | "qbo_bill";
}

export interface Tolerance {
  id: string | null;
  vendor_id: string | null;
  is_default_rule_set?: boolean;
  qty_tolerance: string;
  price_tol_abs: string;
  price_tol_pct: string;
  charge_allowance: string;
  valid_from?: string;
  valid_to?: string | null;
}

export interface InvoiceLine {
  id: string;
  line_no: number;
  status: string | null;
  result_status: string | null;
  stale: boolean;
  supplier_item_code: string | null;
  description: string | null;
  qty: string | null;
  uom: string | null;
  unit_price: string | null;
  amount: string | null;
  line_kind: string;
  page_no: number | null;
  match: null | {
    line_kind: string;
    qty_ordered: string | null;
    qty_received_cum: string | null;
    qty_invoiced_cum_net: string | null;
    qty_invoiced_prior_qbo: string | null;
    receipt_line_count: number;
    covered: boolean | null;
    po_unit_price: string | null;
    invoice_unit_price_po_uom: string | null;
    calculation: string;
  };
  purchase_order?: null | {
    id: string;
    po_number: string;
    line_id: string;
    line_no: number | null;
    description: string | null;
    item_sku: string | null;
    item_name: string | null;
    qty_ordered: string;
    uom: string | null;
    unit_price: string;
    qbo_billed_qty: string | null;
  };
  alias?: null | {
    id: string;
    supplier_item_code: string;
    conversion_factor: string;
    supplier_uom: string | null;
    item_uom: string | null;
    status: string;
  };
  tolerance?: Tolerance;
  receipts?: Receipt[];
  history?: HistoryDoc[];
}

export interface FieldSource {
  source: "read" | "edited";
  original?: unknown;
  by?: string;
  at?: string;
}

export interface ReviewLine {
  line_no: number;
  id: string;
  supplier_item_code: string | null;
  description: string | null;
  qty: string | null;
  uom: string | null;
  unit_price: string | null;
  amount: string | null;
  line_kind: string;
  page_no: number | null;
  field_sources: Record<string, FieldSource>;
}

export interface Review {
  document_id: string;
  document_state: string;
  verification_status: string;
  verification: Record<string, boolean>;
  fields: Record<string, string | null>;
  vendor_name_read: string | null;
  purchase_order_id: string | null;
  field_sources: Record<string, FieldSource>;
  review_draft: null | { fields?: Record<string, unknown>; lines?: Record<string, unknown>[]; saved_at?: string; by?: string };
  confirmed_by: string | null;
  confirmed_at: string | null;
  line_fields: ReviewLine[];
  removed_lines?: (ReviewLine & { removed_by: string | null; removed_at: string | null; removed_reason: string | null })[];
  next_line_no?: number;
  inconsistent_note?: string | null;
  version: number;
  failed_checks?: string[];
  [k: string]: unknown;
}

export interface InvoiceDetail {
  id: string;
  document_id: string;
  vendor_id: string | null;
  vendor_name: string | null;
  purchase_order_id: string | null;
  po_number: string | null;
  total: string | null;
  verification_status: string;
  qbo_bill: null | { doc_number: string; paid_status: string; balance: string };
  stale: boolean;
  doc_type: string;
  doc_number: string | null;
  doc_date: string | null;
  version: number;
  review: Review;
  lines: InvoiceLine[];
  exceptions: ExceptionItem[];
  /** B12: set when a person deleted the document; it is then history only. */
  removed?: { removed_at: string; removed_by_name: string | null; reason: string | null } | null;
}

/** B12: what deleting one document needs (GET /documents/{id}/deletion). */
export interface DocumentDeletionRule {
  accepted: boolean;
  needs_controller: boolean;
  reason_required: boolean;
  blocked: string | null;
  removed_at: string | null;
  removed_reason: string | null;
}

export interface DocumentDeletionResult {
  document_id: string;
  removed_at: string;
  reason: string | null;
  invoice_ids: string[];
  results_retired: number;
  exceptions_closed: number;
  approvals_withdrawn: number;
  match_run_id: string | null;
}

/** B12: the account's billable units by month (GET /usage), the operator's figures without a price. */
export interface UsageMonth {
  month: string;
  invoice: number;
  credit_note: number;
  units: number;
}

export interface Usage {
  items: UsageMonth[];
  total_units: number;
  unit: string;
}

export interface BatchTotals {
  queued: number;
  processing: number;
  ready: number;
  "needs review": number;
  failed: number;
  "duplicate file": number;
  /** B12: files a person deleted; counted here only, so the counts still add up. */
  deleted?: number;
  file_count: number;
}

export interface Batch {
  id: string;
  source?: string;
  file_count?: number;
  created_at: string;
  totals: BatchTotals;
  files?: BatchFile[];
}

export interface BatchFile {
  id: string;
  state: string;
  displayed_state: string;
  failure_code: string | null;
  byte_size: number;
  mime_type: string;
  duplicate_of_document_id: string | null;
  duplicate_of_invoice_id?: string | null;
  original_name: string | null;
  removed_at?: string | null;
  removed_reason?: string | null;
  invoices: { id: string; doc_type: string; doc_number: string | null; vendor_name: string | null; verification_status: string }[];
}

export interface ReceivingImport {
  id: string;
  source_type: string;
  evidence_class: string;
  state: string;
  state_version: number;
  kept_by_name: string | null;
  declared_complete: boolean;
  coverage_start: string | null;
  coverage_end: string | null;
  column_map: Record<string, string> | null;
  rows_total: number | null;
  rows_valid: number | null;
  rows_rejected: number | null;
  late_lines_waiting?: number;
  rejected_rows: { row: number; reason: string; [k: string]: unknown }[] | null;
  committed_at: string | null;
  voided_at: string | null;
  void_reason: string | null;
  counts_as_evidence: boolean;
  file_name?: string | null;
  created_at?: string;
  preview?: { headers: string[]; sample_rows: (string | null)[][]; rows_total: number; applied_mapping?: SavedMapping | null };
  mapping_id?: string | null;
  expires_at?: string | null;
  validation?: { rows_total: number; rows_valid: number; rows_rejected: number; rejected_rows: { row: number; reason: string; value?: unknown }[] };
  receipts?: {
    id: string;
    purchase_order_id: string;
    po_number: string | null;
    received_date: string;
    receiver_ref: string | null;
    receiver_marks_present: boolean | null;
    receiver_name: string | null;
    version: number;
    lines: { id: string; po_line_id: string; po_line_no?: number | null; uom?: string | null; qty_received: string; source_row: number; added_after_exception: boolean; late_approved: boolean }[];
  }[];
  late_lines?: number;
  match_run_id?: string | null;
}

export interface SavedMapping {
  id: string;
  name: string;
  columns: Record<string, string>;
  created_at: string;
}

export interface Alias {
  id: string;
  vendor_id: string;
  vendor_name?: string | null;
  supplier_item_code: string;
  supplier_description: string | null;
  item_id: string;
  item_sku?: string | null;
  item_name?: string | null;
  supplier_uom: string | null;
  item_uom: string | null;
  conversion_factor: string;
  status: string;
  approved_by: string | null;
  approved_by_name?: string | null;
  reviewed_at?: string | null;
  created_by_name?: string | null;
  valid_from: string | null;
  valid_to: string | null;
  retire_reason: string | null;
  version: number;
}

export interface Approval {
  id: string;
  subject_type: string;
  exception_id: string | null;
  alias_id: string | null;
  receiving_import_id: string | null;
  reason: string | null;
  amount: string | null;
  requested_by: string;
  requested_by_name?: string | null;
  requested_at?: string;
  status: string;
  decided_by: string | null;
  decided_by_name?: string | null;
  decision_note: string | null;
  self_approved: boolean;
  version: number;
  exception?: ExceptionItem;
  alias?: Alias;
  /** B8: the invoice lines a conversion re-matches. */
  affected?: AffectedLine[];
  /** B9: late receiving evidence: the exceptions open now on its purchase-order lines. */
  would_clear?: { id: string; invoice_id: string; invoice_line_id: string | null; type: string; doc_number: string | null; line_no: number | null; value: string }[];
}

export interface AffectedLine {
  invoice_id: string;
  invoice_line_id: string;
  doc_number: string | null;
  doc_date: string | null;
  line_no: number;
  qty: string | null;
  uom: string | null;
  converted_qty: string | null;
  open_exceptions: string[];
}

export interface ReportSection {
  count: number;
  amount: string;
}

export interface Report {
  id: string;
  period_start: string;
  period_end: string;
  version_no: number;
  status: string;
  data_cutoff_at: string;
  totals: {
    sections: Record<string, ReportSection>;
    documents: number;
    item_lines: number;
    paid_split: Record<string, string>;
    stale_lines: number;
    lines_matched: number;
    lines_evaluated: number;
    qualifying_amount: string;
    [k: string]: unknown;
  };
  history_read_from: string | null;
  receipt_coverage_pct: string;
  coverage_class_a_pct: string;
  coverage_class_b_pct: string;
  class_c_only_lines: number;
  findings_amount: string;
  not_received_amount: string;
  unverified_amount: string;
  qualifying_amount: string;
  is_stale: boolean;
  changed_since_cutoff?: boolean | null;
  flagged_amount?: string;
  approved_by: string | null;
  approved_at: string | null;
  draft_mark: string | null;
  blocking?: string[];
  findings?: {
    id: string;
    exception_id: string;
    section: string;
    type: string;
    amount: string;
    qualifying: boolean;
    paid_status: string;
    snapshot: Record<string, unknown>;
  }[];
}

export interface Refund {
  report_id: string;
  report_status: string;
  threshold: string;
  qualifying_total: string;
  unverified_total: string;
  refund_due: boolean;
}

export interface UserRow {
  membership_id: string;
  user_id: string;
  email: string;
  display_name: string | null;
  role: string;
  status: string;
  last_sign_in_at?: string | null;
}

export interface Invitation {
  id: string;
  email: string;
  role: string;
  expires_at?: string;
  [k: string]: unknown;
}

export interface AuditEvent {
  id: string;
  occurred_at: string;
  actor_type: string;
  actor_user_id: string | null;
  actor_name: string | null;
  action: string;
  entity_type: string;
  entity_id: string | null;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
}

export interface PurchaseOrder {
  id: string;
  po_number: string;
  vendor_id: string;
  vendor_name: string | null;
  txn_date: string;
  qbo_status: string | null;
  total: string | null;
  invoice_count?: number;
  lines?: {
    id: string;
    line_no: number | null;
    description: string | null;
    item_id: string | null;
    qty_ordered: string;
    uom: string | null;
    unit_price: string;
    amount: string | null;
    charge_kind: string | null;
    qty_received_counting: string;
    counting_receipt_lines: number;
    removed_at?: string | null;
  }[];
  /** B11: why QuickBooks history on this PO is unknown; its lines are history_incomplete. */
  history_unknown?: string[];
  changed_in_quickbooks?: null | {
    detected_at: string;
    rematched_at: string | null;
    changes: {
      po_line_id: string;
      line_no: number | null;
      change: "changed" | "removed";
      before: Record<string, string | number | null>;
      after: Record<string, string | number | null> | null;
    }[];
  };
}

export interface Vendor {
  id: string;
  name: string;
  active: boolean;
}

export interface Item {
  id: string;
  sku: string | null;
  name: string;
  purchase_uom: string | null;
}

export interface Coverage {
  period_start: string;
  period_end: string;
  item_lines: number;
  documents?: number;
  documents_in_review?: number;
  state?: MeasurementState;
  receipt_coverage_pct: string | null;
  coverage_class_a_pct: string | null;
  coverage_class_b_pct: string | null;
  no_receiving_declaration?: NoReceivingDeclaration | null;
  /** B10: the server's measurement words for these dates. */
  measurement?: Measurement;
}

// ---------------------------------------------------------------- B9
export interface Member {
  user_id: string;
  name: string | null;
  role: string;
}

export interface OutcomeRecord {
  amount: string;
  recorded_by: string;
  recorded_by_name: string | null;
  recorded_at: string;
  credit_document_id: string | null;
  credit_reference: string | null;
  note: string | null;
}

export interface OutcomeCounts {
  flagged: ReportSection;
  controller_confirmed: ReportSection;
  credit_recovered: ReportSection;
}

export interface Outcomes {
  is_governing: boolean;
  totals: OutcomeCounts;
  by_finding: Record<string, { controller_confirmed?: OutcomeRecord; credit_recovered?: OutcomeRecord }>;
}

export interface ArchiveExport {
  id: string;
  status: "queued" | "running" | "ready" | "incomplete" | "failed" | "expired";
  requested_at: string;
  finished_at: string | null;
  expires_at: string | null;
  file_count: number | null;
  byte_size: number | null;
  downloadable: boolean;
  /** B10: every original read into the ZIP (expected = included, nothing missing). */
  complete: boolean;
  expected_count: number | null;
  included_count: number | null;
  missing_count: number | null;
}

/** B10: the latest verified archive as the deletion dialog and the operator's row show it. */
export interface ArchiveSnapshot {
  state: "none" | "complete" | "incomplete" | "failed" | "expired";
  included: number | null;
  expected: number | null;
  checked_at: string | null;
  acknowledged?: boolean;
}

export interface DeletionRequest {
  id: string;
  tenant_id: string;
  tenant_name?: string | null;
  status: "requested" | "scheduled" | "deleting" | "declined" | "cancelled" | "executed";
  reason: string | null;
  requested_by: string;
  requested_by_name?: string | null;
  requested_at: string;
  decided_at: string | null;
  decision_note: string | null;
  delete_after: string | null;
  claimed_at?: string | null;
  cancelled_at?: string | null;
  cancellable?: boolean;
  archive?: ArchiveSnapshot;
  version: number;
}

// ---------------------------------------------------------------- B7
export interface Pilot {
  id: string;
  price: string;
  period_start: string;
  period_end: string;
  refund_condition: string;
  refund_threshold: string;
  signed_terms_ref: string | null;
  signed_by_name: string | null;
  signed_by_role: string | null;
  delivery_mode: string;
  governing_report_id: string | null;
  refund_determined_at: string | null;
  refund_qualifying_amount: string | null;
  refund_due: boolean | null;
  payment_status: string;
  outcome: string | null;
  version: number;
}

export interface PilotRead {
  pilot: Pilot | null;
  governing: { report_id: string; period_start: string; period_end: string; version_no: number } | null;
}

export interface WeeklyRow {
  vendor_id: string | null;
  vendor_name: string | null;
  documents: number;
  lines: number;
  lines_matched: number;
  pass_rate_pct: string | null;
  open_count: number;
  open_value: string;
  flagged_amount: string;
}

export interface Weekly {
  week_start: string;
  week_end: string;
  state?: MeasurementState;
  /** B10: the one measurement rule shared with the email and the exports. */
  measurement?: Measurement;
  suppliers: WeeklyRow[];
  total: Omit<WeeklyRow, "vendor_id" | "vendor_name">;
  sent: WeeklyRun[];
}

export interface Measurement {
  state: MeasurementState;
  figures: boolean;
  title: string | null;
  text: string | null;
}

/** B10: one weekly email run and its delivery per recipient. */
export interface WeeklyRun {
  week_start: string;
  trigger: string;
  recipients: number;
  asked_at?: string | null;
  sent_at: string | null;
  delivered?: number;
  failed?: number;
  pending?: number;
  deliveries?: { recipient: string; state: "pending" | "sent" | "failed"; attempts: number; error: string | null }[];
}

/** B10: a scheduled operation of the worker on S-18. */
export interface ScheduledOperation {
  name: string;
  label: string;
  state: "ok" | "late" | "failing";
  last_success_at: string | null;
  last_failure_at: string | null;
  last_error: string | null;
  consecutive_failures: number;
}

export interface SupportGrant {
  id: string;
  tenant_id: string;
  status: string;
  reason: string;
  hours_requested: number;
  requested_by_name: string | null;
  requested_at: string | null;
  granted_by_name: string | null;
  starts_at: string | null;
  ends_at: string | null;
  ended_early_at: string | null;
}

export interface OperatorTenant {
  id: string;
  name: string;
  status: string;
  created_at: string;
  intake_address: string | null;
  pilot: Pilot | null;
  usage_units: number;
  active_grant: boolean;
  pending_requests: number;
  usage?: { month: string; invoice: number; credit_note: number; units: number }[];
  grants?: SupportGrant[];
}

export interface IntakeEmail {
  address: string | null;
  provider: string;
  senders: { id: string; address_or_domain: string }[];
  messages: {
    id: string;
    from_address: string;
    subject: string | null;
    attachment_count: number;
    received_at: string;
    status: string;
    batch_id: string | null;
  }[];
}
