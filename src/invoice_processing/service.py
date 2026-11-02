"""Shared processing service: one entry point used by the CLI and tests."""

import logging
import sqlite3
from collections.abc import Callable
from datetime import date
from pathlib import Path

import langsmith

from invoice_processing import intake, ledger, observability
from invoice_processing.agents.state import Deps, InvoiceState, emit
from invoice_processing.codes import (
    TERMINAL_RUN_STATUSES,
    ExecutionMode,
    InvoiceStatus,
    ModelErrorCode,
    RunStatus,
)
from invoice_processing.limits import DEFAULT_LIMITS, Limits
from invoice_processing.reasoning import ReasoningProvider, get_provider
from invoice_processing.schemas import ProcessingResult, SourceDocument
from invoice_processing.storage import connect, init_schema
from invoice_processing.workflow import build_graph

_INVOICE_STATUS = {
    RunStatus.paid_mock: InvoiceStatus.paid_mock,
    RunStatus.rejected: InvoiceStatus.rejected,
    RunStatus.needs_review: InvoiceStatus.needs_review,
    RunStatus.awaiting_human_approval: InvoiceStatus.awaiting_human_approval,
    RunStatus.failed: InvoiceStatus.failed,
}


RECOVERY_ACTIONS = ["retry", "run offline as a separate simulation"]
_MODEL_ERROR_CODES = frozenset(c.value for c in ModelErrorCode)


def _call_budget(provider: ReasoningProvider) -> int | None:
    """The per-invoice model budget of a live provider; None offline (no model calls)."""
    settings = getattr(provider, "settings", None)
    return None if settings is None else settings.call_budget


def _result(state: InvoiceState, budget: int | None, **overrides) -> ProcessingResult:
    error_code = state.get("error_code")
    source = state.get("source")
    if error_code in _MODEL_ERROR_CODES:
        next_actions = list(RECOVERY_ACTIONS)
    elif error_code == "unexpected_error":
        next_actions = ["retry"]  # an offline simulation would not fix it
    else:
        next_actions = []
    recoverable = bool(next_actions)
    fields = {
        "run_id": state["run_id"],
        "invoice_id": state.get("invoice_id"),
        "status": state["status"],
        "mode": state["mode"],
        "findings": state.get("findings", []),
        "decision": state.get("decision"),
        "receipt": state.get("receipt"),
        "prior_run_id": state.get("prior_run_id"),
        "timings_ms": state.get("timings_ms", {}),
        "errors": [error_code] if error_code else [],
        "error_message": state.get("error_message"),
        "source_hash": source.content_hash if source is not None else None,
        "evaluation_date": state.get("evaluation_date"),
        "model_calls_used": state.get("model_calls_used", 0),
        "model_calls_budget": budget,
        "recoverable": recoverable,
        "next_actions": next_actions,
    }
    fields.update(overrides)
    return ProcessingResult(**fields)


class RetryRefused(RuntimeError):
    """`retry_run` will not retry this run; `reason` is a stable code."""

    def __init__(self, reason: str, run_id: str, receipt_id: str | None = None) -> None:
        super().__init__(f"run {run_id} cannot be retried: {reason}")
        self.reason = reason
        self.run_id = run_id
        self.receipt_id = receipt_id  # set for already_paid: the existing receipt


# Failures a retry can fix: model errors, a crash (startup sweep) or an unexpected exception.
# Extraction and payment-refusal codes are deterministic; the same file fails the same way.
RETRYABLE_ERROR_CODES = _MODEL_ERROR_CODES | {"interrupted", "unexpected_error"}


def _check_retry(conn: sqlite3.Connection, run_id: str, content_hash: str) -> ledger.RunSummary:
    run = ledger.get_run(conn, run_id)
    if run is None:
        raise RetryRefused("unknown_run", run_id)
    if run.status is not RunStatus.failed:
        raise RetryRefused("not_failed", run_id)
    if run.error_code not in RETRYABLE_ERROR_CODES:
        raise RetryRefused("not_recoverable", run_id)
    if run.content_hash != content_hash:
        raise RetryRefused("source_mismatch", run_id)
    # Another (non-failed) run already paid this version: a retry would only re-decide a
    # paid identity. A payer that crashed after paying is retried and re-pointed instead.
    receipt_id = ledger.payment_outside_retry_chain(conn, run_id)
    if receipt_id is not None:
        raise RetryRefused("already_paid", run_id, receipt_id)
    return run


def _open_for_retry(db_path: str | Path, run_id: str) -> sqlite3.Connection:
    """Open an existing ledger for a retry: a database without a schema has no runs, so it
    is refused as unknown_run rather than initialized. Runs the startup sweep, so a crashed
    run becomes a retryable `interrupted` failure."""
    conn = connect(db_path)
    try:
        if conn.execute("PRAGMA user_version").fetchone()[0] == 0:
            raise RetryRefused("unknown_run", run_id)
        init_schema(conn)  # version check only: every table already exists
        ledger.mark_interrupted_runs(conn, started_before=ledger.utcnow())
    except BaseException:
        conn.close()
        raise
    return conn


def check_retry(
    run_id: str, path: str | Path, db_path: str | Path, limits: Limits = DEFAULT_LIMITS
) -> ledger.RunSummary:
    """The failed run `retry_run` would retry, or RetryRefused. Creates no run; the only
    write is the startup sweep (see `_open_for_retry`)."""
    source, _ = intake.read_source(path, limits)
    conn = _open_for_retry(db_path, run_id)
    try:
        return _check_retry(conn, run_id, source.content_hash)
    finally:
        conn.close()


