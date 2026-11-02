import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { ReviewQueue } from "../api/review";
import { REVIEWER_KEY } from "../review/reviewer";
import { json, type Route } from "../test/mockApi";
import { renderApp } from "../test/render";
import {
  actionsFor,
  detailHighValue,
  queueItem,
  sourceExtractionMistake,
} from "../test/reviewFixtures";
import * as wire from "../test/wire";
// Recorded from the real backend by scripts/export_ui_fixtures.py (P5-04 bodies).
import realCorrection from "../test/real/review-correction.json";
import realRefused from "../test/real/review-refused-422.json";
import realApprove from "../test/real/review-approve.json";
import realApproveRun from "../test/real/run-approve.json";

/** The real approval run (GET /api/runs/{id}) under another id, optionally declined. */
function approvalRun(run_id: string, declined = false) {
  if (!declined) return { ...realApproveRun, run_id };
  return {
    ...realApproveRun,
    run_id,
    status: "rejected",
    result: { ...realApproveRun.result, run_id, status: "rejected", receipt: null },
  };
}

interface Posted {
  path: string;
  body: Record<string, unknown>;
  headers: Record<string, string>;
}

/** Records every review POST (path, parsed JSON body, headers) and answers with `reply`. */
function recorder(reply: (p: Posted) => unknown | Response) {
  const posts: Posted[] = [];
  const route: Route = (url, init) => {
    const p: Posted = {
      path: url.pathname,
      body: JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>,
      headers: { ...(init?.headers as Record<string, string>) },
    };
    posts.push(p);
    return reply(p);
  };
  return { posts, route };
}

function queueWith(groups: Partial<ReviewQueue["groups"]>): ReviewQueue {
  return { groups: { correctable_extraction: [], awaiting_human_approval: [], unresolved_blocker: [], ...groups } };
}

async function openItem(user: ReturnType<typeof userEvent.setup>, invoiceNumber: string) {
  await user.click(await screen.findByRole("button", { name: `Review ${invoiceNumber}` }));
  return screen.findByRole("region", { name: new RegExp(`^${invoiceNumber}`) });
}

