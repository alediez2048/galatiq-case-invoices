/**
 * Wire responses (generated types) -> view models (types.ts). The only place that knows
 * both shapes. Pure functions; no defaults are invented for values the API did not send.
 */
import type {
  AllowedActions,
  ExecutionMode,
  InvoiceDetail,
  InvoiceList,
  InvoiceSummary,
  Overview,
  ProcessingResult,
  Readiness,
  RunCreated,
  RunProgress,
  RunSummary,
  Sample,
  SourceContent,
  StageEvent,
  Wire,
} from "./types";

export function toReadiness(w: Wire["Readiness"]): Readiness {
  const live = w.modes.live;
  return {
    offline_available: w.modes.offline?.available === true,
    live_available: live?.available === true,
    live_unavailable_reason: live?.available ? null : (live?.reason ?? null),
    live_settings_present: w.live_settings_present,
    inventory_seeded: w.inventory_seeded,
    db_path: w.database_path,
    schema_version: w.schema_version,
  };
}

export function toSample(w: Wire["Sample"]): Sample {
  return { ...w };
}

export function toRunCreated(w: Wire["RunAccepted"]): RunCreated {
  return { ...w };
}

const str = (v: unknown): string | null => (typeof v === "string" ? v : null);
const num = (v: unknown): number | null => (typeof v === "number" ? v : null);

/** True when a model step is the extraction-repair path (P3-05), not approval/critique. */
function isExtractionModelCall(p: Record<string, unknown>): boolean {
  const agent = str(p.agent) ?? "";
  const step = str(p.step) ?? "";
  return agent === "ingestion" || /extract|repair/i.test(step);
}

/**
 * Operator-facing sentence for one persisted audit event. Unknown events fall back to the
 * event name so nothing is hidden and nothing is invented.
 */
export function eventMessage(stage: string, event: string, p: Record<string, unknown>): string {
  const mode = str(p.mode);
  const simulated = mode === "offline" ? " (simulated)" : "";
  switch (event) {
    case "received":
      return `Document received${str(p.original_name) ? `: ${str(p.original_name)}` : ""}.`;
    case "extracted":
      return "Invoice details extracted.";
    case "extraction_failed":
      return `Extraction failed${str(p.error_code) ? ` (${str(p.error_code)})` : ""}.`;
    case "validated":
      return "Required fields, totals and inventory checked.";
    case "recommendation":
      return `Recommendation${simulated}: ${str(p.recommendation) ?? "recorded"}.`;
    case "critique":
      return p.agrees === false
        ? `Critique${simulated} revised the recommendation to ${str(p.revised_recommendation) ?? "review"}.`
        : `Critique${simulated} agreed with the recommendation.`;
    case "decision":
      return `Policy result: ${(str(p.final_decision) ?? "recorded").replace(/_/g, " ")}.`;
    case "payment_succeeded":
    case "paid":
      return `Mock payment recorded${str(p.receipt_id) ? ` (receipt ${str(p.receipt_id)})` : ""}. No real funds transferred.`;
    case "rejection_recorded":
      return "Payment was not attempted.";
    case "duplicate":
      return "Already processed. No additional payment.";
    case "finished":
      return `Finished: ${(str(p.status) ?? "done").replace(/_/g, " ")}.`;
    case "failed":
      return `Processing stopped${str(p.error_code) ? ` (${str(p.error_code)})` : ""}.`;
    case "model_call": {
      const attempt = num(p.attempt);
      if (isExtractionModelCall(p)) {
        return `Checking an extraction issue — attempt ${attempt ?? 1} of 2.`;
      }
      if (/critique/i.test(str(p.step) ?? "")) return "Checking the recommendation against policy.";
      return `Model request: ${str(p.step) ?? stage}${attempt && attempt > 1 ? ` (attempt ${attempt})` : ""}.`;
    }
    default:
      return `${stage}: ${event.replace(/_/g, " ")}.`;
  }
}

