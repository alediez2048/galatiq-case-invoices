import type { InvoiceDetail, MockReceipt, RunSummary, ValidationFinding } from "../api/types";
import { decimalSubtract, formatMoney } from "../format";
import {
  blockingClause,
  failureKind,
  missingFieldsMessage,
  rankedFindings,
  stageLabel,
  type FailureKind,
} from "./findingCopy";

/** Latest run first by start time; the API is expected to return runs newest first already. */
export function latestRun(detail: InvoiceDetail): RunSummary | undefined {
  return [...detail.runs].sort((a, b) => b.started_at.localeCompare(a.started_at))[0];
}

/** Receipt paid against an earlier version (revision-after-payment / version views). */
export function priorReceipt(detail: InvoiceDetail): MockReceipt | null {
  const earlier = detail.versions
    .filter((v) => v.version !== detail.current_version && v.receipt)
    .sort((a, b) => b.version - a.version)[0];
  return earlier?.receipt ?? detail.receipt ?? null;
}

export function hasFinding(detail: InvoiceDetail, code: string): ValidationFinding | undefined {
  return detail.findings.find((f) => f.code === code && !f.resolved);
}

/** "Stated total exceeds calculated total by USD 50.00." from a total_mismatch finding. */
export function totalsMessage(detail: InvoiceDetail): string | null {
  const finding = hasFinding(detail, "total_mismatch");
  if (!finding) return null;
  const stated = finding.observed ?? detail.stated.total ?? null;
  const calculated = finding.expected ?? detail.computed?.total ?? null;
  if (!stated || !calculated) return "Stated total does not match the calculated total.";
  const diff = decimalSubtract(stated, calculated);
  if (diff === null) return "Stated total does not match the calculated total.";
  const negative = diff.startsWith("-");
  const amount = formatMoney(negative ? diff.slice(1) : diff, detail.currency);
  return negative
    ? `Stated total is below calculated total by ${amount}.`
    : `Stated total exceeds calculated total by ${amount}.`;
}

export interface FailureInfo {
  kind: FailureKind;
  code: string | null;
  headline: string;
  detail: string | null;
  run?: RunSummary;
}

/** Explains a failed invoice using the latest run's persisted error code and stage. */
export function failureInfo(detail: InvoiceDetail): FailureInfo | null {
  const run = latestRun(detail);
  const result = detail.latest_result;
  const failed = detail.status === "failed" || run?.status === "failed" || result?.status === "failed";
  if (!failed) return null;
  const code = run?.error_code ?? result?.errors[0] ?? null;
  const message = run?.error_message ?? result?.error_message ?? null;
  const kind = failureKind(code);
  const lastStage = run?.events.length ? run.events[run.events.length - 1]?.stage : undefined;
  switch (kind) {
    case "unreadable":
      return { kind, code, run, headline: "We could not read this invoice.", detail: message };
    case "ocr":
      return {
        kind,
        code,
        run,
        headline: "This PDF needs OCR, which this prototype does not support.",
        detail: "Submit a text-based version or inspect the source outside the app.",
      };
    case "oversized":
      return {
        kind,
        code,
        run,
        headline: "File exceeds the 10 MiB limit.",
        detail: "Choose a smaller file. No run was started.",
      };
    case "provider":
      return {
        kind,
        code,
        run,
        headline: "Model request failed. Payment was not attempted.",
        detail: message,
      };
    case "processing":
      return {
        kind,
        code,
        run,
        headline: `Processing stopped during ${stageLabel(lastStage)}.`,
        detail: message,
      };
  }
}

export type StageState = "complete" | "active" | "pending" | "failed" | "skipped" | "attention";

export interface Stage {
  key: "extract" | "validate" | "approve" | "pay";
  label: string;
  state: StageState;
}

/**
 * Summary strip derived from the persisted outcome (not animated). Labels follow mockup
 * screen 5; the state words are shown as text next to each symbol.
 */
export function stageStrip(detail: InvoiceDetail): Stage[] {
  const s = (
    extract: StageState,
    validate: StageState,
    approve: StageState,
    pay: StageState,
  ): Stage[] => [
    { key: "extract", label: "Extracted", state: extract },
    { key: "validate", label: "Validated", state: validate },
    { key: "approve", label: "Approved", state: approve },
    { key: "pay", label: "Mock paid", state: pay },
  ];
  const ranked = rankedFindings(detail.findings);
  const blocker = ranked.some((f) => f.severity === "blocker");
  switch (detail.status) {
    case "paid_mock":
      return s("complete", "complete", "complete", "complete");
    case "rejected":
      return blocker
        ? s("complete", "failed", "skipped", "skipped")
        : s("complete", "complete", "failed", "skipped");
    case "needs_review":
      return ranked.some((f) => f.severity === "review")
        ? s("complete", "attention", "skipped", "skipped")
        : s("complete", "complete", "attention", "skipped");
    case "awaiting_human_approval":
      return s("complete", "complete", "active", "pending");
    case "processing":
      return s("active", "pending", "pending", "pending");
    case "failed": {
      const kind = failureInfo(detail)?.kind;
      if (kind === "provider") return s("complete", "complete", "failed", "skipped");
      if (kind === "unreadable" || kind === "ocr" || kind === "oversized")
        return s("failed", "skipped", "skipped", "skipped");
      const stage = latestRun(detail)?.events.at(-1)?.stage;
      if (stage === "validation") return s("complete", "failed", "skipped", "skipped");
      if (stage === "approval") return s("complete", "complete", "failed", "skipped");
      if (stage === "payment") return s("complete", "complete", "complete", "failed");
      return s("failed", "skipped", "skipped", "skipped");
    }
    default:
      return s("complete", "complete", "skipped", "skipped");
  }
}

/** Decision headline for the right-hand panel. */
export function decisionHeadline(detail: InvoiceDetail): { title: string; sub: string | null } {
  const ranked = rankedFindings(detail.findings);
  switch (detail.status) {
    case "paid_mock":
      return {
        title: "Mock payment complete.",
        sub:
          ranked.some((f) => f.severity === "blocker" || f.severity === "review")
            ? null
            : "Inventory and totals passed. No unresolved payment blockers.",
      };
    case "rejected": {
      const primary = ranked.find((f) => f.severity === "blocker") ?? ranked[0];
      return {
        title: primary ? `Payment blocked: ${blockingClause(primary)}.` : "Payment blocked.",
        sub: "Payment was not attempted.",
      };
    }
    case "needs_review": {
      if (hasFinding(detail, "revision_after_payment")) {
        return {
          title: "Earlier version already mock paid. Revised version blocked from additional payment.",
          sub: null,
        };
      }
      const primary = ranked.find((f) => f.severity === "review") ?? ranked[0];
      return {
        title: "Invoice needs review.",
        sub: primary ? blockingClauseSentence(primary) : null,
      };
    }
    case "awaiting_human_approval":
      return { title: "Waiting for human approval.", sub: "Payment waits for this action." };
    case "failed":
      return { title: failureInfo(detail)?.headline ?? "Processing failed.", sub: null };
    case "processing":
      return { title: "Processing.", sub: "Payment has not been attempted." };
    case "superseded":
      return { title: "Superseded by a newer version.", sub: null };
  }
}

function blockingClauseSentence(f: ValidationFinding): string {
  const clause = blockingClause(f);
  return `${clause.charAt(0).toUpperCase()}${clause.slice(1)}.`;
}

export { missingFieldsMessage };
