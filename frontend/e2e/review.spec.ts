import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import { basename, resolve } from "node:path";
import { expect, test, type Page } from "@playwright/test";

// P5-09 against the real P5-04 endpoints, on the e2e server's temporary offline database
// (e2e/serve.py). Review fixtures are uploaded through POST /api/runs with the evaluation
// date the backend tests use, so their due dates are not in the past.
const FIXTURES = resolve(import.meta.dirname, "../../tests/fixtures");
const EVALUATION_DATE = "2026-01-31";

async function upload(page: Page, relative: string): Promise<string> {
  const path = resolve(FIXTURES, relative);
  const res = await page.request.post("/api/runs", {
    headers: { "Idempotency-Key": randomUUID() },
    multipart: {
      file: { name: basename(path), mimeType: "application/octet-stream", buffer: readFileSync(path) },
      mode: "offline",
      evaluation_date: EVALUATION_DATE,
    },
  });
  expect(res.status()).toBe(202);
  const { run_id } = (await res.json()) as { run_id: string };
  for (let i = 0; i < 200; i++) {
    const run = (await (await page.request.get(`/api/runs/${run_id}`)).json()) as {
      terminal: boolean;
      invoice_id: string;
    };
    if (run.terminal) return run.invoice_id;
    await page.waitForTimeout(50);
  }
  throw new Error(`run ${run_id} did not finish`);
}

async function invoice(page: Page, id: string) {
  return (await (await page.request.get(`/api/invoices/${id}`)).json()) as {
    outcome: string;
    current_version: number;
    receipt: { receipt_id: string } | null;
  };
}

async function overview(page: Page) {
  return (await (await page.request.get("/api/overview")).json()) as { runs: number; outcomes: Record<string, number> };
}

async function openReview(page: Page, invoiceNumber: string) {
  await page.goto("/review");
  await page.getByRole("button", { name: `Review ${invoiceNumber}` }).click();
  return page.getByRole("region", { name: new RegExp(`^${invoiceNumber}`) });
}