def retry_run(
    run_id: str,
    path: str | Path,
    db_path: str | Path,
    evaluation_date: date,
    events: logging.Logger | None = None,
    provider: ReasoningProvider | None = None,
    limits: Limits = DEFAULT_LIMITS,
    on_run_started: Callable[[str], None] | None = None,
) -> ProcessingResult:
    """Process `path` again as a new run linked to the failed `run_id` (`retry_of`), in the
    original run's mode. The ledger keeps no source bytes, so the caller re-supplies the
    file; it must hash to the original source. Payment stays once per identity."""
    source, raw = intake.read_source(path, limits)
    conn = _open_for_retry(db_path, run_id)
    try:
        original = _check_retry(conn, run_id, source.content_hash)
    finally:
        conn.close()
    return _process(
        source,
        raw,
        original.mode,
        db_path,
        evaluation_date,
        events,
        limits,
        provider,
        retry_of=original.run_id,
        on_run_started=on_run_started,
    )


def process_invoice(
    path: str | Path,
    mode: ExecutionMode,
    db_path: str | Path,
    evaluation_date: date,
    events: logging.Logger | None = None,
    limits: Limits = DEFAULT_LIMITS,
    provider: ReasoningProvider | None = None,
    on_run_started: Callable[[str], None] | None = None,
) -> ProcessingResult:
    """`on_run_started(run_id)` is called once the run row exists, before any work runs."""
    source, raw = intake.read_source(path, limits)  # IntakeError propagates; no run is created
    return _process(
        source,
        raw,
        mode,
        db_path,
        evaluation_date,
        events,
        limits,
        provider,
        on_run_started=on_run_started,
    )


def _process(
    source: SourceDocument,
    raw: bytes,
    mode: ExecutionMode,
    db_path: str | Path,
    evaluation_date: date,
    events: logging.Logger | None,
    limits: Limits,
    provider: ReasoningProvider | None,
    retry_of: str | None = None,
    on_run_started: Callable[[str], None] | None = None,
) -> ProcessingResult:
    if events is None:
        events = observability.configure_events(None)
    provider = provider or get_provider(mode)  # config errors propagate before any run exists
    budget = _call_budget(provider)
    conn = connect(db_path)
    try:
        init_schema(conn)
        ledger.mark_interrupted_runs(conn, started_before=ledger.utcnow())
        ledger.record_source(conn, source)  # source_id derives from the content hash
        # The same bytes in the other mode: a labeled switch, never a byte-level duplicate.
        # It reads no earlier decision (decisions are per run); payment still decides.
        mode_switch_of = ledger.latest_run_in_other_mode(conn, source.source_id, mode)
        run_id = ledger.start_run(
            conn,
            mode,
            source.source_id,
            evaluation_date,
            retry_of=retry_of,
            mode_switch_of=mode_switch_of,
        )
        if on_run_started is not None:
            on_run_started(run_id)
        deps = Deps(conn=conn, provider=provider, events=events, limits=limits)
        state = InvoiceState(
            run_id=run_id,
            mode=mode,
            evaluation_date=evaluation_date,
            source=source,
            raw=raw,
            status=RunStatus.received,
        )
        try:
            emit(
                deps,
                state,
                "intake",
                "received",
                source_hash=source.content_hash,
                original_name=source.original_name,
                mode=mode.value,
                retry_of=retry_of,
                mode_switch_of=mode_switch_of,
            )
            # Retries and mode switches skip the byte-level check; the identity check in
            # ingestion still runs (and never pays an identity twice).
            exempt = retry_of is not None or mode_switch_of is not None
            prior = None if exempt else ledger.find_prior_outcome(conn, source.content_hash)
            if prior is not None:
                ledger.finish_run(conn, run_id, RunStatus.duplicate, prior_run_id=prior.run_id)
                state["status"] = RunStatus.duplicate
                emit(deps, state, "service", "duplicate", prior_run_id=prior.run_id)
                return _result(
                    state,
                    budget,
                    invoice_id=prior.invoice_id,
                    receipt=prior.receipt,
                    prior_run_id=prior.run_id,
                )

            # LangSmith tracing is forced off in every mode: invoice bytes must not reach a
            # third-party tracer through LANGSMITH_TRACING/LANGCHAIN_TRACING_V2 by accident.
            trace_off = langsmith.tracing_context(enabled=False)
            with trace_off:
                final: InvoiceState = build_graph(deps).invoke(state)
            status = final["status"]
            error_code = final.get("error_code")
            if status not in TERMINAL_RUN_STATUSES:
                status, error_code = RunStatus.failed, "incomplete_graph"
                final = {**final, "status": status, "error_code": error_code}
            ledger.finish_run(
                conn,
                run_id,
                status,
                error_code=error_code,
                error_message=final.get("error_message"),
                prior_run_id=final.get("prior_run_id"),
            )
            invoice_id = final.get("invoice_id")
            if invoice_id is not None and status in _INVOICE_STATUS:
                ledger.set_invoice_status(conn, invoice_id, _INVOICE_STATUS[status])
            emit(deps, final, "service", "finished", errors=[error_code] if error_code else [])
            return _result(final, budget)
        except Exception as e:  # BaseException (Ctrl-C) propagates; mark_interrupted_runs recovers
            current = ledger.get_run_status(conn, run_id)
            if current not in TERMINAL_RUN_STATUSES:
                ledger.finish_run(
                    conn,
                    run_id,
                    RunStatus.failed,
                    error_code="unexpected_error",
                    error_message=type(e).__name__,
                )
                current = RunStatus.failed
            state["status"] = current
            state["error_code"] = "unexpected_error"
            emit(deps, state, "service", "failed", error_type=type(e).__name__)
            return _result(state, budget, invoice_id=state.get("invoice_id"))
    finally:
        conn.close()
