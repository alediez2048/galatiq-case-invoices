/**
 * Test-only encoders: view-model fixtures -> wire responses (generated types), so fixture
 * routes serve exactly what the backend serves and every response goes through adapters.ts.
 * Typed against `Wire`, so a backend contract change fails typecheck here too.
 */
import type {
  InvoiceDetail,
  InvoiceList,
  InvoiceSummary,
  Overview,
  Readiness,
  RunSummary,
  Sample,
  SourceContent,
  StageEvent,
  Wire,
} from "../api/types";

export function readiness(r: Readiness): Wire["Readiness"] {
  return {
    modes: {
      offline: { available: r.offline_available, reason: null },
      live: { available: r.live_available, reason: r.live_unavailable_reason },
    },
    live_settings_present: r.live_settings_present,
    inventory_seeded: r.inventory_seeded,
    database_path: r.db_path,
    schema_version: r.schema_version,
    live_model: r.live_model,
  };
}

export const samples = (s: Sample[]): Wire["Sample"][] => s.map((x) => ({ ...x }));

export function summary(i: InvoiceSummary): Wire["InvoiceSummary"] {
  return {
    invoice_id: i.invoice_id,
    vendor_name: i.vendor,
    invoice_number: i.invoice_number,
    total: i.total,
    currency: i.currency,
    due_date: i.due_date,
    outcome: i.status,
    mode: i.mode,
    latest_run_id: i.latest_run_id,
    current_version: 1,
    updated_at: i.updated_at,
  };
}

export const list = (l: InvoiceList): Wire["InvoiceList"] => ({ ...l, items: l.items.map(summary) });

export function overview(o: Overview): Wire["Overview"] {
  const { unique_invoices, documents, runs, duplicates, ...outcomes } = o.counts;
  return {
    unique_invoices,
    documents,
    runs,
    duplicates,
    outcomes,
    paid_totals: Object.entries(o.mock_paid_totals).map(([currency, amount]) => ({
      currency,
      amount,
      paid_count: 1,
    })),
    recent_invoices: o.recent_invoices.map(summary),
  };
}

export function events(e: StageEvent[]): Wire["AuditEvent"][] {
  return e.map((x) => ({ stage: x.stage, event: x.event, payload: x.payload, created_at: x.at }));
}

function run(r: RunSummary): Wire["RunSummary"] {
  return { ...r, events: events(r.events) };
}

/**
 * The review actions a view-model detail implies: its own `review_actions`, otherwise built
 * from the detail-page booleans (null when none is set, as for a backend that sent none).
 */
function reviewActions(d: InvoiceDetail): Wire["AllowedActions"] | null {
  if (d.review_actions) return d.review_actions as Wire["AllowedActions"];
  const a = d.allowed_actions;
  const allowed = [
    a.correct_extraction && "correct",
    a.approve_payment && "approve",
    a.decline_payment && "decline",
    a.add_corrected_invoice && "submit_corrected",
  ].filter((x): x is Wire["AllowedActions"]["allowed"][number] => typeof x === "string");
  if (allowed.length === 0) return null;
  return { invoice_id: d.invoice_id, status: d.status, current_version: d.current_version, allowed, refused: {} };
}

export function detail(d: InvoiceDetail): Wire["InvoiceDetail"] {
  return {
    invoice_id: d.invoice_id,
    outcome: d.status,
    current_version: d.current_version,
    vendor_name: d.vendor,
    invoice_number: d.invoice_number,
    mode: d.mode,
    latest_run_id: d.runs[0]?.run_id ?? null,
    decision_run_id: d.runs[0]?.run_id ?? null,
    source_id: d.source?.source_id ?? null,
    source: d.source,
    evaluation_date: d.evaluation_date,
    latest_result: d.latest_result,
    invoice: {
      source_id: d.source?.source_id ?? "src",
      vendor_name: d.vendor,
      invoice_number: d.invoice_number,
      due_date: d.due_date,
      currency: d.currency,
      stated: { ...d.stated, total: d.total },
      computed: d.computed,
      lines: [],
      normalization_events: d.normalization_events,
    },
    normalization_events: d.normalization_events,
    findings: d.findings,
    line_items: d.line_items.map((ln) => ({
      item: ln.item,
      quantity: ln.requested,
      unit_price: ln.unit_price,
      line_total: ln.line_total,
      requested_total:
        ln.shortfall && ln.available !== null
          ? String(BigInt(ln.shortfall) + BigInt(ln.available))
          : ln.requested,
      available: ln.available,
      evidence: ln.evidence,
    })),
    decision: d.decision,
    receipt: d.receipt,
    versions: d.versions.map((v) => ({
      version: v.version,
      parent_version: v.version > 1 ? v.version - 1 : null,
      origin: v.version > 1 ? "revision" : "original",
      source_id: v.source_id,
      original_name: v.original_name,
      revision: v.revision,
      total: v.total,
      currency: v.currency,
      lines: v.lines,
      receipt: v.receipt,
      created_at: v.created_at,
    })),
    corrections: d.corrections.map((c) => ({
      from_version: c.version - 1,
      to_version: c.version,
      field: c.field,
      old_value: c.old_value,
      new_value: c.new_value ?? "",
      evidence_location: c.evidence_location,
      reviewer: c.reviewer,
      reason: c.reason,
      created_at: c.created_at,
    })),
    human_reviews: d.human_reviews,
    // View models are newest first; the API sends oldest first.
    runs: [...d.runs].reverse().map(run),
    allowed_actions: d.allowed_actions.retry ? ["retry"] : [],
    review_actions: reviewActions(d),
  };
}

export function source(s: SourceContent): Wire["SourceContent"] {
  return {
    source_id: s.source_id,
    content_hash: "0".repeat(64),
    original_name: s.original_name,
    format: s.format,
    size_bytes: 0,
    page_count: null,
    lines: s.lines.map((l) => ({ anchor: l.location, text: l.text })),
    rows: null,
    original_url: s.original_url,
    preview_limitation: s.preview_limitation,
  };
}
