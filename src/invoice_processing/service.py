"""Shared processing service: one entry point used by the CLI and tests."""

import logging
from datetime import date
from pathlib import Path

import langsmith

from invoice_processing import intake, ledger, observability
from invoice_processing.agents.state import Deps, InvoiceState, emit
from invoice_processing.codes import (
    TERMINAL_RUN_STATUSES,
    ExecutionMode,
    InvoiceStatus,
    RunStatus,
)
from invoice_processing.limits import DEFAULT_LIMITS, Limits
from invoice_processing.reasoning import ReasoningProvider, get_provider
from invoice_processing.schemas import ProcessingResult
from invoice_processing.storage import connect, init_schema
from invoice_processing.workflow import build_graph

_INVOICE_STATUS = {
    RunStatus.paid_mock: InvoiceStatus.paid_mock,
    RunStatus.rejected: InvoiceStatus.rejected,
    RunStatus.needs_review: InvoiceStatus.needs_review,
    RunStatus.awaiting_human_approval: InvoiceStatus.awaiting_human_approval,
    RunStatus.failed: InvoiceStatus.failed,
}


def _result(state: InvoiceState, **overrides) -> ProcessingResult:
    error_code = state.get("error_code")
    source = state.get("source")
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
    }
    fields.update(overrides)
    return ProcessingResult(**fields)


def process_invoice(
    path: str | Path,
    mode: ExecutionMode,
    db_path: str | Path,
    evaluation_date: date,
    events: logging.Logger | None = None,
    limits: Limits = DEFAULT_LIMITS,
    provider: ReasoningProvider | None = None,
) -> ProcessingResult:
    source, raw = intake.read_source(path, limits)  # IntakeError propagates; no run is created
    if events is None:
        events = observability.configure_events(None)
    provider = provider or get_provider(mode)  # config errors propagate before any run exists
    conn = connect(db_path)
    try:
        init_schema(conn)
        ledger.mark_interrupted_runs(conn, started_before=ledger.utcnow())
        ledger.record_source(conn, source)
        run_id = ledger.start_run(conn, mode, source.source_id, evaluation_date)
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
            )
            prior = ledger.find_prior_outcome(conn, source.content_hash)
            if prior is not None:
                ledger.finish_run(conn, run_id, RunStatus.duplicate, prior_run_id=prior.run_id)
                state["status"] = RunStatus.duplicate
                emit(deps, state, "service", "duplicate", prior_run_id=prior.run_id)
                return _result(
                    state,
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
            return _result(final)
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
            return _result(state, invoice_id=state.get("invoice_id"))
    finally:
        conn.close()