test.describe.serial("needs review (P5-09 on P5-04, offline)", () => {
  test("USD 10,000.01 waits for a person; approve pays once with a receipt", async ({ page }) => {
    const id = await upload(page, "threshold/valid_10000_01.json");
    expect((await invoice(page, id)).outcome).toBe("awaiting_human_approval");

    // Reloading /review with the item open only reads: no run, no payment, still waiting.
    const before = await overview(page);
    await openReview(page, "TH-10000-01");
    await page.reload();
    await page.waitForLoadState("networkidle");
    expect(await overview(page)).toEqual(before);
    expect((await invoice(page, id)).outcome).toBe("awaiting_human_approval");

    const panel = await openReview(page, "TH-10000-01");
    await expect(panel.getByText(/USD 10,000\.01 · All checks passed/)).toBeVisible();
    await expect(panel.getByText("Payment waits for this action. It applies to version 1 only.")).toBeVisible();
    await panel.getByLabel("Reviewer").fill("Ana");
    await panel.getByLabel(/Review reason/).fill("Verified with the vendor");
    await panel.getByRole("button", { name: "Approve mock payment" }).click();

    await expect(panel.getByText(/Mock payment approved\. Receipt rcpt-\w+ · USD 10,000\.01\./)).toBeVisible({
      timeout: 30_000,
    });
    await expect(panel.getByRole("button", { name: "Approve mock payment" })).toHaveCount(0);
    const after = await invoice(page, id);
    expect(after.outcome).toBe("paid_mock");
    expect(after.receipt?.receipt_id).toBeTruthy();
  });

  test("an extraction mistake is corrected with source evidence and revalidated to paid", async ({ page }) => {
    const id = await upload(page, "review/extraction_mistake.txt");
    expect((await invoice(page, id)).outcome).toBe("needs_review");

    const panel = await openReview(page, "CT-3001");
    const form = panel.getByRole("form", { name: /Correct extraction · version 1/ });
    await expect(form.getByLabel("Field")).toHaveValue("stated.total");
    // Cite the Total Amount line by picking it in the source panel.
    await panel.getByRole("button", { name: /^Use line:13 as evidence/ }).click();
    await expect(form.getByLabel("Evidence location")).toHaveValue("line:13");
    await form.getByLabel("Corrected value").fill("3500.00");
    await form.getByLabel("Reviewer").fill("Ana");
    await form.getByLabel(/Reason/).fill("Misread total");
    await form.getByRole("button", { name: "Save correction and revalidate" }).click();

    await page.waitForURL(/\/runs\/|\/invoices\//);
    await expect(page).toHaveURL(/\/invoices\//, { timeout: 30_000 });
    await expect(page.getByText("Mock receipt")).toBeVisible();
    const after = await invoice(page, id);
    expect(after.current_version).toBe(2);
    expect(after.outcome).toBe("paid_mock");
  });

  test("two tabs: the stale tab is refused and refreshes in place to the current version", async ({ browser }) => {
    const context = await browser.newContext();
    const [a, b] = [await context.newPage(), await context.newPage()];
    const id = await upload(a, "review/ocr_ambiguous.txt");

    const correct = async (page: Page) => {
      const panel = await openReview(page, "OCR-3002");
      const form = panel.getByRole("form", { name: /Correct extraction · version 1/ });
      await form.getByLabel("Field").selectOption("lines[0].line_total");
      await form.getByLabel("Evidence location").fill("line:9");
      await form.getByLabel("Corrected value").fill("3500.00");
      await form.getByLabel("Reviewer").fill("Ana");
      await form.getByLabel(/Reason/).fill("OCR read O for 0");
      return { panel, save: () => form.getByRole("button", { name: "Save correction and revalidate" }).click() };
    };
    const tabA = await correct(a);
    const tabB = await correct(b); // both show version 1

    await tabA.save();
    await expect(a).toHaveURL(/\/runs\/|\/invoices\//);
    await expect.poll(async () => (await invoice(a, id)).current_version, { timeout: 30_000 }).toBe(2);

    await tabB.save();
    await expect(
      tabB.panel.getByText("This invoice changed since you opened it. Review the current version."),
    ).toBeVisible();
    await expect(tabB.panel.getByText("Nothing was submitted for the earlier version.")).toBeVisible();
    await expect(tabB.panel.getByText("Showing version 2.")).toBeVisible();
    await expect(b).toHaveURL(/\/review/);
    expect((await invoice(b, id)).current_version).toBe(2); // the stale tab created nothing
    await context.close();
  });

  test("add corrected invoice: a rejected invoice is superseded by the vendor's corrected file", async ({ page }) => {
    const res = await page.request.post("/api/runs", {
      headers: { "Idempotency-Key": randomUUID() },
      data: { sample: "invoice_1013.json", mode: "offline", evaluation_date: EVALUATION_DATE },
    });
    expect(res.status()).toBe(202);
    const { run_id } = (await res.json()) as { run_id: string };
    await expect.poll(async () => (await (await page.request.get(`/api/runs/${run_id}`)).json()).terminal).toBe(true);
    const id = ((await (await page.request.get(`/api/runs/${run_id}`)).json()) as { invoice_id: string }).invoice_id;
    expect((await invoice(page, id)).outcome).toBe("rejected");

    await page.goto(`/invoices/${id}`);
    await page.getByRole("link", { name: "Add corrected invoice" }).click();
    await expect(page.getByText(/Corrected invoice for INV-1013 · replaces version 1/)).toBeVisible();
    await page.getByLabel("Invoice file").setInputFiles(resolve(FIXTURES, "review/inv_1013_corrected.json"));
    await page.getByLabel("Reviewer").fill("Ana");
    await page.getByLabel(/Reason for the corrected invoice/).fill("Vendor reissued the invoice");
    await page.getByRole("button", { name: "Process corrected invoice" }).click();
    await page.waitForURL(/\/runs\/|\/invoices\//);
    await expect.poll(async () => (await invoice(page, id)).current_version, { timeout: 30_000 }).toBe(2);
    expect((await invoice(page, id)).outcome).toBe("awaiting_human_approval");
  });

  test("local web security: a foreign Origin is 403 and a text/plain body is 415; no run starts", async ({ page }) => {
    const before = await overview(page);
    const body = JSON.stringify({ sample: "invoice_1001.txt", mode: "offline" });
    const foreign = await page.request.post("/api/runs", {
      headers: { Origin: "https://evil.example", "Content-Type": "text/plain", "Idempotency-Key": randomUUID() },
      data: body,
    });
    expect(foreign.status()).toBe(403);
    expect((await foreign.json()).code).toBe("forbidden_origin");

    await page.goto("/");
    const sameOrigin = await page.evaluate(async (b) => {
      const r = await fetch("/api/runs", {
        method: "POST",
        headers: { "Content-Type": "text/plain", "Idempotency-Key": crypto.randomUUID() },
        body: b,
      });
      return { status: r.status, code: ((await r.json()) as { code: string }).code };
    }, body);
    expect(sameOrigin).toEqual({ status: 415, code: "unsupported_media_type" });
    expect((await overview(page)).runs).toBe(before.runs);
  });
});
