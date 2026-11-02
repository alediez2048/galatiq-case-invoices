import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Wire } from "../api/types";
import detail1001 from "../test/real/detail-1001.json";
import run1001 from "../test/real/run-1001.json";
import source1001 from "../test/real/source-1001.json";
import { renderApp } from "../test/render";

const realRun = run1001 as Wire["RunView"];

/** The persisted 1001 run as it looked after its first `n` audit events. */
function prefix(n: number): Wire["RunView"] {
  return { ...realRun, events: realRun.events.slice(0, n), terminal: false, result: null, finished_at: null };
}

const stages = () =>
  within(screen.getByRole("list", { name: "Processing stages" }))
    .getAllByRole("listitem")
    .map((li) => `${li.textContent?.replace(/:.*/, "")}=${li.getAttribute("data-state")}`);

const completed = () =>
  screen.queryByRole("list", { name: "Completed steps" })
    ? within(screen.getByRole("list", { name: "Completed steps" }))
        .getAllByRole("listitem")
        .map((li) => li.textContent?.trim())
    : [];

beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }));
afterEach(() => vi.useRealTimers());

const poll = () => act(() => vi.advanceTimersByTimeAsync(500));

describe("Processing view (P5-07, screen 3)", () => {
  it("stage display for an offline 1001 run follows the persisted event sequence, then opens the detail", async () => {
    // Serve the real run one persisted event at a time, then the terminal run.
    const snapshots = [...realRun.events.map((_, i) => prefix(i + 1)), realRun];
    let polls = 0;
    const { calls, router } = renderApp(`/runs/${realRun.run_id}`, {
      "GET /api/runs/:id": () => snapshots[Math.min(polls++, snapshots.length - 1)],
      "GET /api/invoices/:id": () => detail1001,
      "GET /api/sources/:id/content": () => source1001,
    });

    expect(await screen.findByRole("heading", { name: "Processing invoice_1001.txt" })).toBeInTheDocument();
    const panel = screen.getByRole("region", { name: "Processing invoice_1001.txt" });
    expect(within(panel).getByText("Offline simulation")).toBeInTheDocument();
    // 1: received
    expect(stages()).toEqual(["Extract details=active", "Check inventory=pending", "Review=pending", "Pay=pending"]);
    expect(screen.getByText("Extracting invoice details.")).toBeInTheDocument();
    expect(screen.getByText("Payment has not been attempted.")).toBeInTheDocument();

    await poll(); // 2: extracted
    expect(stages()).toEqual(["Extract details=complete", "Check inventory=active", "Review=pending", "Pay=pending"]);
    expect(screen.getByText("Checking requested quantities against local inventory.")).toBeInTheDocument();

    await poll(); // 3: validated
    expect(stages()).toEqual(["Extract details=complete", "Check inventory=complete", "Review=active", "Pay=pending"]);
    expect(screen.getByText("Preparing the simulated recommendation.")).toBeInTheDocument();

    await poll(); // 4: recommendation
    expect(screen.getByText("Checking the recommendation against policy.")).toBeInTheDocument();
    await poll(); // 5: critique
    await poll(); // 6: decision
    expect(stages()).toEqual(["Extract details=complete", "Check inventory=complete", "Review=complete", "Pay=active"]);
    expect(screen.getByText("Payment has not been attempted.")).toBeInTheDocument();

    await poll(); // 7: payment_succeeded
    expect(stages()).toEqual(["Extract details=complete", "Check inventory=complete", "Review=complete", "Pay=complete"]);
    expect(screen.getByText("Mock payment recorded. No real funds transferred.", { selector: ".payment-line" })).toBeInTheDocument();

    await poll(); // 8: paid
    await poll(); // 9: finished (bookkeeping, not listed)
    expect(completed()).toEqual([
      "Document received: invoice_1001.txt.",
      "Invoice details extracted.",
      "Required fields, totals and inventory checked.",
      "Recommendation (simulated): approve.",
      "Critique (simulated) agreed with the recommendation.",
      "Policy result: approved.",
      `Mock payment recorded (receipt ${realRun.events[6]!.payload.receipt_id as string}). No real funds transferred.`,
      `Mock payment recorded (receipt ${realRun.events[7]!.payload.receipt_id as string}). No real funds transferred.`,
    ]);
    expect(completed()).toHaveLength(realRun.events.length - 1);

    await poll(); // terminal
    await waitFor(() => expect(router.state.location.pathname).toBe(`/invoices/${realRun.invoice_id}`));
    expect(await screen.findByRole("heading", { level: 1, name: "INV-1001 · Widgets Inc." })).toBeInTheDocument();
    expect(calls.filter((c) => c.method !== "GET")).toHaveLength(0);
  });

  it("polling stops at a terminal run and never posts (refresh-safe)", async () => {
    const failed: Wire["RunView"] = {
      ...realRun,
      invoice_id: null,
      status: "failed",
      stage: "ingestion",
      error_code: "xml_invalid",
      error_message: "The XML is not well-formed (line 3).",
      events: [realRun.events[0]!, { stage: "ingestion", event: "extraction_failed", payload: { error_code: "xml_invalid" }, created_at: "2026-11-01T00:00:00Z" }],
      result: null,
    };
    const { calls } = renderApp("/runs/run-x", { "GET /api/runs/:id": () => failed });
    expect(await screen.findByText("We could not read this invoice.")).toBeInTheDocument();
    expect(screen.getByText("The XML is not well-formed (line 3).")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Replace file" })).toHaveAttribute("href", "/add");
    expect(stages()).toEqual(["Extract details=failed", "Check inventory=skipped", "Review=skipped", "Pay=skipped"]);
    expect(screen.getByText("Payment was not attempted.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
    await poll();
    await poll();
    expect(calls.filter((c) => c.url.startsWith("/api/runs/"))).toHaveLength(1);
    expect(calls.filter((c) => c.method !== "GET")).toHaveLength(0);
  });

  const liveFailure: Wire["RunView"] = {
    ...realRun,
    run_id: "run-live",
    mode: "live",
    status: "failed",
    stage: "approval",
    error_code: "model_unavailable",
    error_message: "The model provider returned 503.",
    events: realRun.events.slice(0, 3),
    result: null,
  };

  it("live provider failure: explains, offers enabled Retry and a separate offline run, substitutes nothing", async () => {
    const { calls, router } = renderApp("/runs/run-live", { "GET /api/runs/:id": () => liveFailure });
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Model request failed. Payment was not attempted.");
    expect(alert).toHaveTextContent("Mode of this run: Live model");
    expect(within(alert).getByRole("button", { name: "Retry" })).toBeEnabled();
    expect(within(alert).getByRole("button", { name: "Run offline as a separate simulation" })).toBeEnabled();
    expect(stages()).toEqual(["Extract details=complete", "Check inventory=complete", "Review=failed", "Pay=skipped"]);
    expect(router.state.location.pathname).toBe("/runs/run-live");
    expect(calls.filter((c) => c.method !== "GET")).toHaveLength(0);
  });

  it.each([
    ["Retry", "retry", "run-retry-1"],
    ["Run offline as a separate simulation", "run_offline", "run-offline-1"],
  ])("%s posts one explicit retry (action %s) and follows the new linked run", async (name, action, newRun) => {
    const bodies: unknown[] = [];
    const { calls, router } = renderApp("/runs/run-live", {
      "GET /api/runs/:id": (url: URL) =>
        url.pathname.endsWith("/run-live") ? liveFailure : { ...realRun, run_id: newRun },
      "POST /api/runs/:id/retry": (_url: URL, init?: RequestInit) => {
        bodies.push(JSON.parse(String(init?.body)));
        return { run_id: newRun, status: "received", mode: action === "retry" ? "live" : "offline", idempotent_replay: false };
      },
      "GET /api/invoices/:id": () => detail1001,
      "GET /api/sources/:id/content": () => source1001,
    });
    const alert = await screen.findByRole("alert");
    const button = within(alert).getByRole("button", { name });
    fireEvent.click(button);
    fireEvent.click(button);
    await waitFor(() => expect(router.state.location.pathname).not.toBe("/runs/run-live"));
    const posts = calls.filter((c) => c.method === "POST");
    expect(posts).toHaveLength(1);
    expect(posts[0]?.url).toBe("/api/runs/run-live/retry");
    expect(posts[0]?.headers["Idempotency-Key"]).toMatch(/[0-9a-f-]{36}/);
    expect(bodies).toEqual([{ action }]);
  });

  it("a refused retry shows the server's reason and stays on the failed run", async () => {
    const { router } = renderApp("/runs/run-live", {
      "GET /api/runs/:id": () => liveFailure,
      "POST /api/runs/:id/retry": () =>
        new Response(
          JSON.stringify({
            code: "already_paid",
            message: "Another run already paid this invoice. No additional payment.",
            details: { reason: "already_paid", run_id: "run-live", receipt_id: "rcpt-1" },
          }),
          { status: 409, headers: { "Content-Type": "application/json" } },
        ),
    });
    const alert = await screen.findByRole("alert");
    fireEvent.click(within(alert).getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Another run already paid this invoice. No additional payment.")).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/runs/run-live");
  });

  it("a non-model failure that can only be retried offers no offline simulation", async () => {
    const crashed: Wire["RunView"] = {
      ...liveFailure,
      mode: "offline",
      error_code: "unexpected_error",
      error_message: "Validation raised an unexpected error.",
      result: { ...(realRun.result as NonNullable<Wire["RunView"]["result"]>), status: "failed", errors: ["unexpected_error"], recoverable: true, next_actions: ["retry"] },
    };
    renderApp("/runs/run-live", { "GET /api/runs/:id": () => crashed });
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByRole("button", { name: "Retry" })).toBeEnabled();
    expect(within(alert).queryByRole("button", { name: "Run offline as a separate simulation" })).not.toBeInTheDocument();
  });

  it("a duplicate submission opens the existing invoice", async () => {
    const dup: Wire["RunView"] = {
      ...realRun,
      status: "duplicate",
      prior_run_id: "run-original",
      events: [realRun.events[0]!, { stage: "service", event: "duplicate", payload: { prior_run_id: "run-original" }, created_at: "2026-11-01T00:00:00Z" }],
    };
    const { router } = renderApp("/runs/run-dup", {
      "GET /api/runs/:id": () => dup,
      "GET /api/invoices/:id": () => detail1001,
      "GET /api/sources/:id/content": () => source1001,
    });
    await waitFor(() => expect(router.state.location.pathname).toBe(`/invoices/${realRun.invoice_id}`));
  });

  it("an unknown run says so", async () => {
    renderApp("/runs/nope");
    expect(await screen.findByRole("alert")).toHaveTextContent("This run was not found.");
  });
});

describe("Processing view announcements (P5-10)", () => {
  it("announces completion once in a status region and leaves failures to the alert", async () => {
    let polls = 0;
    renderApp(`/runs/${realRun.run_id}`, {
      "GET /api/runs/:id": () => (polls++ < 1 ? prefix(2) : realRun),
      "GET /api/invoices/:id": () => detail1001,
      "GET /api/sources/:id/content": () => source1001,
    });
    const announcer = await screen.findByTestId("run-announcer");
    expect(announcer).toHaveAttribute("role", "status");
    expect(announcer).toBeEmptyDOMElement();
    expect(screen.getByText("Checking requested quantities against local inventory.")).toHaveAttribute(
      "aria-live",
      "polite",
    );
  });
});
