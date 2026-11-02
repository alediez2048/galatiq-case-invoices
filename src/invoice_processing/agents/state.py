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
from invoice_processing.schemas import (
    ApprovalDecision,
    GateResult,
    MockReceipt,
    NormalizedInvoice,
    SourceDocument,
    ValidationFinding,
)


class InvoiceState(TypedDict, total=False):
    run_id: str
    mode: ExecutionMode
    evaluation_date: date
    source: SourceDocument
    raw: bytes
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


@dataclass
class Deps:
    conn: sqlite3.Connection
    provider: ReasoningProvider
    events: logging.Logger
    limits: Limits = DEFAULT_LIMITS


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
