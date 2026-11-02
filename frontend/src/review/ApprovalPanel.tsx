import { useId, useState } from "react";
import { reviewApi, type ReviewActionResponse, type ReviewAllowedActions, type ReviewFailure } from "../api/review";
import type { InvoiceDetail, Recommendation } from "../api/types";
import { formatMoney } from "../format";
import { findingText } from "../detail/findingCopy";
import { ReviewerAndReason } from "./ReviewerAndReason";
import { useReviewerName } from "./reviewer";
import { useReviewAction } from "./useReviewAction";

type Conflict = Extract<ReviewFailure, { kind: "conflict" }>;
export type Decision = "approve" | "decline";

const RECOMMENDATION: Record<Recommendation, string> = {
  approve: "Approve",
  reject: "Reject",
  review: "Needs review",
};

/** Codes the gate adds while waiting; they are why the wait exists, not failed checks. */
const WAIT_CODES = new Set(["model_disagreement"]);

/**
 * Human approval for `awaiting_human_approval` (high value or model disagreement): the
 * agent recommendation and critique, a required reason, and Decline / Approve mock payment,
 * both bound to the displayed version. Each control renders only when the server allows it.
 */
export function ApprovalPanel({
  detail,
  actions,
  onConflict,
  onDone,
}: {
  detail: InvoiceDetail;
  actions: ReviewAllowedActions;
  onConflict: (f: Conflict) => void;
  onDone: (decision: Decision, response: ReviewActionResponse) => void;
}) {
  const id = useId();
  const [reason, setReason] = useState("");
  const { reviewer, setReviewer, remember } = useReviewerName();
  const [errors, setErrors] = useState<{ reason?: string; reviewer?: string }>({});
  const { send, busy, failure } = useReviewAction(onConflict);
  const version = detail.current_version;
  const d = detail.decision;
  const disagreement = detail.findings.some((f) => f.code === "model_disagreement" && !f.resolved);
  const failedChecks = detail.findings.filter(
    (f) => !f.resolved && (f.severity === "blocker" || f.severity === "review") && !WAIT_CODES.has(f.code),
  );
  // Never an approve control on a rejected or needs-review invoice, whatever else is sent.
  const statusOk = actions.status === "awaiting_human_approval" && detail.status === "awaiting_human_approval";
  const canApprove = statusOk && actions.allowed.includes("approve");
  const canDecline = statusOk && actions.allowed.includes("decline");

  const act = async (decision: Decision) => {
    const next: typeof errors = {};
    if (!reason.trim()) next.reason = "Enter a review reason.";
    if (!reviewer.trim()) next.reviewer = "Enter your name.";
    setErrors(next);
    if (Object.keys(next).length > 0) return;
    const body = { expected_version: version, reason: reason.trim(), reviewer: reviewer.trim() };
    const call = decision === "approve" ? reviewApi.approve : reviewApi.decline;
    const out = await send(`${decision}:${detail.invoice_id}:${JSON.stringify(body)}`, (key) =>
      call(detail.invoice_id, body, key),
    );
    if (out) {
      remember(body.reviewer);
      onDone(decision, out);
    }
  };

  return (
    <section className="panel review-form" aria-labelledby={`${id}-title`}>
      <h3 id={`${id}-title`} className="eyebrow">
        Awaiting human approval · version {version}
      </h3>
      <p className="decision-message num">
        {formatMoney(detail.total, detail.currency)}
        {failedChecks.length === 0 ? " · All checks passed" : ""}
      </p>
      {disagreement ? (
        <p className="sub">
          All checks passed, but the model did not recommend approval. Payment waits for a person to
          approve or decline.
        </p>
      ) : (
        <p className="sub">Above the USD 10,000 auto-pay limit. Payment waits for a person to approve or decline.</p>
      )}
      {failedChecks.length > 0 && (
        <ul className="reasons">
          {failedChecks.map((f, i) => (
            <li key={`${f.code}-${i}`}>{findingText(f.code)}</li>
          ))}
        </ul>
      )}

      <dl className="checks" aria-label="Agent recommendation">
        <div className="check">
          <dt>Agent recommendation</dt>
          <dd>
            {d ? RECOMMENDATION[d.revised_recommendation ?? d.initial_recommendation] : "Not recorded"}
            {d && d.mode !== "live" ? " (simulated)" : ""}
          </dd>
        </div>
        <div className="check">
          <dt>Critique</dt>
          <dd>{d?.critique_summary ?? "No critique summary recorded."}</dd>
        </div>
      </dl>
      {d && d.reasons.length > 0 && (
        <>
          <h4 className="eyebrow">{disagreement ? "The model's stated reasons" : "Reasons"}</h4>
          <ul className="reasons" aria-label={disagreement ? "The model's stated reasons" : "Reasons"}>
            {d.reasons.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </>
      )}

      {(canApprove || canDecline) && (
        <>
          <ReviewerAndReason
            reviewer={reviewer}
            onReviewer={setReviewer}
            reason={reason}
            onReason={setReason}
            reasonLabel="Review reason"
            errors={errors}
            disabled={busy}
          />
          <div className="review-actions">
            {canDecline && (
              <button type="button" className="button button--secondary" disabled={busy} onClick={() => act("decline")}>
                Decline
              </button>
            )}
            {canApprove && (
              <button type="button" className="button button--primary" disabled={busy} onClick={() => act("approve")}>
                Approve mock payment
              </button>
            )}
          </div>
          <p className="sub">Payment waits for this action. It applies to version {version} only.</p>
        </>
      )}
      {failure && (
        <p className="field-error" role="alert">
          {failure.message}
        </p>
      )}
    </section>
  );
}
