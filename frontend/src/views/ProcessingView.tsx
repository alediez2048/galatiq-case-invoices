import { useEffect } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { useRunProgress } from "../api/hooks";
import { isReviewRun, type RunProgress } from "../api/types";
import { MODE_LABEL } from "../format";
import { Icon, type IconName } from "../components/Icon";
import { RetryButton } from "../components/RetryButton";
import {
  activeMessage,
  completedEvents,
  paymentLine,
  progressStages,
  runFailure,
  type RunFailure,
  type ProgressState,
} from "../processing/progress";

const OFFLINE_ACTION = "run offline as a separate simulation";

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
 * Recoverable failure (P3-08): Retry reprocesses in the run's own mode as a new linked run;
 * "Run offline as a separate simulation" is offered only where the server lists it (live
 * model failures), and never for a correction or human-review run: re-extracting the
 * document would discard the review (the API refuses it). Nothing is substituted
 * automatically.
 */
function RecoveryActions({ run, failure }: { run: RunProgress; failure: RunFailure }) {
  const offline =
    !isReviewRun(run) &&
    (run.result
      ? (run.result.next_actions ?? []).includes(OFFLINE_ACTION)
      : run.mode === "live" && failure.kind === "provider");
  return (
    <div className="recovery">
      <div className="modal__actions">
        <RetryButton runId={run.run_id} />
        {offline && <RetryButton runId={run.run_id} action="run_offline" />}
      </div>
      <p className="sub">Each action starts a new run linked to this one. Payment still happens at most once.</p>
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
      {failure.recoverable && <RecoveryActions run={run} failure={failure} />}
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
      {/* Completion is announced exactly once: this region is always mounted and its text
          changes a single time. Failure is announced by the role="alert" notice below. */}
      <p className="visually-hidden" role="status" data-testid="run-announcer">
        {run.terminal && run.status !== "failed" ? "Processing finished." : ""}
      </p>
      <p className="progress-active" aria-live={run.terminal ? "off" : "polite"}>
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
