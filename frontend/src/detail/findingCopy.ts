import type { FindingCode, RunErrorCode, ValidationFinding } from "../api/types";

/**
 * Operator copy for finding codes. Presentation only: severities and outcomes come from
 * the backend; nothing here decides whether an invoice may be paid.
 */
const FINDING_TEXT: Record<string, string> = {
  missing_vendor: "Vendor name is missing.",
  missing_invoice_number: "Invoice number is missing.",
  missing_due_date: "Due date is missing.",
  missing_currency: "Currency is missing.",
  missing_total: "Stated invoice total is missing.",
  missing_line_items: "Invoice has no line items.",
  incomplete_line_item: "A line item lacks an item name, quantity, or unit price.",
  non_positive_quantity: "A line quantity is zero or negative.",
  non_integer_quantity: "A line quantity is not a whole number.",
  non_positive_total: "Stated invoice total is zero or negative.",
  negative_unit_price: "A unit price is negative.",
  negative_tax: "Stated tax is negative.",
  negative_shipping: "Stated shipping is negative.",
  due_date_past: "Due date is before the evaluation date.",
  line_total_mismatch: "A stated line total differs from quantity times unit price.",
  subtotal_mismatch: "Stated subtotal differs from the sum of line totals.",
  tax_mismatch: "Stated tax differs from subtotal times the tax rate.",
  total_mismatch: "Stated total differs from subtotal plus tax plus shipping.",
  rounding_tolerated: "A difference of at most one cent was tolerated.",
  arithmetic_unverifiable: "Totals could not be recomputed because a line lacks inputs.",
  unknown_item: "Item is not in the inventory database.",
  zero_stock: "Item is in inventory with zero stock.",
  quantity_exceeds_stock: "Requested quantity exceeds available stock.",
  currency_assumed_usd: "Currency was not stated; USD was assumed.",
  model_disagreement: "The recommendation was not approve on an otherwise clean invoice.",
  non_usd_currency: "This prototype only simulates USD settlement.",
  unparsed_line: "A source line matched no known field and was ignored.",
  ambiguous_normalization: "A value could be normalized in more than one way.",
  unparseable_value: "A value could not be converted to its expected type.",
  risk_signal_urgency: "The document contains urgency language.",
  due_date_unresolved: "The due date could not be resolved to a calendar date.",
  ambiguous_date: "A date could be read as day-month or month-day.",
  due_before_invoice_date: "The due date is before the invoice date.",
  terms_inconsistent: "Payment terms disagree with the invoice and due dates.",
  unsupported_currency: "The currency is not supported.",
  currency_conflict: "The document states conflicting currencies.",
  revision_after_payment: "A revision arrived for an invoice that was already mock paid.",
  version_conflict: "This version conflicts with an existing version of the invoice.",
  unrecognized_field: "A field was not recognized and was ignored.",
  duplicate_field: "A field appears more than once with different content.",
  malformed_row: "A table row does not match the expected shape.",
  inconsistent_row_header: "Line item rows are inconsistent with their header.",
};

/** Lower-case clause for "Payment blocked: …". */
const BLOCKING_CLAUSE: Record<string, string> = {
  quantity_exceeds_stock: "requested quantity exceeds available stock",
  zero_stock: "an item has no stock",
  unknown_item: "an item is not in inventory",
  total_mismatch: "the stated total does not match the calculated total",
  subtotal_mismatch: "the stated subtotal does not match the line totals",
  line_total_mismatch: "a line total does not match quantity times unit price",
  tax_mismatch: "the stated tax does not match the tax rate",
};

export function findingText(code: FindingCode): string {
  return FINDING_TEXT[code] ?? code.replace(/_/g, " ");
}

export function blockingClause(finding: ValidationFinding): string {
  const clause = BLOCKING_CLAUSE[finding.code];
  if (clause) return clause;
  const text = findingText(finding.code).replace(/\.$/, "");
  return text.charAt(0).toLowerCase() + text.slice(1);
}

const SEVERITY_RANK = { blocker: 0, review: 1, warning: 2, info: 3 } as const;

