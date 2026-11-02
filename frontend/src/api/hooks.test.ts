import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { api, ApiError, type RunInput } from "./client";
import { useSubmitRun } from "./hooks";
import type { ExecutionMode } from "./types";

const sample = (mode: ExecutionMode): RunInput => ({ kind: "sample", sample: "invoice_1001.txt", mode });

describe("useSubmitRun keys (Phase 5 review, Important 4)", () => {
  it("reuses the key for a resend of the same request, and takes a new one when the mode changes", async () => {
    const keys: string[] = [];
    vi.spyOn(api, "createRun").mockImplementation(async (_input, key) => {
      keys.push(key);
      throw new ApiError(0, { code: "network_error", message: "lost" });
    });
    const { result, rerender } = renderHook(
      ({ mode }: { mode: ExecutionMode }) => useSubmitRun("sample:invoice_1001.txt", mode),
      { initialProps: { mode: "offline" as ExecutionMode } },
    );
    await act(() => result.current.submit(sample("offline")));
    await act(() => result.current.submit(sample("offline")));
    rerender({ mode: "live" });
    await act(() => result.current.submit(sample("live")));
    rerender({ mode: "offline" });
    await act(() => result.current.submit(sample("offline")));
    expect(keys).toHaveLength(4);
    expect(keys[1]).toBe(keys[0]); // lost response, same request: the server replays
    expect(keys[2]).not.toBe(keys[0]); // another mode is another request
    expect(keys[3]).toBe(keys[0]);
  });
});
