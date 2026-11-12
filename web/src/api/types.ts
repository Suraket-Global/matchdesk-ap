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
}

export interface SyncRun {
  id: string;
  state: string;
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
}

export interface BatchTotals {
  queued: number;
  processing: number;
  ready: number;
  "needs review": number;
  failed: number;
  "duplicate file": number;
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
  preview?: { headers: string[]; sample_rows: (string | null)[][]; rows_total: number };
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
  }[];
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
  receipt_coverage_pct: string | null;
  coverage_class_a_pct: string | null;
  coverage_class_b_pct: string | null;
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
  suppliers: WeeklyRow[];
  total: Omit<WeeklyRow, "vendor_id" | "vendor_name">;
  sent: { week_start: string; trigger: string; recipients: number; sent_at: string }[];
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
