/**
 * Review queue and review action client (P5-09 on the P5-04 endpoints).
 *
 * Generated types (schema.d.ts, from openapi.json) for every shape the backend already
 * serves: ReviewAction, ReviewRefusal, AllowedActions, FieldChange, CorrectionBody,
 * ReviewDecisionBody and the RunAccepted a review action returns.
 *
 * TODO(P5-04 stage 3): the review queue and corrected-submission endpoints are not served
 * yet. QueueItem, ReviewQueue and CorrectedSubmissionInput below are HAND-WRITTEN mirrors of
 * schemas.py until they are; then replace them with `Wire[...]` aliases.
 */
import { toInvoiceDetail } from "./adapters";
import { ApiError, request } from "./client";
import type {
  ExecutionMode,
  FindingCode,
  InvoiceDetail,
  InvoiceStatus,
  ReviewAllowedActions,
  ReviewRefusal,
  Wire,
} from "./types";

export type { ReviewAction, ReviewAllowedActions, ReviewRefusal } from "./types";

// ---- Contracts --------------------------------------------------------------------------

/** codes.QueueGroup, in display order. */
export const QUEUE_GROUPS = [
  "correctable_extraction",
  "awaiting_human_approval",
  "unresolved_blocker",
] as const;
export type QueueGroup = (typeof QUEUE_GROUPS)[number];

/** schemas.QueueItem (hand-written until GET /api/review-queue is served). */
export interface QueueItem {
  invoice_id: string;
  vendor_name: string | null;
  invoice_number: string | null;
  /** Decimal string. */
  total: string | null;
  currency: string | null;
  status: InvoiceStatus;
  current_version: number | null;
  reason_codes: FindingCode[];
  actions: ReviewAllowedActions;
}

/** schemas.ReviewQueue: every group present, even when empty. */
export interface ReviewQueue {
  groups: Record<QueueGroup, QueueItem[]>;
}

/** schemas.FieldChange. `field` matches schemas.CORRECTABLE_FIELD. */
export type FieldChange = Wire["FieldChange"];

/** POST /api/invoices/{id}/corrections body (CorrectionRequest without invoice_id: it is in the path). */
export type CorrectionBody = Wire["CorrectionBody"];

/** POST /api/invoices/{id}/approve and /decline body. */
export type ReviewDecisionBody = Wire["ReviewDecisionBody"];

/** POST /api/invoices/{id}/corrected-submission (multipart) fields. */
export interface CorrectedSubmissionInput {
  file: File;
  expected_version: number;
  reason: string;
  reviewer: string;
  mode?: ExecutionMode;
}

/**
 * Success body of a review action, as for POST /api/runs: 202 with the run the action
 * created, sent once the run is committed; follow it with GET /api/runs/{run_id}. 200 with
 * `idempotent_replay` when the action started no run (a repeated approve of the paid version
 * answers with the paying run). A repeated Idempotency-Key replays the same run.
 */
export type ReviewActionResponse = Wire["RunAccepted"];

/**
 * `details` of a refused review action (P5-04). `current` is always present for a known
 * invoice; `invoice` (the GET /api/invoices/{id} body) only on a 409.
 */
export interface ReviewConflictDetails {
  /** ReviewRefused.current */
  current?: ReviewAllowedActions | null;
  /** GET /api/invoices/{id} body for the current record. */
  invoice?: Wire["InvoiceDetail"] | null;
}

// ---- Errors -----------------------------------------------------------------------------

export const STALE_NOTICE = "This invoice changed since you opened it. Review the current version.";

const REFUSAL_COPY: Record<ReviewRefusal, string> = {
  unknown_invoice: "This invoice was not found.",
  stale_version: STALE_NOTICE,
  action_not_allowed: "This action is not available for the invoice in its current state.",
  already_paid: "This invoice is already mock paid. No additional payment.",
  field_not_correctable:
    "This field cannot be corrected here. Submit a corrected invoice from the vendor.",
  identity_correction_deferred:
    "Vendor and invoice number cannot be changed by a correction. Submit a corrected invoice from the vendor.",
  invalid_value: "The corrected value is not valid for this field.",
  correction_not_in_source:
    "This value is not what the invoice says. Submit a corrected invoice from the vendor.",
  evidence_location_mismatch: "The cited location is not where the invoice states this field.",
  evidence_unavailable:
    "This version has no recorded evidence locations, so it cannot be corrected here. Submit a corrected invoice from the vendor.",
  source_text_unavailable:
    "The source text of this version is not stored, so it cannot be corrected here. Submit a corrected invoice from the vendor.",
  corrected_identity_mismatch:
    "The corrected invoice has a different vendor or invoice number than the invoice it replaces.",
};

