import type { InvoiceStatus, Outcome, RunStatus } from "../api/types";
import { Icon, type IconName } from "./Icon";

interface StatusSpec {
  label: string;
  icon: IconName;
  tone: "success" | "danger" | "warning" | "neutral" | "info";
}

/** One text label and one distinct icon per outcome; colour is a secondary cue only. */
export const OUTCOME_SPEC: Record<Outcome, StatusSpec> = {
  paid_mock: { label: "Mock paid", icon: "check", tone: "success" },
  rejected: { label: "Rejected", icon: "cross", tone: "danger" },
  needs_review: { label: "Needs review", icon: "alert", tone: "warning" },
  awaiting_human_approval: { label: "Awaiting approval", icon: "hourglass", tone: "info" },
  failed: { label: "Failed", icon: "warning", tone: "danger" },
  duplicate: { label: "Duplicate", icon: "copy", tone: "neutral" },
  processing: { label: "Processing", icon: "spinner", tone: "neutral" },
};

const SUPERSEDED: StatusSpec = { label: "Superseded", icon: "superseded", tone: "neutral" };

/** Run statuses that are not terminal render as processing. */
export function toOutcome(status: InvoiceStatus | RunStatus): Outcome | "superseded" {
  switch (status) {
    case "paid_mock":
    case "rejected":
    case "needs_review":
    case "awaiting_human_approval":
    case "failed":
    case "duplicate":
    case "processing":
    case "superseded":
      return status;
    default:
      return "processing";
  }
}

export function statusLabel(status: InvoiceStatus | RunStatus): string {
  const outcome = toOutcome(status);
  return outcome === "superseded" ? SUPERSEDED.label : OUTCOME_SPEC[outcome].label;
}

export function StatusBadge({ status }: { status: InvoiceStatus | RunStatus }) {
  const outcome = toOutcome(status);
  const spec = outcome === "superseded" ? SUPERSEDED : OUTCOME_SPEC[outcome];
  return (
    <span className={`status status--${spec.tone}`} data-outcome={outcome}>
      <Icon name={spec.icon} className={outcome === "processing" ? "icon--spin" : undefined} />
      <span>{spec.label}</span>
    </span>
  );
}
