/**
 * Test fixtures shaped like the P5-02/P5-03 responses, with values from the supplied
 * corpus and tests/test_acceptance.py. Used only by tests and the dev-only mock API.
 */
import type {
  InvoiceDetail,
  InvoiceSummary,
  Overview,
  Readiness,
  RunSummary,
  Sample,
  SourceContent,
  ValidationFinding,
} from "../api/types";

export const readinessFixture: Readiness = {
  offline_available: true,
  live_available: false,
  live_unavailable_reason: "XAI_API_KEY is not set",
  live_settings_present: false,
  inventory_seeded: true,
  db_path: "fixture-inventory.db", // sentinel: the bundle check fails if fixtures leak into a build
  schema_version: 6,
  live_model: null,
};

const summary = (s: Partial<InvoiceSummary> & Pick<InvoiceSummary, "invoice_id">): InvoiceSummary => ({
  invoice_number: null,
  vendor: null,
  total: null,
  currency: "USD",
  status: "paid_mock",
  mode: "offline",
  due_date: null,
  latest_run_id: null,
  updated_at: "2026-11-01T18:00:00Z",
  ...s,
});

export const inv1001 = summary({
  invoice_id: "inv-1001",
  invoice_number: "INV-1001",
  vendor: "Widgets Inc.",
  total: "5000.00",
  status: "paid_mock",
  due_date: "2026-02-01",
});
export const inv1004 = summary({
  invoice_id: "inv-1004",
  invoice_number: "INV-1004",
  vendor: "Precision Parts Ltd.",
  total: "1890.00",
  status: "paid_mock",
  due_date: "2026-02-22",
});
export const inv1002 = summary({
  invoice_id: "inv-1002",
  invoice_number: "INV-1002",
  vendor: "Gadgets Co.",
  total: "15000.00",
  status: "rejected",
  due_date: "2026-01-30",
});
export const inv1014 = summary({
  invoice_id: "inv-1014",
  invoice_number: "INV-1014",
  vendor: "TechParts International",
  total: "4125.00",
  currency: "EUR",
  status: "needs_review",
  due_date: "2026-02-26",
});

export const fourInvoices = [inv1001, inv1004, inv1002, inv1014];

/** P5-03 acceptance data: 1001, 1004, 1002, 1014 on a fresh DB. */
export const overviewFixture: Overview = {
  counts: {
    unique_invoices: 4,
    documents: 4,
    runs: 4,
    duplicates: 0,
    paid_mock: 2,
    needs_review: 1,
    awaiting_human_approval: 0,
    rejected: 1,
    failed: 0,
    processing: 0,
  },
  mock_paid_totals: { USD: "6890.00" },
  recent_invoices: fourInvoices,
};

export const emptyOverviewFixture: Overview = {
  counts: {
    unique_invoices: 0,
    documents: 0,
    runs: 0,
    duplicates: 0,
    paid_mock: 0,
    needs_review: 0,
    awaiting_human_approval: 0,
    rejected: 0,
    failed: 0,
    processing: 0,
  },
  mock_paid_totals: {},
  recent_invoices: [],
};

export const samplesFixture: Sample[] = [
  { name: "invoice_1001.txt", label: "Clean invoice", invoice_number: "INV-1001", format: "txt", size_bytes: 400 },
  { name: "invoice_1002.txt", label: "Stock mismatch", invoice_number: "INV-1002", format: "txt", size_bytes: 400 },
  { name: "invoice_1012.txt", label: "Messy formatting", invoice_number: "INV-1012", format: "txt", size_bytes: 400 },
  { name: "invoice_1013.json", label: "Conflicting totals", invoice_number: "INV-1013", format: "json", size_bytes: 400 },
  { name: "invoice_1014.xml", label: "Unsupported currency", invoice_number: "INV-1014", format: "xml", size_bytes: 400 },
];

