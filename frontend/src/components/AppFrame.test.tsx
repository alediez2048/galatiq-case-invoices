import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { readinessFixture } from "../test/fixtures";
import { renderApp } from "../test/render";

describe("App frame", () => {
  it("renders header wordmark, mode badge, Setup, nav and footer", async () => {
    renderApp("/");
    const banner = screen.getByRole("banner");
    expect(within(banner).getByRole("link", { name: /GALATIQ \/ Invoice Operations/ })).toBeInTheDocument();
    expect(within(banner).getByLabelText("Workspace mode: Offline simulation")).toHaveTextContent(
      "Offline simulation",
    );
    expect(within(banner).getByRole("link", { name: "Setup" })).toHaveAttribute("href", "/setup");

    const nav = screen.getByRole("navigation", { name: "Primary" });
    expect(within(nav).getByRole("link", { name: /^Overview/ })).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("link", { name: /^Invoices/ })).toBeInTheDocument();
    expect(within(nav).getByRole("link", { name: /^Needs review/ })).toBeInTheDocument();
    expect(await within(nav).findByLabelText("4 invoices")).toBeInTheDocument();

    expect(screen.getByRole("contentinfo")).toHaveTextContent(
      "Case-study prototype · Local workspace · All payments are simulated",
    );
    expect(screen.getByRole("main")).toBeInTheDocument();
  });

  it.each(["/", "/invoices", "/review", "/invoices/inv-1001", "/setup", "/add"])(
    "keeps the mode badge visible on %s",
    async (path) => {
      renderApp(path);
      expect(await screen.findByLabelText(/Workspace mode:/)).toBeVisible();
    },
  );

  it("navigates between the three views", async () => {
    const user = userEvent.setup();
    const { router } = renderApp("/");
    await user.click(screen.getByRole("link", { name: /^Invoices/ }));
    expect(router.state.location.pathname).toBe("/invoices");
    await user.click(screen.getByRole("link", { name: /^Needs review/ }));
    expect(router.state.location.pathname).toBe("/review");
    expect(await screen.findByRole("heading", { level: 1, name: "Needs review" })).toBeInTheDocument();
  });

  it("badge follows the mode chosen in Setup; live is refused when not configured", async () => {
    const user = userEvent.setup();
    renderApp("/setup", {
      "GET /api/settings/readiness": () => ({ ...readinessFixture, live_available: true, live_model: "grok-4" }),
    });
    const live = await screen.findByRole("radio", { name: /Live model/ });
    await screen.findByText(/Configured · grok-4/);
    await user.click(live);
    expect(screen.getByLabelText("Workspace mode: Live model")).toBeInTheDocument();
  });

  it("disables live in Setup with the reason when it is not configured", async () => {
    renderApp("/setup");
    const live = await screen.findByRole("radio", { name: /Live model/ });
    await screen.findByText("Not configured");
    expect(live).toBeDisabled();
    expect(screen.getByText(/Unavailable: XAI_API_KEY is not set/)).toBeInTheDocument();
  });

  it("shows the readiness notice only when actionable", async () => {
    window.localStorage.setItem("galatiq.workspaceMode", "live");
    renderApp("/");
    expect(await screen.findByRole("status", { name: "Setup required" })).toHaveTextContent(
      "Live model is selected but not configured: XAI_API_KEY is not set",
    );
  });

  it("shows no readiness notice when everything is ready", async () => {
    renderApp("/");
    await screen.findByRole("heading", { name: "Invoice overview" });
    expect(screen.queryByRole("status", { name: "Setup required" })).not.toBeInTheDocument();
  });

  it("warns when inventory is not set up", async () => {
    renderApp("/", { "GET /api/settings/readiness": () => ({ ...readinessFixture, inventory_seeded: false }) });
    expect(await screen.findByRole("status", { name: "Setup required" })).toHaveTextContent(
      "Inventory is not set up.",
    );
  });
});
