import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, newIdempotencyKey } from "./client";
import type { InvoiceListQuery } from "./types";

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

export const useOverview = () => useApiQuery("overview", (s) => api.overview(s));

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
