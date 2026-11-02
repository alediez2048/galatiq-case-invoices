import { act, fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { InvoiceDetail } from "../api/types";
import * as f from "../test/fixtures";
import * as wire from "../test/wire";
import { renderApp } from "../test/render";

function renderDetail(detail: InvoiceDetail, extra = {}) {
  return renderApp(`/invoices/${detail.invoice_id}`, {
    "GET /api/invoices/:id": () => wire.detail(detail),
    ...extra,
  });
}

const notice = (name: string) => screen.getByRole("region", { name });
const stage = (label: string) =>
  within(screen.getByRole("list", { name: "Workflow stages" })).getByText(label).closest("li");

describe("Invoice detail — 1001 paid (screen 5)", () => {
  it("shows header, stage strip, decision, line items, receipt and download", async () => {
    renderDetail(f.detail1001);
    expect(await screen.findByRole("heading", { level: 1, name: "INV-1001 · Widgets Inc." })).toBeInTheDocument();
    const top = screen.getByRole("heading", { level: 1 }).parentElement!.parentElement!;
    expect(within(top).getByText("Mock paid")).toBeInTheDocument();
    expect(top).toHaveTextContent("USD 5,000.00 · Due Feb 1, 2026 · Offline simulation");
    expect(screen.queryByText(/Overdue/)).not.toBeInTheDocument();

    for (const label of ["Extracted", "Validated", "Approved", "Mock paid"]) {
      expect(stage(label)).toHaveAttribute("data-state", "complete");
    }
    expect(screen.getByRole("heading", { name: "Mock payment complete." })).toBeInTheDocument();

    // Decision tab: offline marked simulated
    const panel = screen.getByRole("tabpanel");
    expect(panel).toHaveTextContent("Approve (simulated)");
    expect(panel).toHaveTextContent("Approved for mock payment");
    expect(panel).toHaveTextContent("Offline simulation · simulated agent decisions");

    const lineTable = within(screen.getByRole("region", { name: "Line items" })).getByRole("table");
    const cells = within(within(lineTable).getAllByRole("row")[1]!).getAllByRole("cell");
    expect(cells.map((c) => c.textContent?.trim())).toEqual([
      "WidgetA",
      "10",
      "15",
      "USD 250.00",
      "USD 2,500.00",
      "Within stock",
    ]);

    const receipt = screen.getByRole("region", { name: "Mock receipt" });
    expect(receipt).toHaveTextContent("rcpt-7f3a1c");
    expect(receipt).toHaveTextContent("USD 5,000.00");
    expect(receipt).toHaveTextContent("No real funds transferred.");

    expect(screen.getByRole("link", { name: "Download result JSON" })).toHaveAttribute(
      "href",
      "/api/invoices/inv-1001/result.json",
    );
    expect(screen.queryByRole("button", { name: /approve/i })).not.toBeInTheDocument();
  });

  it("renders source lines and highlights evidence on hover and focus", async () => {
    const user = userEvent.setup();
    renderDetail({
      ...f.detail1001,
      findings: [
        {
          code: "rounding_tolerated",
          severity: "info",
          evidence: [{ source_id: "src-1001", location: "line:9" }],
          resolved: false,
        },
      ],
    });
    const source = await screen.findByRole("list", { name: "Contents of invoice_1001.txt" });
    expect(within(source).getByText("Vendor: Widgets Inc.")).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Checks" }));
    const ref = screen.getByRole("button", { name: "Source line:9" });
    const line = source.querySelector('[data-location="line:9"]')!;
    expect(line).not.toHaveAttribute("data-highlighted");
    fireEvent.mouseEnter(ref);
    expect(line).toHaveAttribute("data-highlighted", "true");
    fireEvent.mouseLeave(ref);
    expect(line).not.toHaveAttribute("data-highlighted");
    act(() => ref.focus());
    expect(line).toHaveAttribute("data-highlighted", "true");
  });

  it("shows an Overdue warning with the evaluation date", async () => {
    renderDetail({ ...f.detail1001, evaluation_date: "2026-11-01" });
    expect(await screen.findByText(/Overdue — due Feb 1, 2026, evaluated Nov 1, 2026\./)).toBeInTheDocument();
  });

  it("tabs are keyboard operable and show history", async () => {
    const user = userEvent.setup();
    renderDetail(f.detail1001);
    const decision = await screen.findByRole("tab", { name: "Decision" });
    decision.focus();
    await user.keyboard("{ArrowRight}{ArrowRight}");
    const history = screen.getByRole("tab", { name: "History" });
    expect(history).toHaveFocus();
    expect(history).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel")).toHaveTextContent("Invoice details extracted.");
  });

  it("shows provider and model for a live decision", async () => {
    renderDetail({
      ...f.detail1001,
      mode: "live",
      decision: { ...f.detail1001.decision!, mode: "live", provider: "xai", model: "grok-4" },
    });
    const panel = await screen.findByRole("tabpanel");
    expect(panel).toHaveTextContent("Live model · xai / grok-4");
    expect(panel).not.toHaveTextContent("(simulated)");
  });
});

describe("Invoice detail — 1002 rejected (screen 6)", () => {
  it("leads with the blocking reason, shows the shortfall, offers a corrected invoice, never Approve anyway", async () => {
    renderDetail(f.detail1002);
    expect(
      await screen.findByRole("heading", { name: "Payment blocked: requested quantity exceeds available stock." }),
    ).toBeInTheDocument();
    expect(stage("Validated")).toHaveAttribute("data-state", "failed");
    expect(stage("Mock paid")).toHaveAttribute("data-state", "skipped");
    const lineTable = within(screen.getByRole("region", { name: "Line items" })).getByRole("table");
    expect(within(lineTable).getByText(/Exceeds stock by 15/)).toBeInTheDocument();
    expect(screen.getByRole("tabpanel")).toHaveTextContent("High-value review does not resolve the stock mismatch.");
    expect(screen.getByText("Payment: Not attempted.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Add corrected invoice" })).toHaveAttribute("href", "/add?corrects=inv-1002");
    expect(screen.queryByText(/approve anyway/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Mock receipt" })).not.toBeInTheDocument();
  });
});

describe("Invoice detail — fixture acceptance views", () => {
  it("1013: contradictory totals and aggregated stock shortages", async () => {
    renderDetail(f.detail1013);
    const totals = await screen.findByRole("region", { name: "Contradictory totals" });
    expect(totals).toHaveTextContent("Stated total exceeds calculated total by USD 50.00.");
    expect(within(totals).getByRole("table")).toHaveTextContent("TotalUSD 22,562.80USD 22,512.80");
    expect(totals).toHaveTextContent("Payment is blocked");
    const lineTable = within(screen.getByRole("region", { name: "Line items" })).getByRole("table");
    expect(within(lineTable).getByText(/Exceeds stock by 7/)).toBeInTheDocument();
    expect(within(lineTable).getByText(/Exceeds stock by 8/)).toBeInTheDocument();
    expect(within(lineTable).getByText(/Exceeds stock by 4/)).toBeInTheDocument();
  });

  it("1012: normalization events raw → normalized with provenance", async () => {
    const user = userEvent.setup();
    renderDetail(f.detail1012);
    await user.click(await screen.findByRole("tab", { name: "Checks" }));
    const events = screen.getByRole("list", { name: "Normalization events" });
    expect(within(events).getAllByRole("listitem")).toHaveLength(3);
    expect(events).toHaveTextContent("INV 1012");
    expect(events).toHaveTextContent("INV-1012");
    expect(events).toHaveTextContent("26-Jan-2O26");
    expect(events).toHaveTextContent("Provenance: rule:ocr_digit");
    expect(events).toHaveTextContent("Provenance: rule:item_spacing");
  });

  it("1014: EUR shown explicitly and kept under review", async () => {
    renderDetail(f.detail1014);
    expect(await screen.findByRole("heading", { name: "Invoice needs review." })).toBeInTheDocument();
    expect(screen.getByText("This prototype only simulates USD settlement.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1 }).parentElement).toHaveTextContent("EUR 4,125.00");
    expect(screen.queryByRole("region", { name: "Mock receipt" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /approve/i })).not.toBeInTheDocument();
  });
});

describe("Other essential states", () => {
  it("duplicate (1011 PDF after TXT): already processed, distinguishes submission from original", async () => {
    renderDetail(f.detail1011Duplicate);
    await screen.findByRole("heading", { level: 1 });
    const n = notice("Duplicate submission");
    expect(n).toHaveTextContent("Already processed. No additional payment.");
    expect(n).toHaveTextContent("This submissioninvoice_1011.pdf · Duplicate");
    expect(n).toHaveTextContent("Original outcomeinvoice_1011.txt · Mock paid");
    expect(within(n).getByRole("link", { name: "Open original result" })).toHaveAttribute("href", "#run-run-1011-txt");
    expect(screen.getByRole("region", { name: "Mock receipt" })).toHaveTextContent("rcpt-1011");
  });

  it("version conflict: compared totals, lines and payment state", async () => {
    renderDetail(f.detailVersionConflict);
    await screen.findByRole("heading", { level: 1 });
    const n = notice("Version conflict");
    expect(n).toHaveTextContent("Invoice versions differ. Review required.");
    const rows = within(within(n).getByRole("table")).getAllByRole("row");
    expect(rows[1]).toHaveTextContent("1inv_2001.txtUSD 5,000.00WidgetA × 10Not paid");
    expect(rows[2]).toHaveTextContent("2 (this)inv_2001_b.txtUSD 5,250.00WidgetA × 11Not paid");
    expect(n).toHaveTextContent("No automatic replacement.");
  });

  it("revision after payment (1004 revised): specific copy and the prior receipt", async () => {
    renderDetail(f.detail1004Revised);
    await screen.findByRole("heading", { level: 1 });
    const n = notice("Revision after payment");
    expect(n).toHaveTextContent("Earlier version already mock paid. Revised version blocked from additional payment.");
    expect(within(n).getByRole("region", { name: "Prior mock receipt" })).toHaveTextContent("rcpt-1004");
    expect(within(n).getByRole("region", { name: "Prior mock receipt" })).toHaveTextContent("USD 1,890.00");
    expect(screen.queryByText(/no payment has been made/i)).not.toBeInTheDocument();
    expect(screen.getByRole("tabpanel")).toHaveTextContent("Mock paid on an earlier version");
  });

  it("malformed or unsupported input: could not read, specific cause, replace file", async () => {
    renderDetail(f.detailUnreadable);
    await screen.findByRole("heading", { level: 1 });
    const n = notice("Processing failure");
    expect(n).toHaveTextContent("We could not read this invoice.");
    expect(n).toHaveTextContent("The XML is not well-formed (line 3).");
    expect(within(n).getByRole("link", { name: "Replace file" })).toHaveAttribute("href", "/add");
    expect(stage("Extracted")).toHaveAttribute("data-state", "failed");
    expect(screen.queryByRole("region", { name: "Mock receipt" })).not.toBeInTheDocument();
  });

  it("image-only PDF without OCR", async () => {
    renderDetail(f.detailOcr);
    await screen.findByRole("heading", { level: 1 });
    const n = notice("Processing failure");
    expect(n).toHaveTextContent("This PDF needs OCR, which this prototype does not support.");
    expect(n).toHaveTextContent("Submit a text-based version");
  });

  it("oversized input", async () => {
    renderDetail(f.detailOversized);
    await screen.findByRole("heading", { level: 1 });
    expect(notice("Processing failure")).toHaveTextContent("File exceeds the 10 MiB limit.");
  });

  it("missing required fields: names them, invents nothing", async () => {
    renderDetail(f.detailMissingFields);
    await screen.findByRole("heading", { level: 1 });
    const n = notice("Missing required fields");
    expect(n).toHaveTextContent("Vendor and due date are missing.");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("INV-3001 · Vendor missing");
    expect(screen.getByRole("heading", { level: 1 }).parentElement).toHaveTextContent("Due date missing");
  });

  it("contradictory totals", async () => {
    renderDetail(f.detail1013);
    expect(await screen.findByRole("region", { name: "Contradictory totals" })).toHaveTextContent(
      "Stated total exceeds calculated total by USD 50.00.",
    );
  });

  it("live provider unavailable: explicit retry or a separate offline run, no silent fallback", async () => {
    const user = userEvent.setup();
    const { calls } = renderDetail(f.detailProvider, {
      "POST /api/runs/:id/retry": () => ({ run_id: "run-retry-1" }),
    });
    await screen.findByRole("heading", { level: 1 });
    const n = notice("Processing failure");
    expect(n).toHaveTextContent("Model request failed. Payment was not attempted.");
    expect(n).toHaveTextContent("Mode of this run: Live model");
    expect(within(n).getByRole("link", { name: "Run offline as a separate simulation" })).toHaveAttribute(
      "href",
      "/add?mode=offline",
    );
    expect(stage("Approved")).toHaveAttribute("data-state", "failed");
    expect(calls.some((c) => c.method === "POST")).toBe(false);
    await user.click(within(n).getByRole("button", { name: "Retry" }));
    const posts = calls.filter((c) => c.method === "POST");
    expect(posts).toHaveLength(1);
    expect(posts[0]?.url).toBe("/api/runs/run-model_unavailable/retry");
    expect(posts[0]?.headers["Idempotency-Key"]).toMatch(/[0-9a-f-]{36}/);
  });

  it("processing failure: names the stage and offers a safe retry", async () => {
    renderDetail(f.detailProcessing);
    await screen.findByRole("heading", { level: 1 });
    const n = notice("Processing failure");
    expect(n).toHaveTextContent("Processing stopped during validation.");
    expect(n).toHaveTextContent("Validation raised an unexpected error; see the run log.");
    expect(within(n).getByRole("button", { name: "Retry" })).toBeInTheDocument();
    expect(stage("Validated")).toHaveAttribute("data-state", "failed");
  });

  it("empty filtered list and loading history are covered in InvoicesView tests; detail loading shows no fabricated data", async () => {
    renderApp("/invoices/inv-1001", { "GET /api/invoices/:id": () => new Promise(() => {}) });
    expect(await screen.findByText("Loading invoice history…")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { level: 1 })).not.toBeInTheDocument();
  });

  it("not found", async () => {
    renderApp("/invoices/nope");
    expect(await screen.findByRole("alert")).toHaveTextContent("This invoice was not found.");
  });
});
