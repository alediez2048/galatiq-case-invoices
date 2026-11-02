import { expect, test, type Page } from "@playwright/test";

type Overview = {
  runs: number;
  documents: number;
  unique_invoices: number;
  duplicates: number;
  outcomes: Record<string, number>;
  paid_totals: unknown[];
};

async function overview(page: Page): Promise<Overview> {
  const res = await page.request.get("/api/overview");
  expect(res.ok()).toBe(true);
  return res.json();
}

const BREAKPOINTS = [
  { name: "wide (>991)", width: 1280, height: 900 },
  { name: "tablet (768-991)", width: 900, height: 900 },
  { name: "phone (480-767)", width: 600, height: 900 },
  { name: "small (<=479)", width: 375, height: 800 },
];

test.describe.serial("happy path (offline, temporary database)", () => {
  test("empty workspace is keyboard reachable with visible focus; panel returns focus", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toContainText("From invoice to decision");
    await expect(page.getByLabel(/Workspace mode:/)).toContainText("Offline simulation");

    // First Tab lands on the skip link, then the header and navigation.
    await page.keyboard.press("Tab");
    await expect(page.getByRole("link", { name: "Skip to content" })).toBeFocused();
    const seen: string[] = [];
    for (let i = 0; i < 12; i++) {
      await page.keyboard.press("Tab");
      seen.push(await page.evaluate(() => document.activeElement?.textContent?.trim() ?? ""));
    }
    for (const name of ["Setup", "Overview", "Invoices", "Needs review", "Upload invoice", "Try a sample"]) {
      expect(seen.some((t) => t.includes(name)), `Tab reaches ${name}`).toBe(true);
    }

    // Focus is visibly outlined.
    const trigger = page.getByRole("button", { name: "Try a sample" });
    await trigger.focus();
    const outline = await trigger.evaluate((el) => getComputedStyle(el).outlineStyle);
    expect(outline).toBe("solid");

    // Dialog has a heading; Escape returns focus to the trigger.
    await page.keyboard.press("Enter");
    const dialog = page.getByRole("dialog", { name: "Try a sample" });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole("heading", { name: "Try a sample" })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await expect(trigger).toBeFocused();
  });

  test("reduced motion switches off the wave mesh animation and transitions", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "no-preference" });
    await page.goto("/");
    const drift = page.locator(".wave-mesh__drift");
    expect(await drift.evaluate((el) => getComputedStyle(el).animationName)).not.toBe("none");

    await page.emulateMedia({ reducedMotion: "reduce" });
    expect(await drift.evaluate((el) => getComputedStyle(el).animationName)).toBe("none");
    const transition = await page
      .getByRole("link", { name: "Upload invoice" })
      .evaluate((el) => getComputedStyle(el).transitionDuration);
    expect(transition).toBe("0s");
  });

  let invoiceUrl = "";
  let runUrl = "";

  test("process INV-1001 to paid_mock through the UI", async ({ page }) => {
    const before = await overview(page);
    await page.goto("/");
    await page.getByRole("button", { name: "Try a sample" }).click();
    await page.getByRole("radio", { name: /Clean invoice/ }).check();
    await page.getByRole("button", { name: "Continue" }).click();

    // Selecting a sample never processes it.
    await expect(page).toHaveURL(/\/add\?sample=invoice_1001\.txt/);
    expect((await overview(page)).runs).toBe(before.runs);

    await page.getByRole("button", { name: "Process invoice" }).click();
    await page.waitForURL(/\/runs\/|\/invoices\//);
    runUrl = page.url().includes("/runs/") ? page.url() : "";
    await expect(page).toHaveURL(/\/invoices\//, { timeout: 30_000 });
    invoiceUrl = page.url();

    await expect(page.getByText("Mock receipt")).toBeVisible();
    await expect(page.getByText("No real funds transferred.").first()).toBeVisible();
    await expect(page.getByRole("heading", { name: "Line items" })).toBeVisible();

    const after = await overview(page);
    expect(after.runs).toBe(before.runs + 1);
    expect(after.outcomes["paid_mock"]).toBe((before.outcomes["paid_mock"] ?? 0) + 1);
  });

  test("reloading the invoice, processing and list pages never processes or pays", async ({ page }) => {
    const snapshot = await overview(page);
    // The processing page of the finished run: reload must only read.
    const runId = runUrl.split("/runs/")[1] ?? (await latestRunId(page));
    for (const path of [new URL(invoiceUrl).pathname, `/runs/${runId}`, "/", "/invoices", "/review"]) {
      await page.goto(path);
      await page.reload();
      await page.waitForLoadState("networkidle");
    }
    expect(await overview(page)).toEqual(snapshot);
  });

  for (const bp of BREAKPOINTS) {
    test(`layout at ${bp.name}: no page scroll; outcome before source; line items scroll`, async ({ page }) => {
      await page.setViewportSize({ width: bp.width, height: bp.height });
      await page.goto(invoiceUrl);
      await expect(page.getByRole("heading", { name: "Line items" })).toBeVisible();

      const noPageScroll = await page.evaluate(
        () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
      );
      expect(noPageScroll).toBe(true);

      const outline = await page.locator("#outcome-title").boundingBox();
      const source = await page.locator(".source-panel").boundingBox();
      expect(outline && source).toBeTruthy();
      if (bp.width <= 991) {
        // Stacked: outcome and reason come before the source preview.
        expect(outline!.y).toBeLessThan(source!.y);
      }

      const wrap = page.getByLabel("Line items, scrollable");
      await expect(wrap).toBeVisible();
      const scrollable = await wrap.evaluate((el) => getComputedStyle(el).overflowX);
      expect(["auto", "scroll"]).toContain(scrollable);
      // Every column header remains in the DOM (nothing hidden permanently).
      await expect(wrap.getByRole("columnheader")).toHaveCount(6);
      if (bp.width <= 479) {
        expect(await wrap.evaluate((el) => el.scrollWidth > el.clientWidth)).toBe(true);
      }
    });
  }

  test("small screens show invoice cards instead of the wide table", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 800 });
    await page.goto("/invoices");
    await expect(page.locator(".invoice-cards")).toBeVisible();
    await expect(page.locator(".invoice-table")).toBeHidden();
    await page.setViewportSize({ width: 1280, height: 900 });
    await expect(page.locator(".invoice-table")).toBeVisible();
    await expect(page.locator(".invoice-cards")).toBeHidden();
  });

  test("primary button text meets WCAG AA contrast in the rendered page", async ({ page }) => {
    await page.goto("/add");
    const ratio = await page.getByRole("button", { name: "Process invoice" }).evaluate((el) => {
      const parse = (c: string) => c.match(/[\d.]+/g)!.slice(0, 3).map(Number);
      const lum = ([r, g, b]: number[]) => {
        const f = (v: number) => ((v /= 255) <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);
        return 0.2126 * f(r!) + 0.7152 * f(g!) + 0.0722 * f(b!);
      };
      const cs = getComputedStyle(el);
      const [a, b] = [lum(parse(cs.color)), lum(parse(cs.backgroundColor))];
      return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
    });
    expect(ratio).toBeGreaterThanOrEqual(4.5);
  });
});

async function latestRunId(page: Page): Promise<string> {
  const res = await page.request.get("/api/invoices");
  const body = (await res.json()) as { items: { latest_run_id: string | null }[] };
  const id = body.items[0]?.latest_run_id;
  expect(id).toBeTruthy();
  return id as string;
}