export function toStageEvents(events: Wire["AuditEvent"][]): StageEvent[] {
  return events.map((e, i) => ({
    sequence: i + 1,
    stage: e.stage,
    event: e.event,
    message: eventMessage(e.stage, e.event, e.payload),
    at: e.created_at,
    payload: e.payload,
  }));
}

export function toResult(w: Wire["RunView"]["result"]): ProcessingResult | null {
  if (!w) return null;
  return {
    ...w,
    errors: w.errors ?? [],
    findings: (w.findings ?? []).map((f) => ({ ...f, evidence: f.evidence ?? [] })),
  };
}

export function toRunProgress(w: Wire["RunView"]): RunProgress {
  return {
    run_id: w.run_id,
    status: w.status,
    mode: w.mode,
    current_stage: w.stage,
    terminal: w.terminal,
    invoice_id: w.invoice_id ?? null,
    source: w.source,
    error_code: w.error_code ?? null,
    error_message: w.error_message ?? null,
    prior_run_id: w.prior_run_id ?? null,
    retry_of: w.retry_of ?? null,
    events: toStageEvents(w.events),
    result: toResult(w.result),
  };
}

export function toInvoiceSummary(w: Wire["InvoiceSummary"]): InvoiceSummary {
  return {
    invoice_id: w.invoice_id,
    invoice_number: w.invoice_number ?? null,
    vendor: w.vendor_name ?? null,
    total: w.total ?? null,
    currency: w.currency ?? null,
    status: w.outcome,
    mode: w.mode ?? null,
    due_date: w.due_date ?? null,
    latest_run_id: w.latest_run_id ?? null,
    updated_at: w.updated_at,
  };
}

export function toInvoiceList(w: Wire["InvoiceList"]): InvoiceList {
  return { ...w, items: w.items.map(toInvoiceSummary) };
}

export function toOverview(w: Wire["Overview"]): Overview {
  return {
    counts: {
      unique_invoices: w.unique_invoices,
      documents: w.documents,
      runs: w.runs,
      duplicates: w.duplicates,
      ...w.outcomes,
    },
    // The API lists every currency on a current invoice (unpaid ones as 0.00); show only
    // currencies that were actually mock paid, each on its own, never combined.
    mock_paid_totals: Object.fromEntries(
      w.paid_totals.filter((t) => t.paid_count > 0).map((t) => [t.currency, t.amount]),
    ),
    recent_invoices: w.recent_invoices.map(toInvoiceSummary),
  };
}

function toRunSummary(w: Wire["RunSummary"]): RunSummary {
  return {
    run_id: w.run_id,
    status: w.status,
    mode: w.mode,
    source_id: w.source_id,
    original_name: w.original_name ?? null,
    started_at: w.started_at,
    finished_at: w.finished_at,
    prior_run_id: w.prior_run_id,
    retry_of: w.retry_of ?? null,
    evaluation_date: w.evaluation_date ?? null,
    error_code: w.error_code ?? null,
    error_message: w.error_message ?? null,
    provider: w.provider ?? null,
    model: w.model ?? null,
    events: toStageEvents(w.events),
  };
}

const ACTIONS: (keyof AllowedActions)[] = [
  "add_corrected_invoice",
  "correct_extraction",
  "approve_payment",
  "decline_payment",
  "retry",
];

export function toAllowedActions(list: string[]): AllowedActions {
  const set = new Set(list);
  return Object.fromEntries(ACTIONS.map((a) => [a, set.has(a)])) as unknown as AllowedActions;
}

/** Positive aggregated shortfall as a decimal string, using exact integer arithmetic. */
function shortfall(requestedTotal: string | null, available: number | null): string | null {
  if (requestedTotal === null || available === null) return null;
  const m = /^(\d+)(?:\.(\d+))?$/.exec(requestedTotal);
  if (!m || !m[1]) return null;
  const frac = (m[2] ?? "").replace(/0+$/, "");
  if (frac) return null; // fractional quantities are flagged by validation, not here
  const diff = BigInt(m[1]) - BigInt(available);
  return diff > 0n ? diff.toString() : null;
}

