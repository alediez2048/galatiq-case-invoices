/**
 * Fixture-backed fetch stub. Tests install it with explicit routes; the dev server can
 * install the default routes with VITE_MOCK_API=1 (never included in production builds).
 */
import type { InvoiceDetail, InvoiceSummary } from "../api/types";
import * as f from "./fixtures";
import * as review from "./reviewFixtures";
import * as wire from "./wire";

export type Route = (url: URL, init?: RequestInit) => unknown | Response | Promise<unknown | Response>;
export type Routes = Record<string, Route>;

export const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

/** Routes are matched by "METHOD /path" with ":param" segments. */
export function createFetch(routes: Routes) {
  const calls: { method: string; url: string; headers: Record<string, string> }[] = [];
  const fetchStub = async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input instanceof Request ? input.url : input), "http://localhost");
    const method = (init?.method ?? "GET").toUpperCase();
    calls.push({ method, url: url.pathname + url.search, headers: { ...(init?.headers as Record<string, string>) } });
    for (const [pattern, handler] of Object.entries(routes)) {
      const [m, path] = pattern.split(" ");
      if (m !== method || !path) continue;
      const re = new RegExp(`^${path.replace(/:[a-z_]+/gi, "[^/]+")}$`);
      if (!re.test(url.pathname)) continue;
      const out = await handler(url, init);
      return out instanceof Response ? out : json(out);
    }
    return json({ code: "not_found", message: `No mock for ${method} ${url.pathname}` }, 404);
  };
  return { fetchStub, calls };
}

const details: Record<string, InvoiceDetail> = Object.fromEntries(
  [
    f.detail1001,
    f.detail1002,
    f.detail1013,
    f.detail1012,
    f.detail1014,
    f.detail1011Duplicate,
    f.detail1004Revised,
    f.detailVersionConflict,
    f.detailUnreadable,
    f.detailOcr,
    f.detailOversized,
    f.detailProvider,
    f.detailProcessing,
    f.detailMissingFields,
    ...review.reviewDetails,
  ].map((d) => [d.invoice_id, d]),
);

export function listFrom(items: InvoiceSummary[]) {
  return (url: URL) => {
    const status = url.searchParams.get("status");
    const mode = url.searchParams.get("mode");
    const q = (url.searchParams.get("q") ?? "").toLowerCase();
    const filtered = items.filter(
      (i) =>
        (!status || i.status === status) &&
        (!mode || i.mode === mode) &&
        (!q || `${i.invoice_number} ${i.vendor}`.toLowerCase().includes(q)),
    );
    return wire.list({ items: filtered, page: 1, page_size: 50, total: filtered.length });
  };
}

export const defaultRoutes: Routes = {
  "GET /api/settings/readiness": () => wire.readiness(f.readinessFixture),
  "GET /api/overview": () => wire.overview(f.overviewFixture),
  "GET /api/invoices": listFrom(f.fourInvoices),
  "GET /api/invoices/:id": (url) => {
    const id = decodeURIComponent(url.pathname.split("/").pop() ?? "");
    const found = details[id];
    return found ? wire.detail(found) : json({ code: "not_found", message: "Invoice not found." }, 404);
  },
  "GET /api/sources/:id/content": () => wire.source(f.source1001),
  "GET /api/samples": () => wire.samples(f.samplesFixture),
  // Hand-shaped until P5-04 lands (see api/review.ts).
  "GET /api/review-queue": () => review.reviewQueueFixture,
};

export function installMockApi(routes: Routes = defaultRoutes) {
  const { fetchStub } = createFetch(routes);
  window.fetch = fetchStub as typeof window.fetch;
}
