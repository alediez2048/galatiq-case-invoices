/**
 * Processing-view state derived only from persisted audit events (P5-07, mockup screen 3).
 * No timers, percentages or invented activity: a stage changes when an event arrives.
 */
import type { RunProgress, StageEvent } from "../api/types";
import { failureKind, stageLabel, type FailureKind } from "../detail/findingCopy";

export type ProgressKey = "extract" | "check" | "review" | "pay";
export type ProgressState = "complete" | "active" | "pending" | "failed" | "skipped";

export interface ProgressStage {
  key: ProgressKey;
  label: string;
  state: ProgressState;
}

const STAGES: { key: ProgressKey; label: string; done: string[] }[] = [
  { key: "extract", label: "Extract details", done: ["extracted"] },
  { key: "check", label: "Check inventory", done: ["validated"] },
  { key: "review", label: "Review", done: ["decision"] },
  { key: "pay", label: "Pay", done: ["payment_succeeded", "paid"] },
];

/** Which UI stage an audit event belongs to (null for service bookkeeping events). */
export function stageOf(e: StageEvent): ProgressKey | null {
  switch (e.stage) {
    case "intake":
    case "ingestion":
      return "extract";
    case "validation":
      return "check";
    case "approval":
      return "review";
    case "payment":
      return "pay";
    case "model":
      return e.payload.agent === "ingestion" ? "extract" : "review";
    default:
      return null;
  }
}

export function progressStages(run: RunProgress): ProgressStage[] {
  const done = STAGES.map((s) =>
    run.events.some((e) => stageOf(e) === s.key && s.done.includes(e.event)),
  );
  const firstOpen = done.indexOf(false);
  return STAGES.map((s, i): ProgressStage => {
    let state: ProgressState;
    if (done[i]) state = "complete";
    else if (!run.terminal) state = i === firstOpen ? "active" : "pending";
    else if (run.status === "failed") state = i === firstOpen ? "failed" : "skipped";
    else state = "skipped";
    return { key: s.key, label: s.label, state };
  });
}

/** What the workflow is doing now, inferred from the last persisted event. */
export function activeMessage(run: RunProgress): string | null {
  if (run.terminal) return null;
  const last = run.events.at(-1);
  if (!last || last.event === "received") return "Extracting invoice details.";
  if (last.event === "model_call") return last.message;
  switch (last.event) {
    case "extracted":
      return "Checking requested quantities against local inventory.";
    case "validated":
      return run.mode === "offline"
        ? "Preparing the simulated recommendation."
        : "Requesting the recommendation from the model.";
    case "recommendation":
      return "Checking the recommendation against policy.";
    case "critique":
      return "Applying the payment policy.";
    case "decision":
      return last.payload.final_decision === "approved"
        ? "Recording the mock payment."
        : "Recording the outcome.";
    default:
      return "Processing.";
  }
}

export function paymentLine(run: RunProgress): string {
  const paid = run.events.some((e) => e.event === "payment_succeeded" || e.event === "paid");
  if (paid) return "Mock payment recorded. No real funds transferred.";
  if (run.status === "duplicate") return "Already processed. No additional payment.";
  if (run.terminal) return "Payment was not attempted.";
  return "Payment has not been attempted.";
}

/** Completed events shown under "Completed": everything persisted except bookkeeping. */
export function completedEvents(run: RunProgress): StageEvent[] {
  return run.events.filter((e) => stageOf(e) !== null || e.event === "duplicate");
}

export interface RunFailure {
  kind: FailureKind;
  headline: string;
  detail: string | null;
  /** Retry or a separate offline run make sense (provider failures, or flagged recoverable). */
  recoverable: boolean;
}

export function runFailure(run: RunProgress): RunFailure | null {
  if (!run.terminal || run.status !== "failed") return null;
  const code = run.error_code ?? run.result?.errors[0] ?? null;
  const kind = failureKind(code);
  const detail = run.error_message ?? run.result?.error_message ?? null;
  const recoverable = kind === "provider" || run.result?.recoverable === true;
  switch (kind) {
    case "provider":
      return { kind, recoverable, headline: "Model request failed. Payment was not attempted.", detail };
    case "unreadable":
      return { kind, recoverable, headline: "We could not read this invoice.", detail };
    case "ocr":
      return {
        kind,
        recoverable,
        headline: "This PDF needs OCR, which this prototype does not support.",
        detail: "Submit a text-based version or inspect the source outside the app.",
      };
    case "oversized":
      return { kind, recoverable, headline: "File exceeds the 10 MiB limit.", detail };
    case "processing": {
      const stage = run.events.filter((e) => stageOf(e) !== null).at(-1)?.stage ?? run.current_stage;
      return { kind, recoverable, headline: `Processing stopped during ${stageLabel(stage)}.`, detail };
    }
  }
}
