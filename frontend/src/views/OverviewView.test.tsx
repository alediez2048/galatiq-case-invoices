import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { emptyOverviewFixture, overviewFixture, inv1001 } from "../test/fixtures";
import { renderApp } from "../test/render";

const metric = (key: string) => document.querySelector(`[data-metric="${key}"]`) as HTMLElement;

describe("Overview with results (P5-03 data: 1001, 1004, 1002, 1014)", () => {
  it("matches mockup screen 4 values", async () => {
    renderApp("/");
    expect(await screen.findByRole("heading", { level: 1, name: "Invoice overview" })).toBeInTheDocument();
    expect(screen.getByText("A clear view of every decision.")).toBeInTheDocument();

    const cards = within(screen.getByRole("list", { name: "Invoice counts" })).getAllByRole("listitem");
    expect(cards).toHaveLength(4);
    expect(metric("unique")).toHaveTextContent("4Unique invoices");
    expect(metric("paid_mock")).toHaveTextContent("2Mock paid");
    expect(metric("needs_review")).toHaveTextContent("1Needs review");
    expect(metric("rejected")).toHaveTextContent("1Rejected");

    const totals = screen.getByLabelText("Mock-paid totals");
    expect(totals).toHaveTextContent("Mock paid: USD 6,890.00");
    expect(totals).toHaveTextContent("No real funds transferred.");
    expect(totals).not.toHaveTextContent("EUR");

    const table = screen.getByRole("table", { name: "Recent invoices" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows.map((r) => within(r).getAllByRole("cell").slice(0, 4).map((c) => c.textContent))).toEqual([
      ["INV-1001", "Widgets Inc.", "USD 5,000.00", "Mock paid"],
      ["INV-1004", "Precision Parts Ltd.", "USD 1,890.00", "Mock paid"],
      ["INV-1002", "Gadgets Co.", "USD 15,000.00", "Rejected"],
      ["INV-1014", "TechParts International", "EUR 4,125.00", "Needs review"],
    ]);
    expect(within(rows[0]!).getAllByRole("cell")[2]).toHaveClass("num");
    expect(within(table).getByRole("link", { name: "Open INV-1001" })).toHaveAttribute("href", "/invoices/inv-1001");
    expect(screen.getByRole("link", { name: "View all invoices" })).toHaveAttribute("href", "/invoices");
    expect(screen.queryByTestId("wave-mesh")).not.toBeInTheDocument();
  });

  it("adds a Failed card as soon as a failed invoice exists, keeping the other four", async () => {
    renderApp("/", {
      "GET /api/overview": () => ({
        ...overviewFixture,
        counts: { ...overviewFixture.counts, unique_invoices: 5, failed: 1 },
      }),
    });
    expect(await screen.findByText("Failed", { selector: ".metric__label" })).toBeInTheDocument();
    expect(within(screen.getByRole("list", { name: "Invoice counts" })).getAllByRole("listitem")).toHaveLength(5);
    expect(metric("failed")).toHaveTextContent("1Failed");
  });

  it("adds an Awaiting approval card when non-zero", async () => {
    renderApp("/", {
      "GET /api/overview": () => ({
        ...overviewFixture,
        counts: { ...overviewFixture.counts, awaiting_human_approval: 1 },
      }),
    });
    expect(await screen.findByText("Awaiting approval", { selector: ".metric__label" })).toBeInTheDocument();
  });

  it("lists mock-paid totals per currency, never combined", async () => {
    renderApp("/", {
      "GET /api/overview": () => ({ ...overviewFixture, mock_paid_totals: { USD: "6890.00", EUR: "100.00" } }),
    });
    const totals = await screen.findByLabelText("Mock-paid totals");
    expect(totals).toHaveTextContent("Mock paid: EUR 100.00 · USD 6,890.00");
  });

  it("renders whatever the API returns (no hard-coded rows)", async () => {
    renderApp("/", {
      "GET /api/overview": () => ({
        ...overviewFixture,
        counts: { ...overviewFixture.counts, unique_invoices: 1, paid_mock: 1, needs_review: 0, rejected: 0 },
        mock_paid_totals: { USD: "5000.00" },
        recent_invoices: [inv1001],
      }),
    });
    await screen.findByText("Mock paid: USD 5,000.00", { exact: false });
    expect(screen.queryByText("Gadgets Co.")).not.toBeInTheDocument();
    expect(metric("unique")).toHaveTextContent("1Unique invoices");
  });

  it("shows the loading copy without fabricated rows", async () => {
    renderApp("/", { "GET /api/overview": () => new Promise(() => {}) });
    expect(await screen.findByText("Loading invoice history…")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});

describe("Empty workspace", () => {
  const empty = { "GET /api/overview": () => emptyOverviewFixture };

  it("shows the hero, actions, decorative mesh and empty copy", async () => {
    renderApp("/", empty);
    expect(await screen.findByRole("heading", { level: 1, name: /From invoice to decision\.\s*Every check visible\./ })).toBeInTheDocument();
    expect(screen.getByText("Extract details. Check inventory. Review the decision. Simulate the payment.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Upload invoice" })).toHaveAttribute("href", "/add");
    expect(screen.getByRole("button", { name: "Try a sample" })).toBeInTheDocument();
    expect(screen.getByText("No invoices processed yet.")).toBeInTheDocument();
    expect(screen.getByText("Start with a sample to explore the workflow.")).toBeInTheDocument();
    expect(screen.getByTestId("wave-mesh")).toHaveAttribute("aria-hidden", "true");
  });

  it("Try a sample opens a selection panel and leads to add-invoice without processing", async () => {
    const user = userEvent.setup();
    const { router, calls } = renderApp("/", empty);
    await user.click(await screen.findByRole("button", { name: "Try a sample" }));
    const dialog = await screen.findByRole("dialog", { name: "Try a sample" });
    const choice = await within(dialog).findByRole("radio", { name: /Stock mismatch/ });
    expect(within(dialog).getByText("INV-1002 · invoice_1002.txt")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: /Continue/ })).toBeDisabled();
    await user.click(choice);
    await user.click(within(dialog).getByRole("button", { name: /Continue/ }));
    expect(router.state.location.pathname).toBe("/add");
    expect(router.state.location.search).toBe("?sample=invoice_1002.txt");
    expect(await screen.findByText("invoice_1002.txt")).toBeInTheDocument();
    expect(calls.filter((c) => c.method !== "GET")).toEqual([]);
  });

  it("closes the sample panel with Escape and returns focus to the trigger", async () => {
    const user = userEvent.setup();
    renderApp("/", empty);
    const trigger = await screen.findByRole("button", { name: "Try a sample" });
    await user.click(trigger);
    await screen.findByRole("dialog");
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });
});
