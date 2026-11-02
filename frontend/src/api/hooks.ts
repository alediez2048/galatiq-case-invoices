import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, newIdempotencyKey, type RunInput } from "./client";
import type { InvoiceListQuery, RunCreated, RunProgress } from "./types";

export interface QueryState<T> {
  data: T | undefined;
  error: Error | undefined;
  /** True while a request is in flight; earlier data stays available meanwhile. */
  loading: boolean;
  reload: () => void;
}

/**
 * Minimal fetch-on-mount hook. Keeps the previous data while refetching so existing
 * context stays visible, and aborts stale requests when the key changes.
 */
export function useApiQuery<T>(
  key: string | null,
  fetcher: (signal: AbortSignal) => Promise<T>,
): QueryState<T> {
  const [data, setData] = useState<T | undefined>(undefined);
  const [error, setError] = useState<Error | undefined>(undefined);
  const [loading, setLoading] = useState(key !== null);
  const [nonce, setNonce] = useState(0);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  useEffect(() => {
    if (key === null) {
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setError(undefined);
    fetcherRef.current(controller.signal).then(
      (value) => {
        if (controller.signal.aborted) return;
        setData(value);
        setLoading(false);
      },
      (err: unknown) => {
        if (controller.signal.aborted) return;
        setError(err instanceof Error ? err : new Error(String(err)));
        setLoading(false);
      },
    );
    return () => controller.abort();
  }, [key, nonce]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return { data, error, loading, reload };
}

export const useReadiness = () => useApiQuery("readiness", (s) => api.readiness(s));

/** `refreshKey` refetches when it changes (the frame passes the route, so counts follow runs). */
export const useOverview = (refreshKey = "") =>
  useApiQuery(`overview:${refreshKey}`, (s) => api.overview(s));

export function useInvoices(q: InvoiceListQuery) {
  const key = `invoices:${q.status ?? ""}:${q.mode ?? ""}:${q.q ?? ""}:${q.page ?? 1}`;
  return useApiQuery(key, (s) => api.invoices(q, s));
}

export const useInvoice = (id: string | undefined) =>
  useApiQuery(id ? `invoice:${id}` : null, (s) => api.invoice(id as string, s));

export const useSourceContent = (sourceId: string | undefined) =>
  useApiQuery(sourceId ? `source:${sourceId}` : null, (s) =>
    api.sourceContent(sourceId as string, s),
  );

/** Samples load only when the selection panel opens. */
export const useSamples = (enabled: boolean) =>
  useApiQuery(enabled ? "samples" : null, (s) => api.samples(s));

/**
 * Explicit retry of a failed run. One idempotency key per mounted control, so a double
 * click or a resubmission after a lost response cannot create two runs.
 */
export function useRetryRun(runId: string, onDone: (runId: string) => void) {
  const key = useRef(newIdempotencyKey());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const retry = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const created = await api.retryRun(runId, key.current);
      onDone(created.run_id);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Retry failed.");
      setBusy(false);
    }
  }, [runId, onDone]);
  return { retry, busy, error };
}

/**
 * One Process action (P5-07). A key is generated per selection, the request is sent at most
 * once while in flight (a synchronous guard, so a double click cannot post twice), and a
 * resend after a lost response reuses the key so the backend replays the same run.
 */
export function useSubmitRun(selectionId: string | null) {
  const keys = useRef(new Map<string, string>());
  const inFlight = useRef(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  useEffect(() => setError(null), [selectionId]);

  const submit = useCallback(
    async (input: RunInput): Promise<RunCreated | null> => {
      if (inFlight.current || selectionId === null) return null;
      inFlight.current = true;
      setBusy(true);
      setError(null);
      let key = keys.current.get(selectionId);
      if (!key) {
        key = newIdempotencyKey();
        keys.current.set(selectionId, key);
      }
      try {
        return await api.createRun(input, key);
      } catch (e) {
        setError(
          e instanceof ApiError ? e : new ApiError(0, { code: "unknown", message: String(e) }),
        );
        inFlight.current = false;
        setBusy(false);
        return null;
      }
    },
    [selectionId],
  );
  return { submit, busy, error };
}

export const POLL_INTERVAL_MS = 500;
const POLL_RETRY_MS = 2000;

/**
 * Polls GET /api/runs/{id} until the run is terminal. Read-only: refreshing or remounting
 * never starts processing. A failed poll keeps the last progress and tries again.
 */
export function useRunProgress(runId: string | undefined, intervalMs = POLL_INTERVAL_MS) {
  const [data, setData] = useState<RunProgress | undefined>(undefined);
  const [error, setError] = useState<ApiError | undefined>(undefined);

  useEffect(() => {
    if (!runId) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const tick = async () => {
      try {
        const run = await api.run(runId, controller.signal);
        if (controller.signal.aborted) return;
        setData(run);
        setError(undefined);
        if (!run.terminal) timer = setTimeout(tick, intervalMs);
      } catch (e) {
        if (controller.signal.aborted) return;
        const err =
          e instanceof ApiError ? e : new ApiError(0, { code: "unknown", message: String(e) });
        setError(err);
        if (err.status !== 404) timer = setTimeout(tick, POLL_RETRY_MS);
      }
    };
    void tick();
    return () => {
      controller.abort();
      if (timer) clearTimeout(timer);
    };
  }, [runId, intervalMs]);

  return { data, error };
}