const run = (r: Partial<RunSummary> & Pick<RunSummary, "run_id" | "status">): RunSummary => ({
  mode: "offline",
  source_id: "src-1",
  original_name: "invoice.txt",
  started_at: "2026-11-01T18:00:00Z",
  finished_at: "2026-11-01T18:00:01Z",
  prior_run_id: null,
  retry_of: null,
  evaluation_date: "2026-01-20",
  error_code: null,
  error_message: null,
  provider: null,
  model: null,
  trigger: "submission",
  events: [],
  ...r,
});

const offlineDecision = (
  final: "approved" | "rejected" | "needs_review",
  initial: "approve" | "reject" | "review",
  critique: string,
  reasons: string[],
) => ({
  initial_recommendation: initial,
  critique_summary: critique,
  revised_recommendation: null,
  final_decision: final,
  reasons,
  policy_version: "policy-1",
  mode: "offline" as const,
  provider: "offline",
  model: "simulator",
  model_calls_used: 0,
});

/** Base detail; every state fixture overrides only what differs. */
export function detailFixture(overrides: Partial<InvoiceDetail> = {}): InvoiceDetail {
  return {
    invoice_id: "inv-1001",
    invoice_number: "INV-1001",
    vendor: "Widgets Inc.",
    status: "paid_mock",
    total: "5000.00",
    currency: "USD",
    due_date: "2026-02-01",
    evaluation_date: "2026-01-20",
    mode: "offline",
    current_version: 1,
    source: {
      source_id: "src-1001",
      original_name: "invoice_1001.txt",
      format: "txt",
      size_bytes: 412,
      page_count: null,
    },
    stated: { subtotal: "5000.00", tax: "0.00", total: "5000.00" },
    computed: { line_totals: ["2500.00", "2500.00"], subtotal: "5000.00", tax: "0.00", total: "5000.00" },
    normalization_events: [],
    findings: [],
    line_items: [
      { item: "WidgetA", requested: "10", available: 15, unit_price: "250.00", line_total: "2500.00", shortfall: null, evidence: [] },
      { item: "WidgetB", requested: "5", available: 10, unit_price: "500.00", line_total: "2500.00", shortfall: null, evidence: [] },
    ],
    decision: offlineDecision("approved", "approve", "Agrees: inventory and totals passed.", [
      "All required fields present.",
      "Requested quantities are within stock.",
    ]),
    receipt: {
      receipt_id: "rcpt-7f3a1c",
      amount: "5000.00",
      currency: "USD",
      paid_at: "2026-11-01T18:00:01Z",
    },
    latest_result: null,
    versions: [],
    corrections: [],
    human_reviews: [],
    runs: [
      run({
        run_id: "run-1001",
        status: "paid_mock",
        original_name: "invoice_1001.txt",
        events: [
          { sequence: 1, stage: "ingestion", event: "extracted", message: "Vendor, invoice number, due date, and two items extracted.", at: "2026-11-01T18:00:00Z", payload: {} },
          { sequence: 2, stage: "validation", event: "validated", message: null, at: "2026-11-01T18:00:00Z", payload: {} },
          { sequence: 3, stage: "approval", event: "approved", message: null, at: "2026-11-01T18:00:01Z", payload: {} },
          { sequence: 4, stage: "payment", event: "paid", message: null, at: "2026-11-01T18:00:01Z", payload: {} },
        ],
      }),
    ],
    allowed_actions: {
      add_corrected_invoice: false,
      correct_extraction: false,
      approve_payment: false,
      decline_payment: false,
      retry: false,
    },
    review_actions: null,
    ...overrides,
  };
}

export const source1001: SourceContent = {
  source_id: "src-1001",
  original_name: "invoice_1001.txt",
  format: "txt",
  lines: [
    "INVOICE",
    "",
    "Vendor: Widgets Inc.",
    "Invoice Number: INV-1001",
    "Date: 2026-01-15",
    "Due Date: 2026-02-01",
    "",
    "Items:",
    "  WidgetA    qty: 10    unit price: $250.00",
    "  WidgetB    qty: 5     unit price: $500.00",
  ].map((text, i) => ({ location: `line:${i + 1}`, text })),
  original_url: null,
  preview_limitation: null,
};