export function refusalMessage(code: string, fallback?: string): string {
  return REFUSAL_COPY[code as ReviewRefusal] ?? fallback ?? "The action was refused.";
}

/**
 * The outcome of a failed review action, already classified for the UI:
 * - `conflict` (409): the record changed or the action no longer applies. Carries the
 *   current invoice detail and allowed actions when the body had them. Never resubmitted.
 * - `refused` (422 with a refusal code): the request itself was refused; show `message`.
 * - `invalid` (422 schema errors) and `error` (network / 5xx): show `message`.
 */
export type ReviewFailure =
  | {
      kind: "conflict";
      code: string;
      message: string;
      invoice: InvoiceDetail | null;
      actions: ReviewAllowedActions | null;
    }
  | { kind: "refused" | "invalid" | "error"; code: string; message: string };

export function classifyReviewError(error: unknown): ReviewFailure {
  if (!(error instanceof ApiError)) {
    return { kind: "error", code: "unknown", message: "The action failed. Try again." };
  }
  if (error.status === 409) {
    const details = (error.details ?? {}) as ReviewConflictDetails;
    let invoice: InvoiceDetail | null = null;
    try {
      invoice = details.invoice ? toInvoiceDetail(details.invoice) : null;
    } catch {
      invoice = null; // malformed body: the caller refetches instead
    }
    return {
      kind: "conflict",
      code: error.code,
      message: error.code === "stale_version" ? STALE_NOTICE : refusalMessage(error.code, error.message),
      invoice,
      actions: details.current ?? null,
    };
  }
  if (error.status === 422) {
    if (error.code in REFUSAL_COPY) {
      return { kind: "refused", code: error.code, message: refusalMessage(error.code, error.message) };
    }
    return { kind: "invalid", code: error.code, message: "Check the reason, reviewer and value, then try again." };
  }
  if (error.status === 404) {
    return { kind: "refused", code: error.code, message: REFUSAL_COPY.unknown_invoice };
  }
  return { kind: "error", code: error.code, message: error.message || "The action failed. Try again." };
}

// ---- Endpoints --------------------------------------------------------------------------

const enc = encodeURIComponent;

function normalizeQueue(body: Partial<ReviewQueue> | null | undefined): ReviewQueue {
  const groups = (body?.groups ?? {}) as Partial<Record<QueueGroup, QueueItem[]>>;
  return {
    groups: Object.fromEntries(QUEUE_GROUPS.map((g) => [g, groups[g] ?? []])) as Record<
      QueueGroup,
      QueueItem[]
    >,
  };
}

export const reviewApi = {
  /** GET /api/review-queue */
  queue: async (signal?: AbortSignal): Promise<ReviewQueue> =>
    normalizeQueue(await request<ReviewQueue>("/review-queue", { signal })),

  /** POST /api/invoices/{id}/corrections — starts a revalidation run on a new version. */
  correct: (invoiceId: string, body: CorrectionBody, idempotencyKey: string) =>
    request<ReviewActionResponse>(`/invoices/${enc(invoiceId)}/corrections`, {
      method: "POST",
      json: body,
      idempotencyKey,
    }),

  /** POST /api/invoices/{id}/approve — bound to `expected_version`. */
  approve: (invoiceId: string, body: ReviewDecisionBody, idempotencyKey: string) =>
    request<ReviewActionResponse>(`/invoices/${enc(invoiceId)}/approve`, {
      method: "POST",
      json: body,
      idempotencyKey,
    }),

  /** POST /api/invoices/{id}/decline — bound to `expected_version`. */
  decline: (invoiceId: string, body: ReviewDecisionBody, idempotencyKey: string) =>
    request<ReviewActionResponse>(`/invoices/${enc(invoiceId)}/decline`, {
      method: "POST",
      json: body,
      idempotencyKey,
    }),

  /** POST /api/invoices/{id}/corrected-submission (multipart/form-data). */
  correctedSubmission: (invoiceId: string, input: CorrectedSubmissionInput, idempotencyKey: string) => {
    const form = new FormData();
    form.append("expected_version", String(input.expected_version));
    form.append("reason", input.reason);
    form.append("reviewer", input.reviewer);
    if (input.mode) form.append("mode", input.mode);
    form.append("file", input.file, input.file.name);
    return request<ReviewActionResponse>(`/invoices/${enc(invoiceId)}/corrected-submission`, {
      method: "POST",
      body: form,
      idempotencyKey,
    });
  },
};
