import { useCallback, useRef, useState } from "react";
import { newIdempotencyKey } from "../api/client";
import { classifyReviewError, type ReviewFailure } from "../api/review";

/**
 * Sends one review action at a time. The idempotency key is tied to the exact request
 * (action, version and payload), so a resend after a lost response replays the same
 * request, while any change to what is sent gets a new key. A 409 is reported to
 * `onConflict` and never retried automatically.
 */
export function useReviewAction(onConflict: (failure: Extract<ReviewFailure, { kind: "conflict" }>) => void) {
  const keys = useRef(new Map<string, string>());
  const inFlight = useRef(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<ReviewFailure | null>(null);

  const send = useCallback(
    async <T,>(signature: string, call: (key: string) => Promise<T>): Promise<T | null> => {
      if (inFlight.current) return null; // synchronous guard: a double click posts once
      inFlight.current = true;
      setBusy(true);
      setFailure(null);
      let key = keys.current.get(signature);
      if (!key) {
        key = newIdempotencyKey();
        keys.current.set(signature, key);
      }
      try {
        return await call(key);
      } catch (error) {
        const f = classifyReviewError(error);
        if (f.kind === "conflict") onConflict(f);
        else setFailure(f);
        return null;
      } finally {
        inFlight.current = false;
        setBusy(false);
      }
    },
    [onConflict],
  );

  return { send, busy, failure };
}