const finding = (f: Partial<ValidationFinding> & Pick<ValidationFinding, "code" | "severity">): ValidationFinding => ({
  field: null,
  item: null,
  expected: null,
  observed: null,
  evidence: [],
  resolved: false,
  ...f,
});

const noActions = detailFixture().allowed_actions;

export const detail1001 = detailFixture();

export const detail1002 = detailFixture({
  invoice_id: "inv-1002",
  invoice_number: "INV-1002",
  vendor: "Gadgets Co.",
  status: "rejected",
  total: "15000.00",
  due_date: "2026-01-30",
  source: { source_id: "src-1002", original_name: "invoice_1002.txt", format: "txt", size_bytes: 160, page_count: null },
  stated: { total: "15000.00" },
  computed: { line_totals: ["15000.00"], subtotal: "15000.00", total: "15000.00" },
  findings: [
    finding({
      code: "quantity_exceeds_stock",
      severity: "blocker",
      item: "GadgetX",
      expected: "5",
      observed: "20",
      evidence: [{ source_id: "src-1002", location: "line:9", snippet: "GadgetX  qty 20   @ $750 ea" }],
    }),
  ],
  line_items: [
    { item: "GadgetX", requested: "20", available: 5, unit_price: "750.00", line_total: "15000.00", shortfall: "15", evidence: [] },
  ],
  decision: offlineDecision("rejected", "reject", "High-value review does not resolve the stock mismatch.", [
    "Requested 20 GadgetX; 5 available.",
  ]),
  receipt: null,
  runs: [run({ run_id: "run-1002", status: "rejected", original_name: "invoice_1002.txt" })],
  allowed_actions: { ...noActions, add_corrected_invoice: true },
});

export const detail1013 = detailFixture({
  invoice_id: "inv-1013",
  invoice_number: "INV-1013",
  vendor: "Atlas Industrial Supply",
  status: "rejected",
  total: "22562.80",
  due_date: "2026-03-24",
  source: { source_id: "src-1013", original_name: "invoice_1013.json", format: "json", size_bytes: 1500, page_count: null },
  stated: { subtotal: "21040.00", tax_rate: "0.07", tax: "1472.80", total: "22562.80" },
  computed: { line_totals: [], subtotal: "21040.00", tax: "1472.80", total: "22512.80" },
  findings: [
    finding({ code: "quantity_exceeds_stock", severity: "blocker", item: "WidgetA", expected: "15", observed: "22" }),
    finding({ code: "quantity_exceeds_stock", severity: "blocker", item: "WidgetB", expected: "10", observed: "18" }),
    finding({ code: "quantity_exceeds_stock", severity: "blocker", item: "GadgetX", expected: "5", observed: "9" }),
    finding({ code: "total_mismatch", severity: "blocker", field: "total", expected: "22512.80", observed: "22562.80" }),
  ],
  line_items: [
    { item: "WidgetA", requested: "22", available: 15, unit_price: "250.00", line_total: "3750.00", shortfall: "7", evidence: [] },
    { item: "WidgetB", requested: "18", available: 10, unit_price: "500.00", line_total: "5000.00", shortfall: "8", evidence: [] },
    { item: "GadgetX", requested: "9", available: 5, unit_price: "750.00", line_total: "3750.00", shortfall: "4", evidence: [] },
  ],
  decision: offlineDecision("rejected", "reject", "Agrees: stock and totals block payment.", []),
  receipt: null,
  runs: [run({ run_id: "run-1013", status: "rejected", original_name: "invoice_1013.json" })],
  allowed_actions: { ...noActions, add_corrected_invoice: true },
});

