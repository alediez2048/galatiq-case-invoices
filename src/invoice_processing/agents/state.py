"""Shared graph state, dependencies, and the single audit/log emit path."""

import logging
import sqlite3
from dataclasses import dataclass
from datetime import date
from typing import Any, TypedDict

from invoice_processing import ledger, observability
from invoice_processing.codes import ExecutionMode, FindingCode, RunStatus
from invoice_processing.limits import DEFAULT_LIMITS, Limits
from invoice_processing.reasoning.base import ReasoningProvider
from invoice_processing.reasoning.session import ModelSession
from invoice_processing.schemas import (
    ApprovalDecision,
    GateResult,
    MockReceipt,
    NormalizedInvoice,
    SourceDocument,
    SupersedeLink,
    ValidationFinding,
)
from invoice_processing.tools import Dispatcher, ReadOnlyConnection, ToolContext


class InvoiceState(TypedDict, total=False):
    run_id: str
    mode: ExecutionMode
    evaluation_date: date
    source: SourceDocument
    raw: bytes
    source_text: str | None  # decoded raw text, or extracted PDF text; for model tools
    invoice: NormalizedInvoice
    invoice_id: str
    version_id: str
    version: int
    findings: list[ValidationFinding]
    decision: ApprovalDecision
    gate: GateResult
    receipt: MockReceipt | None
    prior_run_id: str
    status: RunStatus
    error_code: str
    error_message: str
    timings_ms: dict[str, int]
    model_calls_used: int  # budget units spent so far this run, carried between nodes
    trigger: str  # what created the run: submission, correction, human_review, ...
    review_of: str  # for a review-created run: the run it continues
    supersede: SupersedeLink | None  # a corrected submission: the invoice it replaces


@dataclass
class Deps:
    conn: sqlite3.Connection
    provider: ReasoningProvider
    events: logging.Logger
    limits: Limits = DEFAULT_LIMITS


def make_session(deps: Deps, state: InvoiceState) -> ModelSession:
    """A model session for one node; live providers also get the read-only tool dispatcher.

    The budget is per invoice: the session starts from the units earlier nodes spent, and
    the node returns `session.used` as the new `model_calls_used`.
    """
    session = ModelSession.for_provider(deps.provider)
    session.used = state.get("model_calls_used", 0)
    settings = getattr(deps.provider, "settings", None)
    if settings is not None:
        ctx = ToolContext(
            conn=ReadOnlyConnection(deps.conn),
            run_id=state["run_id"],
            invoice=state.get("invoice"),
            invoice_id=state.get("invoice_id"),
            version_id=state.get("version_id"),
            source_text=state.get("source_text"),
        )
        session.tools = Dispatcher(ctx, excerpt_chars=settings.excerpt_chars, audit_conn=deps.conn)
    return session


def emit(
    deps: Deps,
    state: InvoiceState,
    stage: str,
    event: str,
    *,
    codes: list[FindingCode] | None = None,
    **payload: Any,
) -> None:
    """Record one event in the audit table and the JSONL log."""
    source = state.get("source")
    status = state.get("status")
    mode = state.get("mode")
    fields: dict[str, Any] = {
        "status": status.value if status is not None else None,
        "mode": mode.value if mode is not None else None,
        "source_hash": source.content_hash if source is not None else None,
    }
    if codes is not None:
        fields["codes"] = [c.value for c in codes]
    fields.update(payload)
    ledger.append_audit_event(
        deps.conn,
        state.get("run_id"),
        stage,
        event,
        fields,
        invoice_id=state.get("invoice_id"),
        version_id=state.get("version_id"),
    )
    observability.log_event(
        deps.events, run_id=state.get("run_id"), stage=stage, event=event, **fields
    )


def emit_model_calls(
    deps: Deps, state: InvoiceState, session: ModelSession, agent: str, prompt_version: str | None
) -> None:
    """One `model_call` audit event per attempt the session recorded (counts, never text)."""
    provider = deps.provider
    for call in session.calls:
        emit(
            deps,
            state,
            "model",
            "model_call",
            agent=agent,
            step=call.step,
            attempt=call.attempt,
            latency_ms=call.latency_ms,
            input_tokens=call.input_tokens,
            output_tokens=call.output_tokens,
            tool_turns=call.tool_turns,
            provider=provider.provider,
            model=provider.model,
            prompt_version=prompt_version,
        )
