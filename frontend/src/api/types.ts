/**
 * Hand-written API types for the P5-01..P5-03 endpoints.
 *
 * TODO(P5-05): replace with openapi-typescript output from frontend/src/api/openapi.json
 * when the backend lands (`npx openapi-typescript src/api/openapi.json -o src/api/schema.d.ts`),
 * then re-export the generated component schemas under these names.
 *
 * Shapes mirror src/invoice_processing/schemas.py and codes.py. Money is always a decimal
 * string (Pydantic DecimalStr) and is rendered as-is; dates are ISO strings.
 */

// ---- Enums (codes.py) ----------------------------------------------------------------

export type ExecutionMode = "offline" | "live";

export type RunStatus =
  | "received"
  | "extracted"
  | "validated"
  | "approval_pending"
  | "approved"
  | "awaiting_human_approval"
  | "paid_mock"
  | "rejected"
  | "needs_review"
  | "failed"
  | "duplicate";

/** Current business state of one invoice identity (codes.InvoiceStatus). */
export type InvoiceStatus =
  | "processing"
  | "paid_mock"
  | "rejected"
  | "needs_review"
  | "awaiting_human_approval"
  | "failed"
  | "superseded";

/** Every outcome the status component can show. */
export type Outcome =
  | "paid_mock"
  | "rejected"
  | "needs_review"
  | "awaiting_human_approval"
  | "failed"
  | "duplicate"
  | "processing";

export type Severity = "info" | "warning" | "review" | "blocker";
export type Recommendation = "approve" | "reject" | "review";
export type GateOutcome = "approved" | "rejected" | "needs_review" | "awaiting_human_approval";
export type SourceFormat = "txt" | "json" | "csv" | "xml" | "pdf";
export type HumanReviewAction = "approve" | "decline";

/** codes.FindingCode; kept open so new backend codes do not break the client. */
export type FindingCode =
  | "missing_vendor"
  | "missing_invoice_number"
  | "missing_due_date"
  | "missing_currency"
  | "missing_total"
  | "missing_line_items"
  | "incomplete_line_item"
  | "due_date_past"
  | "line_total_mismatch"
  | "subtotal_mismatch"
  | "tax_mismatch"
  | "total_mismatch"
  | "unknown_item"
  | "zero_stock"
  | "quantity_exceeds_stock"
  | "non_usd_currency"
  | "unsupported_currency"
  | "revision_after_payment"
  | "version_conflict"
  | (string & {});

/**
 * Error codes carried in ProcessingResult.errors / API error bodies: intake and parser
 * errors (intake.py, parsers/*), model errors (codes.ModelErrorCode), service errors.
 */
export type RunErrorCode =
  | "file_too_large"
  | "unsupported_format"
  | "format_mismatch"
  | "empty_file"
  | "unreadable"
  | "pdf_needs_ocr"
  | "pdf_corrupt"
  | "pdf_encrypted"
  | "too_many_pages"
  | "json_invalid"
  | "xml_invalid"
  | "txt_decode_error"
  | "unsupported_csv_layout"
  | "model_auth_error"
  | "model_rate_limited"
  | "model_timeout"
  | "model_unavailable"
  | "model_output_invalid"
  | "model_refused"
  | "model_budget_exhausted"
  | "model_tool_loop_exceeded"
  | "unexpected_error"
  | "incomplete_graph"
  | "interrupted"
  | (string & {});

// ---- Contracts (schemas.py) ----------------------------------------------------------

/** Decimal string such as "5000.00". Never parsed for display arithmetic. */
export type DecimalStr = string;

export interface EvidenceRef {
  source_id: string;
  /** e.g. "line:9", "row:3", "page:1,line:4", "$.line_items[2].quantity" */
  location: string;
  snippet?: string | null;
}

export interface NormalizationEvent {
  field: string;
  raw_value?: string | null;
  normalized_value?: string | null;
  evidence: EvidenceRef[];
  /** "rule:<name>" or "model:<provider>/<model>" */
  provenance: string;
}