describe("Needs review queue (P5-09)", () => {
  it("renders the three groups from GET /api/review-queue", async () => {
    const { calls } = renderApp("/review");
    expect(await screen.findByRole("heading", { level: 1, name: "Needs review" })).toBeInTheDocument();
    const corrections = await screen.findByRole("table", { name: "Extraction corrections" });
    const approvals = screen.getByRole("table", { name: "Awaiting human approval" });
    const blockers = screen.getByRole("table", { name: "Unresolved blockers" });
    expect(within(corrections).getByText("CT-3001")).toBeInTheDocument();
    expect(within(corrections).getByText("A value could not be converted to its expected type")).toBeInTheDocument();
    expect(within(approvals).getByText("HV-10001")).toBeInTheDocument();
    expect(within(approvals).getByText("Above the USD 10,000 auto-pay limit")).toBeInTheDocument();
    expect(within(approvals).getByText("The model did not recommend approval")).toBeInTheDocument();
    expect(within(blockers).getByText("INV-1014")).toBeInTheDocument();
    expect(within(blockers).getByText("EUR 4,125.00")).toHaveClass("num");
    expect(calls.some((c) => c.method === "GET" && c.url === "/api/review-queue")).toBe(true);
  });

  it("shows an empty note per group", async () => {
    renderApp("/review", { "GET /api/review-queue": () => queueWith({}) });
    expect(await screen.findByText("No extraction mistakes to correct.")).toBeInTheDocument();
    expect(screen.getByText("No invoices are waiting for approval.")).toBeInTheDocument();
    expect(screen.getByText("No unresolved blockers.")).toBeInTheDocument();
  });

  it("renders review controls only from the server's AllowedActions", async () => {
    const user = userEvent.setup();
    const onlyDecline = {
      ...queueItem(detailHighValue, []),
      actions: { ...actionsFor(detailHighValue.invoice_id, "awaiting_human_approval", 1), allowed: ["decline" as const] },
    };
    renderApp("/review", { "GET /api/review-queue": () => queueWith({ awaiting_human_approval: [onlyDecline] }) });
    const panel = await openItem(user, "HV-10001");
    expect(await within(panel).findByRole("button", { name: "Decline" })).toBeInTheDocument();
    expect(within(panel).queryByRole("button", { name: "Approve mock payment" })).toBeNull();
    expect(within(panel).queryByRole("button", { name: /Correct an extracted value/ })).toBeNull();
    expect(within(panel).queryByRole("link", { name: "Add corrected invoice" })).toBeNull();
  });

  it("prefers the loaded record's review actions over the queue row", async () => {
    const user = userEvent.setup();
    const row = queueItem(detailHighValue, []); // approve, decline and correct
    const loaded = {
      ...detailHighValue,
      review_actions: { ...actionsFor(detailHighValue.invoice_id, "awaiting_human_approval", 1), allowed: ["decline" as const] },
    };
    renderApp("/review", {
      "GET /api/review-queue": () => queueWith({ awaiting_human_approval: [row] }),
      "GET /api/invoices/:id": () => wire.detail(loaded),
    });
    const panel = await openItem(user, "HV-10001");
    expect(await within(panel).findByRole("button", { name: "Decline" })).toBeInTheDocument();
    expect(within(panel).queryByRole("button", { name: "Approve mock payment" })).toBeNull();
    expect(within(panel).queryByRole("button", { name: /Correct an extracted value/ })).toBeNull();
  });

  it("marks the open row with aria-current, not aria-selected (a plain table, not a grid)", async () => {
    const user = userEvent.setup();
    const row = queueItem(detailHighValue, []);
    renderApp("/review", {
      "GET /api/review-queue": () => queueWith({ awaiting_human_approval: [row] }),
      "GET /api/invoices/:id": () => wire.detail(detailHighValue),
    });
    await openItem(user, "HV-10001");
    const tr = screen.getByRole("button", { name: "Review HV-10001" }).closest("tr")!;
    expect(tr).toHaveAttribute("aria-current", "true");
    expect(tr).not.toHaveAttribute("aria-selected");
  });

  it("renders no review control at all when nothing is allowed", async () => {
    const user = userEvent.setup();
    const none = {
      ...queueItem(detailHighValue, []),
      actions: { ...actionsFor(detailHighValue.invoice_id, "awaiting_human_approval", 1), allowed: [] },
    };
    renderApp("/review", { "GET /api/review-queue": () => queueWith({ awaiting_human_approval: [none] }) });
    const panel = await openItem(user, "HV-10001");
    await within(panel).findByText(/All checks passed/);
    expect(within(panel).queryByRole("button", { name: /Approve|Decline/ })).toBeNull();
    expect(within(panel).queryByLabelText(/Review reason/)).toBeNull();
  });

  it("binds approve to the displayed version and sends reason, reviewer and an Idempotency-Key", async () => {
    const user = userEvent.setup();
    const v3 = { ...detailHighValue, current_version: 3 };
    // The real 202 body; the outcome comes from following the run.
    const { posts, route } = recorder(() => json({ ...realApprove, run_id: "run-hv-2" }, 202));
    renderApp("/review", {
      "GET /api/review-queue": () =>
        queueWith({ awaiting_human_approval: [{ ...queueItem(v3, []), current_version: 3, actions: actionsFor(v3.invoice_id, "awaiting_human_approval", 3) }] }),
      "GET /api/invoices/:id": () => wire.detail(v3),
      "POST /api/invoices/:id/approve": route,
      "GET /api/runs/:id": () => approvalRun("run-hv-2"),
    });
    const panel = await openItem(user, "HV-10001");
    expect(await within(panel).findByText("Showing version 3.")).toBeInTheDocument();
    expect(within(panel).getByText(/USD 10,000\.01 · All checks passed/)).toBeInTheDocument();
    expect(within(panel).getByText("Payment waits for this action. It applies to version 3 only.")).toBeInTheDocument();
    await user.type(within(panel).getByLabelText("Reviewer"), "Ana");
    await user.type(within(panel).getByLabelText(/Review reason/), "Verified with the vendor");
    await user.click(within(panel).getByRole("button", { name: "Approve mock payment" }));

    const receipt = realApproveRun.result.receipt!.receipt_id;
    expect(
      await within(panel).findByText(new RegExp(`Mock payment approved\\. Receipt ${receipt} · USD 10,000\\.01\\.`)),
    ).toBeInTheDocument();
    expect(posts).toHaveLength(1);
    expect(posts[0]!.path).toBe("/api/invoices/inv-hv-1/approve");
    expect(posts[0]!.body).toEqual({ expected_version: 3, reason: "Verified with the vendor", reviewer: "Ana" });
    expect(posts[0]!.headers["Idempotency-Key"]).toMatch(/^[0-9a-f-]{36}$/);
    // Approving again is impossible in the UI once the action is recorded.
    expect(within(panel).queryByRole("button", { name: "Approve mock payment" })).toBeNull();
    expect(window.localStorage.getItem(REVIEWER_KEY)).toBe("Ana");
  });

  it("binds decline to the displayed version", async () => {
    const user = userEvent.setup();
    const { posts, route } = recorder(() => json({ ...realApprove, run_id: "run-hv-d" }, 202));
    renderApp("/review", {
      "POST /api/invoices/:id/decline": route,
      "GET /api/runs/:id": () => approvalRun("run-hv-d", true),
    });
    const panel = await openItem(user, "HV-10001");
    await user.type(await within(panel).findByLabelText("Reviewer"), "Ben");
    await user.type(within(panel).getByLabelText(/Review reason/), "Not ordered");
    await user.click(within(panel).getByRole("button", { name: "Decline" }));
    expect(await within(panel).findByText("Declined. No payment was made.")).toBeInTheDocument();
    expect(posts.map((p) => [p.path, p.body.expected_version])).toEqual([["/api/invoices/inv-hv-1/decline", 1]]);
  });

  it("blocks a blank review reason client-side", async () => {
    const user = userEvent.setup();
    const { posts, route } = recorder(() => ({ run_id: "x", status: "paid_mock" }));
    renderApp("/review", { "POST /api/invoices/:id/approve": route, "POST /api/invoices/:id/decline": route });
    const panel = await openItem(user, "HV-10001");
    await user.type(await within(panel).findByLabelText("Reviewer"), "Ana");
    await user.type(within(panel).getByLabelText(/Review reason/), "   ");
    await user.click(within(panel).getByRole("button", { name: "Approve mock payment" }));
    expect(within(panel).getByText("Enter a review reason.")).toBeInTheDocument();
    await user.click(within(panel).getByRole("button", { name: "Decline" }));
    expect(posts).toHaveLength(0);
  });

  it("on 409 replaces the panel with the current record and resubmits nothing", async () => {
    const user = userEvent.setup();
    const v2 = {
      ...detailHighValue,
      current_version: 2,
      corrections: [
        {
          version: 2,
          field: "stated.total",
          old_value: "10000.10",
          new_value: "10000.01",
          reason: "Misread total",
          reviewer: "Cleo",
          evidence_location: "$.total",
          created_at: "2026-11-02T09:00:00Z",
        },
      ],
    };
    const { posts, route } = recorder(() =>
      json(
        {
          code: "stale_version",
          message: "The invoice changed.",
          details: { current: actionsFor(v2.invoice_id, "awaiting_human_approval", 2), invoice: wire.detail(v2) },
        },
        409,
      ),
    );
    renderApp("/review", { "POST /api/invoices/:id/approve": route });
    const panel = await openItem(user, "HV-10001");
    expect(await within(panel).findByText("Showing version 1.")).toBeInTheDocument();
    await user.type(within(panel).getByLabelText("Reviewer"), "Ana");
    await user.type(within(panel).getByLabelText(/Review reason/), "Looks fine");
    await user.click(within(panel).getByRole("button", { name: "Approve mock payment" }));

    expect(
      await within(panel).findByText("This invoice changed since you opened it. Review the current version."),
    ).toBeInTheDocument();
    expect(within(panel).getByText("Showing version 2.")).toBeInTheDocument();
    expect(within(panel).getByText("Payment waits for this action. It applies to version 2 only.")).toBeInTheDocument();
    // History of the current record: who changed what, when, why.
    expect(within(panel).getByText(/Cleo · .* · Misread total · evidence \$\.total/)).toBeInTheDocument();
    // The form for the new version starts empty; nothing was resent.
    expect(within(panel).getByLabelText(/Review reason/)).toHaveValue("");
    expect(posts).toHaveLength(1);
    expect(posts[0]!.body.expected_version).toBe(1);
  });

  it("on 409 without a body refetches the invoice", async () => {
    const user = userEvent.setup();
    let version = 1;
    const { route } = recorder(() => {
      version = 2;
      return json({ code: "stale_version", message: "Changed." }, 409);
    });
    renderApp("/review", {
      "GET /api/invoices/:id": () => wire.detail({ ...detailHighValue, current_version: version }),
      "POST /api/invoices/:id/approve": route,
    });
    const panel = await openItem(user, "HV-10001");
    await user.type(await within(panel).findByLabelText("Reviewer"), "Ana");
    await user.type(within(panel).getByLabelText(/Review reason/), "ok");
    await user.click(within(panel).getByRole("button", { name: "Approve mock payment" }));
    expect(await within(panel).findByText("Showing version 2.")).toBeInTheDocument();
    expect(within(panel).getByText(/This invoice changed since you opened it/)).toBeInTheDocument();
  });

  it("explains an EUR blocker and offers no approve button", async () => {
    const user = userEvent.setup();
    renderApp("/review");
    const panel = await openItem(user, "INV-1014");
    expect(
      await within(panel).findByText("EUR settlement remains blocked; human approval cannot override it."),
    ).toBeInTheDocument();
    expect(within(panel).getByText("Total: EUR 4,125.00")).toBeInTheDocument();
    expect(within(panel).getByText("Inventory and arithmetic passed.")).toBeInTheDocument();
    expect(within(panel).getByText("This prototype only simulates USD settlement.")).toBeInTheDocument();
    expect(within(panel).queryByRole("button", { name: /approve/i })).toBeNull();
    expect(within(panel).queryByRole("button", { name: /Save correction/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Approve mock payment" })).toBeNull();
  });

  it("never renders approve for a needs-review invoice even if the server lists it", async () => {
    const user = userEvent.setup();
    const bad = queueItem(detailHighValue, []);
    bad.actions = { ...bad.actions, status: "needs_review" };
    renderApp("/review", {
      "GET /api/review-queue": () => queueWith({ awaiting_human_approval: [bad] }),
      "GET /api/invoices/:id": () => wire.detail({ ...detailHighValue, status: "needs_review" }),
    });
    const panel = await openItem(user, "HV-10001");
    await within(panel).findByText("Showing version 1.");
    expect(within(panel).queryByRole("button", { name: "Approve mock payment" })).toBeNull();
  });

  it("surfaces the model_disagreement wait with the model's stated reasons", async () => {
    const user = userEvent.setup();
    renderApp("/review");
    const panel = await openItem(user, "MD-2001");
    expect(await within(panel).findByText(/the model did not recommend approval/)).toBeInTheDocument();
    expect(within(panel).getByRole("list", { name: "The model's stated reasons" })).toHaveTextContent("Vendor is unfamiliar.");
    expect(within(panel).getByRole("button", { name: "Approve mock payment" })).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: "Decline" })).toBeInTheDocument();
  });
});

