import { describe, expect, it } from "vitest";
import type { Wire } from "./types";
import {
  eventMessage,
  lineAnchor,
  toInvoiceDetail,
  toOverview,
  toReadiness,
  toRunProgress,
  toSourceContent,
} from "./adapters";
import detail1001 from "../test/real/detail-1001.json";
import detail1007 from "../test/real/detail-1007.json";
import detail1011pdf from "../test/real/detail-1011pdf.json";
import run1001 from "../test/real/run-1001.json";
import source1001 from "../test/real/source-1001.json";
import source1007 from "../test/real/source-1007.json";
import source1011pdf from "../test/real/source-1011pdf.json";

// Captured from the real backend by scripts/export_ui_fixtures.py.
const real = {
  detail: { "1001": detail1001, "1007": detail1007, "1011pdf": detail1011pdf } as Record<
    string,
    Wire["InvoiceDetail"]
  >,
  source: { "1001": source1001, "1007": source1007, "1011pdf": source1011pdf } as Record<
    string,
    Wire["SourceContent"]
  >,
};

describe("adapters over real API responses", () => {
  it("maps the 1001 detail to the view model without inventing values", () => {
    const d = toInvoiceDetail(real.detail["1001"]!);
    expect(d.invoice_number).toBe("INV-1001");
    expect(d.vendor).toBe("Widgets Inc.");
    expect(d.status).toBe("paid_mock");
    expect(d.total).toBe("5000.00");
    expect(d.currency).toBe("USD");
    expect(d.due_date).toBe("2026-02-01");
    expect(d.evaluation_date).toBe("2026-01-31");
    expect(d.mode).toBe("offline");
    expect(d.source?.original_name).toBe("invoice_1001.txt");
    expect(d.line_items.map((l) => [l.item, l.requested, l.available, l.shortfall])).toEqual([
      ["WidgetA", "10", 15, null],
      ["WidgetB", "5", 10, null],
    ]);
    expect(d.receipt?.amount).toBe("5000.00");
    expect(d.latest_result?.status).toBe("paid_mock");
    expect(d.runs[0]?.events.map((e) => e.event)).toEqual(run1001.events.map((e) => e.event));
    expect(d.allowed_actions.retry).toBe(false);
  });

  it.each(["1001", "1011pdf", "1007"])(
    "every line-addressed evidence location of %s resolves to a source line",
    (key) => {
      const d = toInvoiceDetail(real.detail[key]!);
      const lines = new Set(toSourceContent(real.source[key]!).lines.map((l) => l.location));
      const refs = [
        ...d.findings.flatMap((f) => f.evidence),
        ...d.normalization_events.flatMap((e) => e.evidence),
        ...d.line_items.flatMap((l) => l.evidence),
      ].filter((r) => r.source_id === d.source?.source_id && !r.location.startsWith("$"));
      expect(refs.length).toBeGreaterThan(0);
      for (const r of refs) expect(lines).toContain(lineAnchor(r.location));
    },
  );

  it("PDF lines keep page:N,line:M anchors and report the preview limitation", () => {
    const s = toSourceContent(real.source["1011pdf"]!);
    expect(s.lines[0]?.location).toBe("page:1,line:1");
    expect(s.preview_limitation).toMatch(/extracted/);
    expect(s.original_url).toMatch(/^\/api\/sources\/.+\/original$/);
  });

  it("CSV lines take row anchors so row:N,col:X evidence highlights its row", () => {
    const s = toSourceContent(real.source["1007"]!);
    expect(s.lines[0]?.location).toBe("row:1");
    expect(lineAnchor("row:3,col:Qty")).toBe("row:3");
    expect(lineAnchor("page:1,line:4")).toBe("page:1,line:4");
  });

  it("every persisted event of the 1001 run has a specific message", () => {
    const run = toRunProgress(run1001 as Wire["RunView"]);
    expect(run.events.map((e) => e.sequence)).toEqual(run.events.map((_, i) => i + 1));
    for (const e of run.events) expect(e.message).not.toMatch(/^[a-z]+: /);
    expect(run.events.find((e) => e.event === "recommendation")?.message).toBe(
      "Recommendation (simulated): approve.",
    );
  });
});

describe("adapters — shape rules", () => {
  it("overview keeps currencies separate and drops never-paid ones", () => {
    const o = toOverview({
      documents: 4,
      unique_invoices: 4,
      runs: 4,
      duplicates: 0,
      outcomes: {
        paid_mock: 2,
        needs_review: 1,
        awaiting_human_approval: 0,
        rejected: 1,
        failed: 0,
        processing: 0,
      },
      paid_totals: [
        { currency: "EUR", amount: "0.00", paid_count: 0 },
        { currency: "USD", amount: "6890.00", paid_count: 2 },
      ],
      recent_invoices: [],
    });
    expect(o.mock_paid_totals).toEqual({ USD: "6890.00" });
    expect(o.counts.paid_mock).toBe(2);
  });

  it("readiness exposes live availability and its reason only", () => {
    const r = toReadiness({
      modes: {
        offline: { available: true, reason: null },
        live: { available: false, reason: "XAI_API_KEY is not set" },
      },
      live_settings_present: false,
      inventory_seeded: true,
      database_path: "x.db",
      schema_version: 5,
    });
    expect(r.live_available).toBe(false);
    expect(r.live_unavailable_reason).toBe("XAI_API_KEY is not set");
  });

  it("names Phase 3 model steps with the mockup copy", () => {
    expect(eventMessage("model", "model_call", { agent: "ingestion", step: "extraction_repair", attempt: 2 })).toBe(
      "Checking an extraction issue — attempt 2 of 2.",
    );
    expect(eventMessage("model", "model_call", { agent: "approval", step: "critique", attempt: 1 })).toBe(
      "Checking the recommendation against policy.",
    );
    expect(eventMessage("x", "brand_new_event", {})).toBe("x: brand new event.");
  });
});
