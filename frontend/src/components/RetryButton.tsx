import { useCallback } from "react";
import { useNavigate } from "react-router";
import { useRetryRun } from "../api/hooks";
import type { RetryAction } from "../api/types";

const LABEL: Record<RetryAction, { idle: string; busy: string; tone: string }> = {
  retry: { idle: "Retry", busy: "Retrying…", tone: "button--primary" },
  run_offline: {
    idle: "Run offline as a separate simulation",
    busy: "Starting offline simulation…",
    tone: "button--secondary",
  },
};

/**
 * One explicit recovery action for a failed run (P3-08): posts once with its own
 * idempotency key, then follows the new linked run on the processing view. A refusal
 * (already paid, not recoverable, …) shows the server's message next to the button.
 */
export function RetryButton({ runId, action = "retry" }: { runId: string; action?: RetryAction }) {
  const navigate = useNavigate();
  const onDone = useCallback((newRun: string) => navigate(`/runs/${encodeURIComponent(newRun)}`), [navigate]);
  const { retry, busy, error } = useRetryRun(runId, onDone, action);
  const label = LABEL[action];
  return (
    <>
      <button type="button" className={`button ${label.tone}`} onClick={retry} disabled={busy}>
        {busy ? label.busy : label.idle}
      </button>
      {error && (
        <p className="field-error" role="status">
          {error}
        </p>
      )}
    </>
  );
}
