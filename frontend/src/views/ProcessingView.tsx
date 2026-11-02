import { useEffect, useId } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { useRunProgress } from "../api/hooks";
import type { RunProgress } from "../api/types";
import { MODE_LABEL } from "../format";
import { Icon, type IconName } from "../components/Icon";
import {
  activeMessage,
  completedEvents,
  paymentLine,
  progressStages,
  runFailure,
  type ProgressState,
} from "../processing/progress";

const ICON: Record<ProgressState, IconName> = {
  complete: "check",
  active: "spinner",
  pending: "pending",
  failed: "cross",
  skipped: "skipped",
};

const WORD: Record<ProgressState, string> = {
  complete: "complete",
  active: "in progress",
  pending: "pending",
  failed: "failed",
  skipped: "skipped",
};

function Stages({ run }: { run: RunProgress }) {
  return (
    <ol className="progress-stages" aria-label="Processing stages">
      {progressStages(run).map((s) => (
        <li key={s.key} className={`stage stage--${s.state}`} data-state={s.state}>
          <Icon name={ICON[s.state]} />
          <span>{s.label}</span>
          <span className="visually-hidden">: {WORD[s.state]}</span>
        </li>
      ))}
    </ol>
  );
}

/**
 * Recoverable failure: Retry and "Run offline as a separate simulation" are shown but
 * disabled until the retry endpoint exists.
 * TODO(P3-08): wire Retry to POST /api/runs/{id}/retry (useRetryRun) and the offline action
 * to a new offline submission of the same source, then enable both.
 */
function RecoveryActions() {
  const noteId = useId();
  return (
    <div className="recovery">
      <div className="modal__actions">
        <button type="button" className="button button--primary" disabled aria-describedby={noteId}>
          Retry
        </button>
        <button type="button" className="button button--secondary" disabled aria-describedby={noteId}>
          Run offline as a separate simulation
        </button>
      </div>
      <p className="sub" id={noteId}>
        Retry is not available in this build yet; it arrives with the live-mode retry endpoint.
        Nothing was substituted and no payment was attempted.
      </p>
    </div>
  );
}

function Failure({ run }: { run: RunProgress }) {
  const failure = runFailure(run);
  if (!failure) return null;
  return (
    <section className="state-notice state-notice--danger" aria-label="Processing failure" role="alert">
      <p className="state-notice__title">
        <Icon name="warning" />
        {failure.headline}
      </p>
      {failure.detail && <p className="sub">{failure.detail}</p>}
      <p className="sub">Mode of this run: {MODE_LABEL[run.mode]}</p>
      {failure.recoverable && <RecoveryActions />}
      <div className="modal__actions">
        {(failure.kind === "unreadable" || failure.kind === "ocr" || failure.kind === "oversized") && (
          <Link to="/add" className="button button--secondary">
            Replace file
          </Link>
        )}
        {run.invoice_id && (
          <Link to={`/invoices/${encodeURIComponent(run.invoice_id)}`} className="button button--ghost">
            Open invoice
          </Link>
        )}
      </div>
    </section>
  );
}

function Progress({ run }: { run: RunProgress }) {
  const active = activeMessage(run);
  const done = completedEvents(run);
  return (
    <>
      <Stages run={run} />
      <p className="progress-active" aria-live="polite">
        {active ?? (run.status === "failed" ? "Processing stopped." : "Processing finished.")}
      </p>
      {done.length > 0 && (
        <>
          <h2 className="eyebrow">Completed</h2>
          <ol className="events progress-events" aria-label="Completed steps">
            {done.map((e) => (
              <li key={e.sequence}>
                <Icon name="check" /> {e.message}
              </li>
            ))}
          </ol>
        </>
      )}
      <p className="strong payment-line">{paymentLine(run)}</p>
      <Failure run={run} />
    </>
  );
}

/**
 * Processing view (mockup screen 3). Polls the persisted run; stages move only when an audit
 * event arrives. No cancel or background controls. Opens the invoice detail once the run
 * reaches a business outcome or is a duplicate; failures stay here with their explanation.
 */
export function ProcessingView() {
  const { runId } = useParams();
  const navigate = useNavigate();
  const { data: run, error } = useRunProgress(runId);

  const target =
    run?.terminal && run.status !== "failed" && run.invoice_id
      ? `/invoices/${encodeURIComponent(run.invoice_id)}`
      : null;
  useEffect(() => {
    if (target) navigate(target, { replace: true });
  }, [target, navigate]);

  return (
    <section className="panel processing" aria-labelledby="processing-title">
      <div className="panel__title">
        <h1 id="processing-title">
          {run ? (
            <>
              Processing <span className="mono">{run.source.original_name}</span>
            </>
          ) : (
            "Processing"
          )}
        </h1>
        {run && (
          <span className="pill mode-badge" data-mode={run.mode}>
            {MODE_LABEL[run.mode]}
          </span>
        )}
      </div>
      {!run && !error && <p className="sub">Loading run…</p>}
      {error && (
        <p className={run ? "sub" : "field-error"} role={run ? undefined : "alert"}>
          {error.status === 404
            ? "This run was not found."
            : `Lost contact with the local API; still trying. ${error.message}`}
        </p>
      )}
      {run && <Progress run={run} />}
      {target && <p className="sub">Opening the invoice…</p>}
    </section>
  );
}
