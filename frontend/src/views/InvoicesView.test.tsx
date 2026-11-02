import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { fourInvoices } from "../test/fixtures";
import { listFrom } from "../test/mockApi";
import { renderApp } from "../test/render";

const rowsOf = () =>
  within(screen.getByRole("table", { name: "Invoices" }))
    .getAllByRole("row")
    .slice(1)
    .map((r) => within(r).getAllByRole("cell")[0]?.textContent);

describe("Invoices list", () => {
  it("lists invoice, vendor, right-aligned total with currency, outcome, mode and open", async () => {
    renderApp("/invoices");
    await screen.findByRole("table", { name: "Invoices" });
    const table = screen.getByRole("table", { name: "Invoices" });
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent)).toEqual([
      "Invoice",
      "Vendor",
      "Total",
      "Outcome",
      "Mode",
      "Open",
    ]);
    expect(within(table).getByRole("columnheader", { name: "Total" })).toHaveClass("num");
    expect(rowsOf()).toEqual(["INV-1001", "INV-1004", "INV-1002", "INV-1014"]);
    expect(within(table).getByText("EUR 4,125.00")).toHaveClass("num");
    // Narrow-width summary cards carry the same invoices.
    expect(within(screen.getByRole("list", { name: "Invoices" })).getAllByRole("listitem")).toHaveLength(4);
  });

  it("filters by outcome through the API", async () => {
    const user = userEvent.setup();
    const { calls } = renderApp("/invoices");
    await screen.findByRole("table", { name: "Invoices" });
    await user.click(screen.getByRole("button", { name: "Rejected" }));
    expect(screen.getByRole("button", { name: "Rejected" })).toHaveAttribute("aria-pressed", "true");
    await screen.findByText("Gadgets Co.", { selector: "td" });
    expect(rowsOf()).toEqual(["INV-1002"]);
    expect(calls.at(-1)?.url).toBe("/api/invoices?status=rejected&page=1");
  });

  it("filters by mode and search", async () => {
    const user = userEvent.setup();
    const { calls } = renderApp("/invoices");
    await screen.findByRole("table", { name: "Invoices" });
    await user.selectOptions(screen.getByLabelText("Mode"), "offline");
    await user.type(screen.getByLabelText("Search invoices"), "tech");
    expect(await screen.findByText("TechParts International", { selector: "td" })).toBeInTheDocument();
    expect(rowsOf()).toEqual(["INV-1014"]);
    expect(calls.at(-1)?.url).toBe("/api/invoices?mode=offline&q=tech&page=1");
  });

  it("shows the empty filtered state with Clear filters", async () => {
    const user = userEvent.setup();
    renderApp("/invoices?mode=live");
    expect(await screen.findByText("No invoices match these filters.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Clear filters" }));
    await screen.findByRole("table", { name: "Invoices" });
    expect(rowsOf()).toHaveLength(4);
    expect(screen.getByLabelText("Mode")).toHaveValue("");
  });

  it("shows loading copy without fabricated rows", async () => {
    renderApp("/invoices", { "GET /api/invoices": () => new Promise(() => {}) });
    expect(await screen.findByText("Loading invoice history…")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("explains a load failure with a retry", async () => {
    renderApp("/invoices", {
      "GET /api/invoices": () =>
        new Response(JSON.stringify({ code: "internal", message: "Database is locked." }), { status: 500 }),
    });
    expect(await screen.findByRole("alert")).toHaveTextContent("Database is locked.");
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});

describe("Needs review (placeholder until P5-09)", () => {
  it("requests only needs_review invoices", async () => {
    const { calls } = renderApp("/review", { "GET /api/invoices": listFrom([...fourInvoices]) });
    expect(await screen.findByText("TechParts International", { selector: "td" })).toBeInTheDocument();
    expect(calls.find((c) => c.url.startsWith("/api/invoices"))?.url).toBe(
      "/api/invoices?status=needs_review&page=1",
    );
  });
});