export function toInvoiceDetail(w: Wire["InvoiceDetail"]): InvoiceDetail {
  const inv = w.invoice;
  return {
    invoice_id: w.invoice_id,
    invoice_number: w.invoice_number,
    vendor: w.vendor_name,
    status: w.outcome,
    total: inv?.stated?.total ?? null,
    currency: inv?.currency ?? null,
    due_date: inv?.due_date ?? null,
    evaluation_date: w.evaluation_date ?? null,
    mode: (w.mode ?? "offline") as ExecutionMode,
    current_version: w.current_version ?? 1,
    source: w.source
      ? { ...w.source, page_count: w.source.page_count ?? null }
      : null,
    stated: inv?.stated ?? {},
    computed: inv?.computed ?? null,
    normalization_events: w.normalization_events.map((e) => ({ ...e, evidence: e.evidence ?? [] })),
    findings: w.findings.map((f) => ({ ...f, evidence: f.evidence ?? [] })),
    line_items: w.line_items.map((ln) => ({
      item: ln.item,
      requested: ln.quantity,
      available: ln.available,
      unit_price: ln.unit_price,
      line_total: ln.line_total,
      shortfall: shortfall(ln.requested_total, ln.available),
      evidence: ln.evidence,
    })),
    decision: w.decision ? { ...w.decision, reasons: w.decision.reasons ?? [] } : null,
    receipt: w.receipt,
    latest_result: toResult(w.latest_result ?? null),
    versions: w.versions.map((v) => ({
      version: v.version,
      source_id: v.source_id,
      original_name: v.original_name ?? null,
      revision: v.revision ?? null,
      total: v.total ?? null,
      currency: v.currency ?? null,
      created_at: v.created_at,
      receipt: v.receipt ?? null,
      lines: v.lines.map((l) => ({ ...l, evidence: l.evidence ?? [] })),
    })),
    corrections: w.corrections.map((c) => ({
      version: c.to_version,
      field: c.field,
      old_value: c.old_value,
      new_value: c.new_value,
      reason: c.reason,
      reviewer: c.reviewer,
      evidence_location: c.evidence_location,
      created_at: c.created_at,
    })),
    human_reviews: w.human_reviews,
    // The API returns runs oldest first; the UI shows newest first.
    runs: w.runs.map(toRunSummary).reverse(),
    allowed_actions: toAllowedActions(w.allowed_actions),
  };
}

/**
 * Readable lines keyed by the location evidence uses. TXT and PDF anchors already equal
 * evidence locations ("line:9", "page:1,line:4"). CSV evidence points at rows
 * ("row:3,col:Qty"), so CSV lines take their row anchor when lines and rows correspond.
 */
export function toSourceContent(w: Wire["SourceContent"]): SourceContent {
  const rows = w.rows ?? null;
  const lines =
    w.format === "csv" && rows && rows.length === w.lines.length
      ? w.lines.map((ln, i) => ({ location: rows[i]?.anchor ?? ln.anchor, text: ln.text }))
      : w.lines.map((ln) => ({ location: ln.anchor, text: ln.text }));
  return {
    source_id: w.source_id,
    original_name: w.original_name,
    format: w.format,
    lines,
    original_url: w.original_url ?? null,
    preview_limitation: w.preview_limitation ?? null,
  };
}

/**
 * The source line an evidence location points at: "row:3,col:Qty" -> "row:3"; line and
 * page anchors are returned unchanged. JSON/XML paths ("$.items[0]") have no line anchor.
 */
export function lineAnchor(location: string): string {
  const row = /^(row:\d+),col:/.exec(location);
  return row?.[1] ?? location;
}