describe("Correction form (P5-09)", () => {
  const routes = (post: Route) => ({
    "GET /api/sources/:id/content": () => wire.source(sourceExtractionMistake),
    "POST /api/invoices/:id/corrections": post,
  });

  it("submits a correction with evidence, bound to the displayed version, and opens the revalidation run", async () => {
    const user = userEvent.setup();
    // The real success body: the revalidation run's ProcessingResult (200).
    const { posts, route } = recorder(() => json({ ...realCorrection, run_id: "run-ct-2" }, 200));
    const { router } = renderApp("/review", {
      ...routes(route),
      "GET /api/runs/:id": () => json({ code: "not_found", message: "x" }, 404),
    });
    const panel = await openItem(user, "CT-3001");
    const form = await within(panel).findByRole("form", { name: /Correct extraction · version 1/ });
    expect(within(form).getByLabelText("Field")).toHaveValue("stated.total");
    expect(within(form).getByLabelText("Evidence location")).toHaveValue("line:13");
    const beforeAfter = within(form).getByLabelText("Before and after");
    expect(within(beforeAfter).getByText("Extracted value").nextSibling).toHaveTextContent("∅");
    expect(within(form).getByText("Total Amount: $3.500,00")).toBeInTheDocument();
    expect(
      within(form).getByText("Saving invalidates prior approval; an eligible invoice up to USD 10,000 may auto-pay."),
    ).toBeInTheDocument();

    // Pick the evidence line in the source panel.
    await user.click(await within(panel).findByRole("button", { name: "Use line:11 as evidence: Subtotal: $3,500.00" }));
    expect(within(form).getByLabelText("Evidence location")).toHaveValue("line:11");
    await user.click(within(panel).getByRole("button", { name: "Use line:13 as evidence: Total Amount: $3.500,00" }));
    expect(within(form).getByLabelText("Evidence location")).toHaveValue("line:13");

    await user.type(within(form).getByLabelText("Corrected value"), "3500.00");
    expect(within(beforeAfter).getByText("Corrected value").nextSibling).toHaveTextContent("3500.00");
    await user.type(within(form).getByLabelText("Reviewer"), "Ana");
    await user.type(within(form).getByLabelText(/Reason/), "Misread total");
    await user.click(within(form).getByRole("button", { name: "Save correction and revalidate" }));

    await waitFor(() => expect(router.state.location.pathname).toBe("/runs/run-ct-2"));
    expect(posts).toHaveLength(1);
    expect(posts[0]!.path).toBe("/api/invoices/inv-ct-3001/corrections");
    expect(posts[0]!.body).toEqual({
      expected_version: 1,
      changes: [{ field: "stated.total", new_value: "3500.00", evidence_location: "line:13" }],
      reason: "Misread total",
      reviewer: "Ana",
    });
    expect(posts[0]!.headers["Idempotency-Key"]).toBeTruthy();
  });

  it("blocks a blank reason client-side", async () => {
    const user = userEvent.setup();
    const { posts, route } = recorder(() => ({ run_id: "x", status: "received" }));
    renderApp("/review", routes(route));
    const panel = await openItem(user, "CT-3001");
    const form = await within(panel).findByRole("form", { name: /Correct extraction/ });
    await user.type(within(form).getByLabelText("Corrected value"), "3500.00");
    await user.type(within(form).getByLabelText("Reviewer"), "Ana");
    await user.click(within(form).getByRole("button", { name: "Save correction and revalidate" }));
    expect(within(form).getByText("Enter a reason for this correction.")).toBeInTheDocument();
    expect(posts).toHaveLength(0);
  });

  it("shows the refusal message for a 422 and stays on the form", async () => {
    const user = userEvent.setup();
    const { router } = renderApp("/review", routes(() => json(realRefused, 422)));
    const panel = await openItem(user, "CT-3001");
    const form = await within(panel).findByRole("form", { name: /Correct extraction/ });
    await user.type(within(form).getByLabelText("Corrected value"), "3150.00");
    await user.type(within(form).getByLabelText("Reviewer"), "Ana");
    await user.type(within(form).getByLabelText(/Reason/), "Typo");
    await user.click(within(form).getByRole("button", { name: "Save correction and revalidate" }));
    expect(
      await within(form).findByText("This value is not what the invoice says. Submit a corrected invoice from the vendor."),
    ).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/review");
  });

  it("remembers the reviewer name in this browser", async () => {
    window.localStorage.setItem(REVIEWER_KEY, "Remembered Reviewer");
    const user = userEvent.setup();
    renderApp("/review", routes(() => ({ run_id: "x", status: "received" })));
    const panel = await openItem(user, "CT-3001");
    const form = await within(panel).findByRole("form", { name: /Correct extraction/ });
    expect(within(form).getByLabelText("Reviewer")).toHaveValue("Remembered Reviewer");
  });
});