export interface ValidationFinding {
  code: FindingCode;
  severity: Severity;
  field?: string | null;
  item?: string | null;
  expected?: string | null;
  observed?: string | null;
  evidence: EvidenceRef[];
  resolved: boolean;
}

export interface ApprovalDecision {
  initial_recommendation: Recommendation;
  critique_summary?: string | null;
  revised_recommendation?: Recommendation | null;
  final_decision: GateOutcome;
  reasons: string[];
  policy_version: string;
  mode: ExecutionMode;
  provider?: string | null;
  model?: string | null;
  prompt_version?: string | null;
  model_calls_used?: number;
}

export interface MockReceipt {
  receipt_id: string;
  amount: DecimalStr;
  currency: string;
  paid_at: string;
}

export interface LineItem {
  item?: string | null;
  quantity?: DecimalStr | null;
  unit_price?: DecimalStr | null;
  line_total?: DecimalStr | null;
  note?: string | null;
  evidence: EvidenceRef[];
}

export interface StatedTotals {
  subtotal?: DecimalStr | null;
  tax_rate?: DecimalStr | null;
  tax?: DecimalStr | null;
  shipping?: DecimalStr | null;
  total?: DecimalStr | null;
}

export interface ComputedTotals {
  line_totals: (DecimalStr | null)[];
  subtotal?: DecimalStr | null;
  tax?: DecimalStr | null;
  shipping?: DecimalStr | null;
  total?: DecimalStr | null;
}

export interface ProcessingResult {
  run_id: string;
  invoice_id?: string | null;
  status: RunStatus;
  mode: ExecutionMode;
  findings: ValidationFinding[];
  decision?: ApprovalDecision | null;
  receipt?: MockReceipt | null;
  timings_ms: Record<string, number>;
  errors: RunErrorCode[];
  source_hash?: string | null;
  prior_run_id?: string | null;
  evaluation_date?: string | null;
  error_message?: string | null;
  model_calls_used?: number;
  model_calls_budget?: number | null;
  recoverable?: boolean;
  next_actions?: string[];
}

// ---- Error body (P5-01) ----------------------------------------------------------------

export interface ApiErrorBody {
  code: string;
  message: string;
  details?: unknown;
}

// ---- Readiness (P5-01) -----------------------------------------------------------------

export interface Readiness {
  /** Mode the workspace starts in; the operator can switch in Setup. */
  default_mode: ExecutionMode;
  offline_available: boolean;
  live_available: boolean;
  /** Why live is unavailable (e.g. "XAI_API_KEY is not set"); never a secret value. */
  live_unavailable_reason?: string | null;
  live_model?: string | null;
  inventory_seeded: boolean;
  db_path: string;
}

// ---- Samples and runs (P5-02) ----------------------------------------------------------

export interface Sample {
  /** Bare basename in data/invoices/, e.g. "invoice_1001.txt". */
  name: string;
  /** Describes the input, never the outcome: "Clean invoice", "Stock mismatch", ... */
  label: string;
  invoice_number?: string | null;
  format: SourceFormat;
}

export interface StageEvent {
  sequence: number;
  stage: string;
  event: string;
  /** Operator-facing message derived from the persisted audit event. */
  message?: string | null;
  at: string;
}

export interface RunProgress {
  run_id: string;
  status: RunStatus;
  mode: ExecutionMode;
  current_stage?: string | null;
  events: StageEvent[];
  result?: ProcessingResult | null;
  invoice_id?: string | null;
}

export interface RunCreated {
  run_id: string;
}

// ---- Read endpoints (P5-03) ------------------------------------------------------------

export interface InvoiceSummary {
  invoice_id: string;
  invoice_number?: string | null;
  vendor?: string | null;
  total?: DecimalStr | null;
  currency?: string | null;
  status: InvoiceStatus;
  /** Mode of the latest run; historical runs keep their own mode. */
  mode: ExecutionMode;
  due_date?: string | null;
  latest_run_id?: string | null;
  updated_at?: string | null;
}