export const detail1012 = detailFixture({
  invoice_id: "inv-1012",
  invoice_number: "INV-1012",
  vendor: "QuickShip Distributers",
  total: "9975.00",
  due_date: "2026-02-25",
  source: { source_id: "src-1012", original_name: "invoice_1012.txt", format: "txt", size_bytes: 900, page_count: null },
  normalization_events: [
    { field: "invoice_number", raw_value: "INV 1012", normalized_value: "INV-1012", evidence: [{ source_id: "src-1012", location: "line:6" }], provenance: "rule:invoice_number_format" },
    { field: "invoice_date", raw_value: "26-Jan-2O26", normalized_value: "2026-01-26", evidence: [{ source_id: "src-1012", location: "line:7" }], provenance: "rule:ocr_digit" },
    { field: "lines[0].item", raw_value: "Widget A", normalized_value: "WidgetA", evidence: [{ source_id: "src-1012", location: "line:16" }], provenance: "rule:item_spacing" },
  ],
  receipt: { receipt_id: "rcpt-1012", amount: "9975.00", currency: "USD", paid_at: "2026-11-01T18:05:00Z" },
  runs: [run({ run_id: "run-1012", status: "paid_mock", original_name: "invoice_1012.txt" })],
});

export const detail1014 = detailFixture({
  invoice_id: "inv-1014",
  invoice_number: "INV-1014",
  vendor: "TechParts International",
  status: "needs_review",
  total: "4125.00",
  currency: "EUR",
  due_date: "2026-02-26",
  source: { source_id: "src-1014", original_name: "invoice_1014.xml", format: "xml", size_bytes: 1200, page_count: null },
  findings: [
    finding({ code: "non_usd_currency", severity: "review", field: "currency", observed: "EUR" }),
    finding({ code: "unsupported_currency", severity: "review", field: "currency", observed: "EUR" }),
  ],
  line_items: [
    { item: "WidgetA", requested: "4", available: 15, unit_price: "225.00", line_total: "900.00", shortfall: null, evidence: [] },
    { item: "WidgetB", requested: "6", available: 10, unit_price: "475.00", line_total: "2850.00", shortfall: null, evidence: [] },
  ],
  decision: offlineDecision("needs_review", "review", "EUR settlement is not supported.", []),
  receipt: null,
  runs: [run({ run_id: "run-1014", status: "needs_review", original_name: "invoice_1014.xml" })],
});

/** 1011 TXT paid, then 1011 PDF submitted: duplicate run, same receipt. */
export const detail1011Duplicate = detailFixture({
  invoice_id: "inv-1011",
  invoice_number: "INV-1011",
  vendor: "Summit Supply Co.",
  total: "3250.00",
  source: { source_id: "src-1011", original_name: "invoice_1011.txt", format: "txt", size_bytes: 600, page_count: null },
  receipt: { receipt_id: "rcpt-1011", amount: "3250.00", currency: "USD", paid_at: "2026-11-01T18:01:00Z" },
  runs: [
    run({ run_id: "run-1011-pdf", status: "duplicate", original_name: "invoice_1011.pdf", prior_run_id: "run-1011-txt", started_at: "2026-11-01T18:02:00Z" }),
    run({ run_id: "run-1011-txt", status: "paid_mock", original_name: "invoice_1011.txt", started_at: "2026-11-01T18:01:00Z" }),
  ],
});

const receipt1004 = { receipt_id: "rcpt-1004", amount: "1890.00", currency: "USD", paid_at: "2026-11-01T18:03:00Z" };

