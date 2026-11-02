/**
 * Review-queue fixtures shaped like the Phase 4 contracts (ReviewQueue, QueueItem,
 * AllowedActions) and the P5-04 endpoint bodies assumed in api/review.ts. Values follow
 * the Phase 4 plan fixtures (extraction_mistake.txt, valid_10000_01.json, INV-1014).
 */
import type { QueueItem, ReviewAllowedActions, ReviewQueue } from "../api/review";
import type { InvoiceDetail, SourceContent } from "../api/types";
import { detail1014, detailFixture } from "./fixtures";

const decision = (
  final: "awaiting_human_approval" | "needs_review" | "approved",
  initial: "approve" | "reject" | "review",
  critique: string,
  reasons: string[],
): NonNullable<InvoiceDetail["decision"]> => ({
  initial_recommendation: initial,
  critique_summary: critique,
  revised_recommendation: null,
  final_decision: final,
  reasons,
  policy_version: "policy-1",
  mode: "offline",
  provider: "offline",
  model: "simulator",
  model_calls_used: 0,
});

const run = (run_id: string, status: InvoiceDetail["runs"][number]["status"], original_name: string) => ({
  run_id,
  status,
  mode: "offline" as const,
  source_id: "src",
  original_name,
  started_at: "2026-11-01T18:00:00Z",
  finished_at: "2026-11-01T18:00:01Z",
  prior_run_id: null,
  retry_of: null,
  evaluation_date: "2026-01-31",
  error_code: null,
  error_message: null,
  provider: null,
  model: null,
  trigger: "submission",
  events: [],
});

export const detailExtractionMistake: InvoiceDetail = detailFixture({
  invoice_id: "inv-ct-3001",
  invoice_number: "CT-3001",
  vendor: "Correction Test Co",
  status: "needs_review",
  total: null,
  due_date: "2026-03-01",
  evaluation_date: "2026-01-31",
  source: { source_id: "src-ct", original_name: "extraction_mistake.txt", format: "txt", size_bytes: 300, page_count: null },
  stated: { subtotal: "3500.00", tax: "0.00", total: null },
  computed: { line_totals: ["3500.00"], subtotal: "3500.00", tax: "0.00", total: "3500.00" },
  findings: [
    {
      code: "unparseable_value",
      severity: "review",
      field: "total",
      item: null,
      expected: null,
      observed: "$3.500,00",
      evidence: [{ source_id: "src-ct", location: "line:13", snippet: "Total Amount: $3.500,00" }],
      resolved: false,
    },
  ],
  line_items: [
    {
      item: "WidgetA",
      requested: "7",
      available: 15,
      unit_price: "500.00",
      line_total: "3500.00",
      shortfall: null,
      evidence: [{ source_id: "src-ct", location: "line:9", snippet: "WidgetA qty: 7 unit price: $500.00" }],
    },
  ],
  decision: decision("needs_review", "review", "A value could not be read.", []),
  receipt: null,
  runs: [run("run-ct-1", "needs_review", "extraction_mistake.txt")],
});

export const sourceExtractionMistake: SourceContent = {
  source_id: "src-ct",
  original_name: "extraction_mistake.txt",
  format: "txt",
  lines: [
    "INVOICE",
    "",
    "Vendor: Correction Test Co",
    "Invoice Number: CT-3001",
    "Date: 2026-01-20",
    "Due Date: 2026-03-01",
    "",
    "Items:",
    "  WidgetA    qty: 7    unit price: $500.00",
    "",
    "Subtotal: $3,500.00",
    "Tax (0%): $0.00",
    "Total Amount: $3.500,00",
  ].map((text, i) => ({ location: `line:${i + 1}`, text })),
  original_url: null,
  preview_limitation: null,
};

export const detailHighValue: InvoiceDetail = detailFixture({
  invoice_id: "inv-hv-1",
  invoice_number: "HV-10001",
  vendor: "Threshold Supply",
  status: "awaiting_human_approval",
  total: "10000.01",
  current_version: 1,
  source: { source_id: "src-hv", original_name: "valid_10000_01.json", format: "json", size_bytes: 500, page_count: null },
  stated: { subtotal: "10000.01", tax: "0.00", total: "10000.01" },
  findings: [],
  decision: decision("awaiting_human_approval", "approve", "Agrees: high value scrutinized; checks passed.", [
    "All required fields present.",
    "Total above USD 10,000 requires a person.",
  ]),
  receipt: null,
  runs: [run("run-hv-1", "awaiting_human_approval", "valid_10000_01.json")],
});

export const detailDisagreement: InvoiceDetail = detailFixture({
  invoice_id: "inv-md-1",
  invoice_number: "MD-2001",
  vendor: "Second Opinion Ltd",
  status: "awaiting_human_approval",
  total: "1200.00",
  findings: [
    {
      code: "model_disagreement",
      severity: "review",
      field: null,
      item: null,
      expected: null,
      observed: null,
      evidence: [],
      resolved: false,
    },
  ],
  decision: decision("awaiting_human_approval", "reject", "The model's concern is not backed by a finding.", [
    "Vendor is unfamiliar.",
  ]),
  receipt: null,
  runs: [run("run-md-1", "awaiting_human_approval", "second_opinion.txt")],
});

export function actionsFor(
  invoice_id: string,
  status: ReviewAllowedActions["status"],
  current_version: number,
): ReviewAllowedActions {
  // The Phase 4 Task 2 table.
  switch (status) {
    case "awaiting_human_approval":
      return {
        invoice_id,
        status,
        current_version,
        allowed: ["approve", "decline", "correct"],
        refused: { submit_corrected: "action_not_allowed" },
      };
    case "needs_review":
    case "rejected":
      return {
        invoice_id,
        status,
        current_version,
        allowed: ["correct", "submit_corrected"],
        refused: { approve: "action_not_allowed", decline: "action_not_allowed" },
      };
    case "paid_mock":
      return {
        invoice_id,
        status,
        current_version,
        allowed: [],
        refused: {
          correct: "already_paid",
          approve: "already_paid",
          decline: "already_paid",
          submit_corrected: "already_paid",
        },
      };
    default:
      return { invoice_id, status, current_version, allowed: [], refused: {} };
  }
}

export function queueItem(d: InvoiceDetail, reason_codes: QueueItem["reason_codes"]): QueueItem {
  return {
    invoice_id: d.invoice_id,
    vendor_name: d.vendor,
    invoice_number: d.invoice_number,
    total: d.total,
    currency: d.currency,
    status: d.status,
    current_version: d.current_version,
    reason_codes,
    actions: actionsFor(d.invoice_id, d.status, d.current_version),
  };
}

export const reviewQueueFixture: ReviewQueue = {
  groups: {
    correctable_extraction: [queueItem(detailExtractionMistake, ["unparseable_value"])],
    awaiting_human_approval: [queueItem(detailHighValue, []), queueItem(detailDisagreement, ["model_disagreement"])],
    unresolved_blocker: [queueItem(detail1014, ["non_usd_currency", "unsupported_currency"])],
  },
};

export const reviewDetails: InvoiceDetail[] = [detailExtractionMistake, detailHighValue, detailDisagreement];
