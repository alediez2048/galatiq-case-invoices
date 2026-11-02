import {
  toInvoiceDetail,
  toInvoiceList,
  toOverview,
  toReadiness,
  toRunCreated,
  toRunProgress,
  toSample,
  toSourceContent,
} from "./adapters";
import type {
  ApiErrorBody,
  ExecutionMode,
  InvoiceDetail,
  InvoiceList,
  InvoiceListQuery,
  Overview,
  Readiness,
  RunCreated,
  RunProgress,
  Sample,
  SourceContent,
  Wire,
} from "./types";

/** All API routes live under /api on the same origin (Vite proxies it in development). */
export const API_BASE = "/api";

/** Error raised for any non-2xx response, carrying the backend's {code, message, details}. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: unknown;

  constructor(status: number, body: ApiErrorBody) {
    super(body.message);
    this.name = "ApiError";
    this.status = status;
    this.code = body.code;
    this.details = body.details;
  }
}

function isErrorBody(value: unknown): value is ApiErrorBody {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as ApiErrorBody).code === "string" &&
    typeof (value as ApiErrorBody).message === "string"
  );
}

/** Maps any failed response to an ApiError; unknown bodies become a generic http_<status>. */
async function toApiError(response: Response): Promise<ApiError> {
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    // Non-JSON error body (proxy error page, empty 502, ...).
  }
  if (isErrorBody(body)) return new ApiError(response.status, body);
  // FastAPI's default 422 shape: {detail: [...]}
  const details = typeof body === "object" && body !== null ? body : undefined;
  return new ApiError(response.status, {
    code: response.status === 0 ? "network_error" : `http_${response.status}`,
    message: response.statusText || "The request failed.",
    details,
  });
}

/** A fresh client-generated key for one user action (P5-02 / P5-04 idempotency). */
export function newIdempotencyKey(): string {
  return crypto.randomUUID();
}

export function idempotencyHeaders(key: string): Record<string, string> {
  return { "Idempotency-Key": key };
}

export interface RequestOptions {
  method?: string;
  body?: BodyInit | null;
  json?: unknown;
  headers?: Record<string, string>;
  idempotencyKey?: string;
  signal?: AbortSignal;
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json", ...options.headers };
  let body = options.body ?? null;
  if (options.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.json);
  }
  if (options.idempotencyKey) Object.assign(headers, idempotencyHeaders(options.idempotencyKey));

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method: options.method ?? (body ? "POST" : "GET"),
      headers,
      body,
      signal: options.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError(0, {
      code: "network_error",
      message: "Cannot reach the local API. Is the backend running?",
    });
  }
  if (!response.ok) throw await toApiError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

function query(params: Record<string, string | number | undefined | null>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

const enc = encodeURIComponent;

/** What one Process click submits: a bundled sample by name, or an uploaded file. */
export type RunInput =
  | { kind: "sample"; sample: string; mode: ExecutionMode; evaluationDate?: string }
  | { kind: "file"; file: File; mode: ExecutionMode; evaluationDate?: string };

function runBody(input: RunInput): Pick<RequestOptions, "json" | "body"> {
  if (input.kind === "sample") {
    const json: Wire["RunRequest"] = { sample: input.sample, mode: input.mode };
    if (input.evaluationDate) json.evaluation_date = input.evaluationDate;
    return { json };
  }
  const form = new FormData();
  form.append("mode", input.mode);
  if (input.evaluationDate) form.append("evaluation_date", input.evaluationDate);
  form.append("file", input.file, input.file.name);
  return { body: form };
}

/** Typed endpoint functions; responses are adapted to view models. Views use hooks.ts. */
export const api = {
  readiness: async (signal?: AbortSignal): Promise<Readiness> =>
    toReadiness(await request<Wire["Readiness"]>("/settings/readiness", { signal })),
  overview: async (signal?: AbortSignal): Promise<Overview> =>
    toOverview(await request<Wire["Overview"]>("/overview", { signal })),
  invoices: async (q: InvoiceListQuery, signal?: AbortSignal): Promise<InvoiceList> =>
    toInvoiceList(await request<Wire["InvoiceList"]>(`/invoices${query({ ...q })}`, { signal })),
  invoice: async (id: string, signal?: AbortSignal): Promise<InvoiceDetail> =>
    toInvoiceDetail(await request<Wire["InvoiceDetail"]>(`/invoices/${enc(id)}`, { signal })),
  sourceContent: async (sourceId: string, signal?: AbortSignal): Promise<SourceContent> =>
    toSourceContent(
      await request<Wire["SourceContent"]>(`/sources/${enc(sourceId)}/content`, { signal }),
    ),
  samples: async (signal?: AbortSignal): Promise<Sample[]> =>
    (await request<Wire["Sample"][]>("/samples", { signal })).map(toSample),
  /** P5-02: one run per idempotency key; the backend replays the same run for a repeat. */
  createRun: async (input: RunInput, idempotencyKey: string): Promise<RunCreated> =>
    toRunCreated(
      await request<Wire["RunAccepted"]>("/runs", {
        method: "POST",
        idempotencyKey,
        ...runBody(input),
      }),
    ),
  run: async (runId: string, signal?: AbortSignal): Promise<RunProgress> =>
    toRunProgress(await request<Wire["RunView"]>(`/runs/${enc(runId)}`, { signal })),
  /**
   * P5-02 explicit retry of a recoverable failure; creates a linked run.
   * TODO(P3-08): the backend route lands with Phase 3; the response shape is assumed.
   */
  retryRun: async (runId: string, idempotencyKey: string): Promise<RunCreated> =>
    toRunCreated(
      await request<Wire["RunAccepted"]>(`/runs/${enc(runId)}/retry`, {
        method: "POST",
        idempotencyKey,
      }),
    ),
};

/** Persisted result download (P5-03); a plain link, never transient UI state. */
export function resultJsonUrl(invoiceId: string): string {
  return `${API_BASE}/invoices/${enc(invoiceId)}/result.json`;
}