/** 1004 revised (R1) after 1004 was mock paid. */
export const detail1004Revised = detailFixture({
  invoice_id: "inv-1004",
  invoice_number: "INV-1004",
  vendor: "Precision Parts Ltd.",
  status: "needs_review",
  total: "5940.00",
  due_date: "2026-02-22",
  current_version: 2,
  source: { source_id: "src-1004r", original_name: "invoice_1004_revised.json", format: "json", size_bytes: 700, page_count: null },
  findings: [finding({ code: "revision_after_payment", severity: "review" })],
  receipt: receipt1004,
  versions: [
    { version: 1, source_id: "src-1004", original_name: "invoice_1004.json", revision: null, total: "1890.00", currency: "USD", created_at: "2026-11-01T18:03:00Z", receipt: receipt1004, lines: [] },
    { version: 2, source_id: "src-1004r", original_name: "invoice_1004_revised.json", revision: "R1", total: "5940.00", currency: "USD", created_at: "2026-11-01T18:04:00Z", receipt: null, lines: [] },
  ],
  decision: offlineDecision("needs_review", "review", "Revision after payment requires review.", []),
  runs: [
    run({ run_id: "run-1004r", status: "needs_review", original_name: "invoice_1004_revised.json", started_at: "2026-11-01T18:04:00Z" }),
    run({ run_id: "run-1004", status: "paid_mock", original_name: "invoice_1004.json", started_at: "2026-11-01T18:03:00Z" }),
  ],
});

export const detailVersionConflict = detailFixture({
  invoice_id: "inv-2001",
  invoice_number: "INV-2001",
  vendor: "Widgets Inc.",
  status: "needs_review",
  total: "5250.00",
  current_version: 2,
  findings: [finding({ code: "version_conflict", severity: "review" })],
  receipt: null,
  decision: null,
  versions: [
    { version: 1, source_id: "a", original_name: "inv_2001.txt", revision: null, total: "5000.00", currency: "USD", created_at: "2026-11-01T10:00:00Z", receipt: null, lines: [{ item: "WidgetA", quantity: "10", evidence: [] }] },
    { version: 2, source_id: "b", original_name: "inv_2001_b.txt", revision: null, total: "5250.00", currency: "USD", created_at: "2026-11-01T11:00:00Z", receipt: null, lines: [{ item: "WidgetA", quantity: "11", evidence: [] }] },
  ],
  runs: [run({ run_id: "run-2001", status: "needs_review" })],
});

const failedDetail = (code: string, message: string, mode: "offline" | "live" = "offline", lastStage = "ingestion") =>
  detailFixture({
    invoice_id: `inv-fail-${code}`,
    invoice_number: null,
    vendor: null,
    status: "failed",
    total: null,
    due_date: null,
    mode,
    findings: [],
    line_items: [],
    decision: null,
    receipt: null,
    runs: [
      run({
        run_id: `run-${code}`,
        status: "failed",
        mode,
        error_code: code,
        error_message: message,
        events: [{ sequence: 1, stage: lastStage, event: "failed", message: null, at: "2026-11-01T18:00:00Z", payload: {} }],
      }),
    ],
    allowed_actions: { ...noActions, retry: code.startsWith("model_") || code === "unexpected_error" },
  });

export const detailUnreadable = failedDetail("xml_invalid", "The XML is not well-formed (line 3).");
export const detailOcr = failedDetail("pdf_needs_ocr", "This PDF needs OCR, which this prototype does not support.");
export const detailOversized = failedDetail("file_too_large", "File exceeds the 10 MiB limit.");
export const detailProvider = failedDetail("model_unavailable", "The model provider returned 503.", "live", "approval");
export const detailProcessing = failedDetail("unexpected_error", "Validation raised an unexpected error; see the run log.", "offline", "validation");

export const detailMissingFields = detailFixture({
  invoice_id: "inv-missing",
  invoice_number: "INV-3001",
  vendor: null,
  status: "rejected",
  due_date: null,
  findings: [
    finding({ code: "missing_vendor", severity: "blocker", field: "vendor" }),
    finding({ code: "missing_due_date", severity: "blocker", field: "due_date" }),
  ],
  receipt: null,
  decision: null,
  runs: [run({ run_id: "run-missing", status: "rejected" })],
});
