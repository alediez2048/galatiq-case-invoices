import { afterEach, describe, expect, it, vi } from "vitest";
import { detailHighValue, actionsFor } from "../test/reviewFixtures";
import * as wire from "../test/wire";
import { ApiError } from "./client";
import { classifyReviewError, reviewApi, STALE_NOTICE } from "./review";

afterEach(() => vi.unstubAllGlobals());

function stubFetch(response: Response) {
  const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const ok = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

describe("review API client", () => {
  it("fills every queue group in display order, even when the body omits one", async () => {
    stubFetch(ok({ groups: { awaiting_human_approval: [] } }));
    const q = await reviewApi.queue();
    expect(Object.keys(q.groups)).toEqual(["correctable_extraction", "awaiting_human_approval", "unresolved_blocker"]);
  });

  it("posts approve as JSON with the Idempotency-Key header", async () => {
    const fetchMock = stubFetch(ok({ run_id: "r", status: "paid_mock" }));
    await reviewApi.approve("inv 1", { expected_version: 2, reason: "ok", reviewer: "Ana" }, "key-1");
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe("/api/invoices/inv%201/approve");
    expect(init?.method).toBe("POST");
    expect((init?.headers as Record<string, string>)["Idempotency-Key"]).toBe("key-1");
    expect(JSON.parse(String(init?.body))).toEqual({ expected_version: 2, reason: "ok", reviewer: "Ana" });
  });

  it("posts a corrected submission as multipart with version, reason and reviewer", async () => {
    const fetchMock = stubFetch(ok({ run_id: "r", status: "received" }, 202));
    const file = new File(["x"], "fixed.txt", { type: "text/plain" });
    await reviewApi.correctedSubmission(
      "inv-1",
      { file, expected_version: 1, reason: "Vendor reissued", reviewer: "Ana", mode: "offline" },
      "key-2",
    );
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe("/api/invoices/inv-1/corrected-submission");
    const form = init?.body as FormData;
    expect(form.get("expected_version")).toBe("1");
    expect(form.get("reason")).toBe("Vendor reissued");
    expect(form.get("reviewer")).toBe("Ana");
    expect(form.get("mode")).toBe("offline");
    expect((form.get("file") as File).name).toBe("fixed.txt");
    expect((init?.headers as Record<string, string>)["Content-Type"]).toBeUndefined();
    expect((init?.headers as Record<string, string>)["Idempotency-Key"]).toBe("key-2");
  });
});

describe("classifyReviewError", () => {
  it("turns a 409 into a conflict carrying the adapted current record", () => {
    const current = { ...detailHighValue, current_version: 2 };
    const f = classifyReviewError(
      new ApiError(409, {
        code: "stale_version",
        message: "x",
        details: { current: actionsFor(current.invoice_id, "awaiting_human_approval", 2), invoice: wire.detail(current) },
      }),
    );
    expect(f.kind).toBe("conflict");
    if (f.kind !== "conflict") return;
    expect(f.message).toBe(STALE_NOTICE);
    expect(f.invoice?.current_version).toBe(2);
    expect(f.actions?.current_version).toBe(2);
  });

  it("keeps a 409 without details as a conflict with nothing to show yet", () => {
    const f = classifyReviewError(new ApiError(409, { code: "action_not_allowed", message: "x" }));
    expect(f).toMatchObject({ kind: "conflict", invoice: null, actions: null });
  });

  it("maps a 422 refusal code to its message", () => {
    const f = classifyReviewError(new ApiError(422, { code: "evidence_location_mismatch", message: "server" }));
    expect(f).toEqual({
      kind: "refused",
      code: "evidence_location_mismatch",
      message: "The cited location is not where the invoice states this field.",
    });
  });

  it("treats a schema 422 as invalid input", () => {
    const f = classifyReviewError(new ApiError(422, { code: "http_422", message: "Unprocessable Entity" }));
    expect(f.kind).toBe("invalid");
  });
});