export interface OverviewCounts {
  unique_invoices: number;
  documents: number;
  runs: number;
  duplicates: number;
  paid_mock: number;
  needs_review: number;
  awaiting_human_approval: number;
  rejected: number;
  failed: number;
  processing: number;
}

export interface Overview {
  counts: OverviewCounts;
  /** Keyed by ISO currency code; never combined across currencies. */
  mock_paid_totals: Record<string, DecimalStr>;
  recent_invoices: InvoiceSummary[];
}

export interface InvoiceListQuery {
  status?: InvoiceStatus | "";
  mode?: ExecutionMode | "";
  q?: string;
  page?: number;
}

export interface InvoiceList {
  items: InvoiceSummary[];
  page: number;
  page_size: number;
  total: number;
}

export interface DetailLineItem {
  item?: string | null;
  requested?: DecimalStr | null;
  /** null when the item is unknown to inventory. */
  available?: number | null;
  unit_price?: DecimalStr | null;
  line_total?: DecimalStr | null;
  /** requested - available when positive (aggregated per item), else null. */
  shortfall?: DecimalStr | null;
  evidence: EvidenceRef[];
}

export interface SourceSummary {
  source_id: string;
  original_name: string;
  format: SourceFormat;
  size_bytes: number;
  page_count?: number | null;
}

export interface InvoiceVersion {
  version: number;
  source_id: string;
  original_name: string;
  revision?: string | null;
  total?: DecimalStr | null;
  currency?: string | null;
  created_at: string;
  status?: InvoiceStatus | null;
  /** Receipt paid against this version, if any. */
  receipt?: MockReceipt | null;
  lines: LineItem[];
}

export interface Correction {
  version: number;
  field: string;
  old_value?: string | null;
  new_value?: string | null;
  reason: string;
  reviewer: string;
  evidence: EvidenceRef[];
  created_at: string;
}

export interface HumanReviewRecord {
  version: number;
  action: HumanReviewAction;
  reviewer: string;
  reason: string;
  policy_version: string;
  created_at: string;
}

export interface RunSummary {
  run_id: string;
  status: RunStatus;
  mode: ExecutionMode;
  source_id?: string | null;
  original_name?: string | null;
  started_at: string;
  finished_at?: string | null;
  prior_run_id?: string | null;
  error_code?: RunErrorCode | null;
  error_message?: string | null;
  provider?: string | null;
  model?: string | null;
  events: StageEvent[];
}

export interface AllowedActions {
  add_corrected_invoice: boolean;
  correct_extraction: boolean;
  approve_payment: boolean;
  decline_payment: boolean;
  retry: boolean;
}

export interface InvoiceDetail {
  invoice_id: string;
  invoice_number?: string | null;
  vendor?: string | null;
  status: InvoiceStatus;
  total?: DecimalStr | null;
  currency?: string | null;
  due_date?: string | null;
  /** Evaluation date of the latest run; drives the Overdue warning. */
  evaluation_date?: string | null;
  mode: ExecutionMode;
  current_version: number;
  source: SourceSummary;
  /** Raw extracted strings by field name (InvoiceDraft *_raw fields). */
  extracted: Record<string, string | null>;
  stated: StatedTotals;
  computed?: ComputedTotals | null;
  normalization_events: NormalizationEvent[];
  findings: ValidationFinding[];
  line_items: DetailLineItem[];
  decision?: ApprovalDecision | null;
  receipt?: MockReceipt | null;
  latest_result?: ProcessingResult | null;
  versions: InvoiceVersion[];
  corrections: Correction[];
  human_reviews: HumanReviewRecord[];
  runs: RunSummary[];
  allowed_actions: AllowedActions;
}

export interface SourceLine {
  /** Evidence location this line answers to, e.g. "line:9" or "row:3". */
  location: string;
  text: string;
}

export interface SourceContent {
  source_id: string;
  original_name: string;
  format: SourceFormat;
  lines: SourceLine[];
  /** For PDF: URL of the original file for page preview, served by the API. */
  original_url?: string | null;
  /** Set when a visual preview is not available, e.g. "Preview unavailable; showing extracted text." */
  preview_limitation?: string | null;
}