/** Unresolved findings, most severe first (stable within a severity). */
export function rankedFindings(findings: ValidationFinding[]): ValidationFinding[] {
  return findings
    .filter((f) => !f.resolved)
    .map((f, i) => ({ f, i }))
    .sort((a, b) => SEVERITY_RANK[a.f.severity] - SEVERITY_RANK[b.f.severity] || a.i - b.i)
    .map(({ f }) => f);
}

/** Check groups for the Checks tab summary (mockup screen 5). */
export const CHECK_GROUPS: { label: string; pass: string; codes: string[] }[] = [
  {
    label: "Required fields",
    pass: "Complete",
    codes: [
      "missing_vendor",
      "missing_invoice_number",
      "missing_due_date",
      "missing_currency",
      "missing_total",
      "missing_line_items",
      "incomplete_line_item",
    ],
  },
  {
    label: "Item quantities",
    pass: "Within stock",
    codes: ["quantity_exceeds_stock", "zero_stock", "unknown_item", "non_positive_quantity", "non_integer_quantity"],
  },
  {
    label: "Invoice arithmetic",
    pass: "Matches",
    codes: [
      "line_total_mismatch",
      "subtotal_mismatch",
      "tax_mismatch",
      "total_mismatch",
      "arithmetic_unverifiable",
      "non_positive_total",
      "negative_unit_price",
      "negative_tax",
      "negative_shipping",
    ],
  },
  {
    label: "Currency",
    pass: "USD",
    codes: ["non_usd_currency", "unsupported_currency", "currency_conflict"],
  },
  {
    label: "Duplicate payment",
    pass: "None found",
    codes: ["revision_after_payment", "version_conflict"],
  },
];

export const FIELD_LABEL: Record<string, string> = {
  vendor: "vendor",
  vendor_name: "vendor",
  invoice_number: "invoice number",
  due_date: "due date",
  currency: "currency",
  total: "total",
  line_items: "line items",
};

const MISSING_CODES: Record<string, string> = {
  missing_vendor: "vendor",
  missing_invoice_number: "invoice number",
  missing_due_date: "due date",
  missing_currency: "currency",
  missing_total: "total",
  missing_line_items: "line items",
};

/** "Vendor and due date are missing." / "Vendor is missing." / null when none. */
export function missingFieldsMessage(findings: ValidationFinding[]): string | null {
  const fields = findings
    .filter((f) => !f.resolved && f.code in MISSING_CODES)
    .map((f) => MISSING_CODES[f.code] as string);
  const unique = [...new Set(fields)];
  if (unique.length === 0) return null;
  const joined =
    unique.length === 1
      ? unique[0]!
      : unique.length === 2
        ? `${unique[0]} and ${unique[1]}`
        : `${unique.slice(0, -1).join(", ")}, and ${unique[unique.length - 1]}`;
  const verb = unique.length === 1 && unique[0] !== "line items" ? "is" : "are";
  return `${joined.charAt(0).toUpperCase()}${joined.slice(1)} ${verb} missing.`;
}

// ---- Run errors ---------------------------------------------------------------------

export type FailureKind = "unreadable" | "ocr" | "oversized" | "provider" | "processing";

const UNREADABLE = new Set<string>([
  "unsupported_format",
  "format_mismatch",
  "empty_file",
  "unreadable",
  "pdf_corrupt",
  "pdf_encrypted",
  "too_many_pages",
  "json_invalid",
  "xml_invalid",
  "txt_decode_error",
  "unsupported_csv_layout",
  "unsupported_document",
]);

export function failureKind(code: RunErrorCode | null | undefined): FailureKind {
  if (!code) return "processing";
  if (code === "pdf_needs_ocr") return "ocr";
  if (code === "file_too_large") return "oversized";
  if (code.startsWith("model_")) return "provider";
  if (UNREADABLE.has(code)) return "unreadable";
  return "processing";
}

const STAGE_LABEL: Record<string, string> = {
  intake: "intake",
  ingest: "extraction",
  ingestion: "extraction",
  extract: "extraction",
  extraction: "extraction",
  validate: "validation",
  validation: "validation",
  approve: "review",
  approval: "review",
  review: "review",
  pay: "payment",
  payment: "payment",
};

export function stageLabel(stage: string | null | undefined): string {
  if (!stage) return "processing";
  return STAGE_LABEL[stage] ?? stage.replace(/_/g, " ");
}
