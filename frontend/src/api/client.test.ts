import { describe, expect, it, vi } from "vitest";
import { api, ApiError, request } from "./client";
import { createFetch, json } from "../test/mockApi";

describe("api client", () => {
  it("prefixes /api and sends the idempotency key header", async () => {
    const { fetchStub, calls } = createFetch({ "POST /api/runs/:id/retry": () => ({ run_id: "r2" }) });
    vi.stubGlobal("fetch", fetchStub);
    await expect(api.retryRun("r1", "key-123")).resolves.toEqual({ run_id: "r2" });
    expect(calls[0]).toMatchObject({ method: "POST", url: "/api/runs/r1/retry" });
    expect(calls[0]?.headers["Idempotency-Key"]).toBe("key-123");
  });

  it("maps the {code, message, details} error body", async () => {
    const { fetchStub } = createFetch({
      "GET /api/invoices/:id": () =>
        json({ code: "stale_version", message: "Invoice changed.", details: { version: 3 } }, 409),
    });
    vi.stubGlobal("fetch", fetchStub);
    const error = await api.invoice("x").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 409, code: "stale_version", message: "Invoice changed.", details: { version: 3 } });
  });

  it("maps non-conforming bodies and network failures", async () => {
    vi.stubGlobal("fetch", async () => new Response("bad gateway", { status: 502, statusText: "Bad Gateway" }));
    await expect(request("/overview")).rejects.toMatchObject({ code: "http_502" });
    vi.stubGlobal("fetch", async () => {
      throw new TypeError("Failed to fetch");
    });
    await expect(request("/overview")).rejects.toMatchObject({ code: "network_error", status: 0 });
  });

  it("serializes list filters into the query string", async () => {
    const { fetchStub, calls } = createFetch({ "GET /api/invoices": () => ({ items: [], page: 1, page_size: 50, total: 0 }) });
    vi.stubGlobal("fetch", fetchStub);
    await api.invoices({ status: "rejected", mode: "", q: "gad", page: 2 });
    expect(calls[0]?.url).toBe("/api/invoices?status=rejected&q=gad&page=2");
  });
});
