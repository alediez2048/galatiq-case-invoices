"""Human review actions (Phase 4). Each action checks the expected version and status inside
one write transaction, records an immutable row, creates the run that continues the work and
commits; the run is then executed by `service.run_existing_version` with no transaction open.

Refusals raise `ReviewRefused` with a stable code and the invoice's current actions.
"""

import logging
import re
import sqlite3
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from invoice_processing import evidence, ledger, normalize, policy, service
from invoice_processing.codes import (
    ExecutionMode,
    FindingCode,
    HumanReviewAction,
    InvoiceStatus,
    ReviewAction,
    ReviewRefusal,
    RunStatus,
    SourceFormat,
)
from invoice_processing.reasoning import ReasoningProvider, get_provider
from invoice_processing.reasoning.base import NoModelProvider
from invoice_processing.schemas import (
    AllowedActions,
    Correction,
    CorrectionRequest,
    EvidenceRef,
    FieldChange,
    HumanReview,
    MockReceipt,
    NormalizationEvent,
    NormalizedInvoice,
    ProcessingResult,
    ValidationFinding,
)
from invoice_processing.storage import connect, init_schema, write_transaction

R = ReviewRefusal
MESSAGES: dict[ReviewRefusal, str] = {
    R.unknown_invoice: "There is no invoice with this id.",
    R.stale_version: "The invoice changed since it was loaded. Reload it and try again.",
    R.action_not_allowed: "This action is not available for the invoice in its current state.",
    R.already_paid: "This invoice has already been paid.",
    R.field_not_correctable: "This field cannot be corrected on this invoice.",
    R.identity_correction_deferred: (
        "The vendor or invoice number cannot be changed by a correction. "
        "Submit a corrected invoice from the vendor."
    ),
    R.invalid_value: "The new value is not a valid value for this field.",
    R.correction_not_in_source: (
        "This value is not what the invoice says. Submit a corrected invoice from the vendor."
    ),
    R.evidence_location_mismatch: "The cited location is not where the invoice states this field.",
    R.evidence_unavailable: "This version has no recorded evidence to check a correction against.",
    R.source_text_unavailable: "The invoice text is not stored, so a correction cannot be checked.",
    R.corrected_identity_mismatch: (
        "The corrected invoice has a different vendor or invoice number."
    ),
}


class ReviewRefused(Exception):
    """A refused review action: `code` is stable; `current` is the invoice's fresh state
    (None when the invoice is unknown)."""

    def __init__(
        self, code: ReviewRefusal, message: str, current: AllowedActions | None = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.current = current


def _refuse(code: ReviewRefusal, current: AllowedActions | None) -> ReviewRefused:
    return ReviewRefused(code, MESSAGES[code], current)


# --- Allowed actions -----------------------------------------------------------------------

A = ReviewAction
_BY_STATUS: dict[InvoiceStatus, frozenset[ReviewAction]] = {
    InvoiceStatus.awaiting_human_approval: frozenset({A.approve, A.decline, A.correct}),
    InvoiceStatus.needs_review: frozenset({A.correct, A.submit_corrected}),
    InvoiceStatus.rejected: frozenset({A.correct, A.submit_corrected}),
    InvoiceStatus.failed: frozenset({A.submit_corrected}),
}
_SUPERSEDE_STATUSES = frozenset(
    {InvoiceStatus.rejected, InvoiceStatus.needs_review, InvoiceStatus.failed}
)
# A version whose latest business run is one of these blocks a corrected submission.
_HELD = (RunStatus.awaiting_human_approval, RunStatus.approved, RunStatus.paid_mock)
_BUSINESS = (*_HELD, RunStatus.rejected, RunStatus.needs_review)


def _paid(conn: sqlite3.Connection, invoice_id: str) -> bool:
    row = conn.execute("SELECT 1 FROM payments WHERE invoice_id = ?", (invoice_id,)).fetchone()
    return row is not None


def _has_source_text(conn: sqlite3.Connection, invoice: ledger.InvoiceRow) -> bool:
    if invoice.current_version is None:
        return False
    version = ledger.get_version(conn, invoice.invoice_id, invoice.current_version)
    return ledger.get_source(conn, version.source_id).extracted_text is not None


def _supersede_eligible(conn: sqlite3.Connection, invoice: ledger.InvoiceRow) -> bool:
    """Decision 22: no payment, a correctable status, and no version held by its latest
    business run (awaiting approval, approved or paid)."""
    if invoice.status not in _SUPERSEDE_STATUSES or _paid(conn, invoice.invoice_id):
        return False
    slots = ",".join("?" * len(_BUSINESS))
    rows = conn.execute(
        f"SELECT version_id, status FROM runs WHERE invoice_id = ? AND version_id IS NOT NULL "
        f"AND status IN ({slots}) ORDER BY started_at, rowid",
        (invoice.invoice_id, *(s.value for s in _BUSINESS)),
    ).fetchall()
    latest = {r["version_id"]: r["status"] for r in rows}  # the last row per version wins
    return not any(status in {s.value for s in _HELD} for status in latest.values())


def _allowed(conn: sqlite3.Connection, invoice_id: str) -> AllowedActions:
    """The actions the invoice allows now, and why the others are refused."""
    try:
        invoice = ledger.get_invoice(conn, invoice_id)
    except KeyError:
        raise _refuse(R.unknown_invoice, None) from None
    refused: dict[ReviewAction, ReviewRefusal] = {}
    if invoice.status is InvoiceStatus.paid_mock or _paid(conn, invoice_id):
        allowed: set[ReviewAction] = set()
        refused = {a: R.already_paid for a in ReviewAction}
    else:
        allowed = set(_BY_STATUS.get(invoice.status, ()))
        if A.correct in allowed and not _has_source_text(conn, invoice):
            allowed.discard(A.correct)
            refused[A.correct] = R.source_text_unavailable
        if A.submit_corrected in allowed and not _supersede_eligible(conn, invoice):
            allowed.discard(A.submit_corrected)
    return AllowedActions(
        invoice_id=invoice_id,
        status=invoice.status,
        current_version=invoice.current_version,
        allowed=[a for a in ReviewAction if a in allowed],
        refused={a: refused.get(a, R.action_not_allowed) for a in ReviewAction if a not in allowed},
    )


def allowed_actions(invoice_id: str, *, db_path: str | Path) -> AllowedActions:
    conn = connect(db_path)
    try:
        init_schema(conn)
        return _allowed(conn, invoice_id)
    finally:
        conn.close()


# --- Corrections ---------------------------------------------------------------------------

_LINE_FIELD = re.compile(r"^lines\[(\d+)\]\.(item|quantity|unit_price|line_total)$")
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_CURRENCY = re.compile(r"[A-Za-z]{3}")
_POSITIVE_INT = re.compile(r"\d+")
_CENT = Decimal("0.01")
_HEADER_ATTR = {"vendor": "vendor_name"}


def _is_money(field: str) -> bool:
    return field.startswith("stated.") or field.endswith((".unit_price", ".line_total"))


def _parse_value(field: str, raw: str) -> Any:
    """The typed value of a corrected field; ValueError when it does not parse."""
    if _is_money(field):
        return normalize.parse_amount(raw).quantize(_CENT)
    if field.endswith(".quantity"):
        if not _POSITIVE_INT.fullmatch(raw) or int(raw) <= 0:
            raise ValueError(raw)
        return Decimal(int(raw))
    if field in ("invoice_date", "due_date"):
        if not _ISO_DATE.fullmatch(raw):
            raise ValueError(raw)
        return date.fromisoformat(raw)
    if field == "currency":
        if not _CURRENCY.fullmatch(raw):
            raise ValueError(raw)
        return raw.upper()
    return raw  # vendor, invoice_number, item: stripped, non-empty text


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return f"{value:f}"
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _target(invoice: NormalizedInvoice, field: str) -> tuple[Any, str] | None:
    """The object holding `field` and its attribute name; None for a line index out of
    range."""
    if m := _LINE_FIELD.match(field):
        index = int(m[1])
        if index >= len(invoice.lines):
            return None
        return invoice.lines[index], m[2]
    if field.startswith("stated."):
        return invoice.stated, field.removeprefix("stated.")
    return invoice, _HEADER_ATTR.get(field, field)


def _currency_correctable(invoice: NormalizedInvoice, base_findings: list[dict]) -> bool:
    """Decision 11: only a missing, assumed or unparseable currency can be corrected."""
    if invoice.currency is None:
        return True
    unparseable = any(
        f["code"] == FindingCode.unparseable_value and f.get("field") == "currency"
        for f in base_findings
    )
    events = [e for e in invoice.normalization_events if e.field == "currency"]
    assumed = bool(events) and events[-1].provenance == "rule:dataset_usd_assumption"
    return unparseable or assumed


def _identity_kept(invoice: NormalizedInvoice, field: str, value: str) -> bool:
    """Decision 10: a vendor or invoice-number correction must keep the identity key."""
    if field == "vendor":
        return normalize.vendor_key(value) == invoice.vendor_key
    if field == "invoice_number":
        return (normalize.invoice_number_key(value) or None) == invoice.invoice_number_key
    return True


def _check_change(
    change: FieldChange,
    invoice: NormalizedInvoice,
    text: str | None,
    fmt: SourceFormat,
    base_findings: list[dict],
    current: AllowedActions,
) -> tuple[Any, str, str]:
    """The parsed value, the located source text and the canonical location, or
    ReviewRefused (in the brief's order)."""
    field = change.field
    if _target(invoice, field) is None or (
        field == "currency" and not _currency_correctable(invoice, base_findings)
    ):
        raise _refuse(R.field_not_correctable, current)
    try:
        value = _parse_value(field, change.new_value)
    except (ValueError, ArithmeticError):
        raise _refuse(R.invalid_value, current) from None
    if not _identity_kept(invoice, field, value):
        raise _refuse(R.identity_correction_deferred, current)
    if text is None:
        raise _refuse(R.source_text_unavailable, current)
    if not invoice.field_evidence and not any(line.evidence for line in invoice.lines):
        raise _refuse(R.evidence_unavailable, current)
    cited = change.evidence_location
    if not evidence.scheme_matches(cited, fmt):  # one address per value (Decision 8)
        raise _refuse(R.evidence_location_mismatch, current)
    location = evidence.canonical_location(cited, text)
    located = None if location is None else evidence.locate(text, location)
    if located is None or evidence.claimed_by_other(field, location, invoice, text):
        raise _refuse(R.evidence_location_mismatch, current)
    structured = evidence.is_structured(location)
    if not evidence.supports(field, _text(value), located, structured=structured):
        raise _refuse(R.correction_not_in_source, current)
    return value, located, location


def _base_run(conn: sqlite3.Connection, invoice_id: str) -> ledger.RunRow | None:
    """The latest business-outcome run of the invoice's current version."""
    try:
        invoice = ledger.get_invoice(conn, invoice_id)
    except KeyError:
        return None
    if invoice.current_version is None:
        return None
    version = ledger.get_version(conn, invoice_id, invoice.current_version)
    return ledger.latest_outcome_run(conn, version.version_id)


def submit_correction(
    request: CorrectionRequest,
    *,
    db_path: str | Path,
    events: logging.Logger | None = None,
    provider: ReasoningProvider | None = None,
    on_run_started: Callable[[str], None] | None = None,
) -> ProcessingResult:
    """Apply evidence-backed field corrections as a new version and revalidate it.

    All changes are checked before anything is written (all or nothing). The new run uses the
    base run's mode and evaluation date; a live invoice without credentials raises
    ConfigurationError before any row is written. `on_run_started(run_id)` is called once,
    after the new run is committed and before it executes."""
    conn = connect(db_path)
    try:
        init_schema(conn)
        seen = _base_run(conn, request.invoice_id)
        if provider is None and seen is not None:
            provider = get_provider(seen.mode)  # ConfigurationError comes first
        with write_transaction(conn):
            run_id = _record_correction(conn, request, seen)
    finally:
        conn.close()
    if on_run_started is not None:
        on_run_started(run_id)
    return service.run_existing_version(run_id, db_path=db_path, events=events, provider=provider)


def _record_correction(
    conn: sqlite3.Connection, request: CorrectionRequest, seen: ledger.RunRow | None
) -> str:
    invoice_id = request.invoice_id
    try:
        row = ledger.get_invoice(conn, invoice_id)
    except KeyError:
        raise _refuse(R.unknown_invoice, None) from None
    current = _allowed(conn, invoice_id)
    if _paid(conn, invoice_id):
        raise _refuse(R.already_paid, current)
    if request.expected_version != row.current_version:
        raise _refuse(R.stale_version, current)
    if A.correct not in current.allowed:
        raise _refuse(current.refused.get(A.correct, R.action_not_allowed), current)
    base = ledger.get_version(conn, invoice_id, row.current_version)
    base_run = ledger.latest_outcome_run(conn, base.version_id)
    if base_run is None:
        raise _refuse(R.action_not_allowed, current)
    if seen is None or seen.run_id != base_run.run_id:  # moved on since the provider was chosen
        raise _refuse(R.stale_version, current)
    source = ledger.get_source(conn, base.source_id)
    base_findings = ledger.list_findings(conn, base_run.run_id)

    text = source.extracted_text
    checked = [
        (change, *_check_change(change, base.invoice, text, source.format, base_findings, current))
        for change in request.changes
    ]

    invoice = base.invoice.model_copy(deep=True, update={"computed": None})
    applied: list[tuple[FieldChange, str | None, str, str]] = []
    for change, value, located, location in checked:
        holder, attr = _target(invoice, change.field)
        old = _text(getattr(holder, attr))
        setattr(holder, attr, value)
        if change.field == "vendor":
            invoice.vendor_key = normalize.vendor_key(value)
        new = _text(value)
        invoice.normalization_events.append(
            NormalizationEvent(
                field=change.field,
                raw_value=old,
                normalized_value=new,
                evidence=[
                    EvidenceRef(
                        source_id=base.source_id,
                        location=location,
                        snippet=located[:200],
                    )
                ],
                provenance="review:correction",
            )
        )
        applied.append((change, old, new, location))
    invoice = NormalizedInvoice.model_validate(invoice.model_dump())

    version_id, version = ledger.record_correction_version(
        conn, invoice_id, invoice, base.source_id, base.version
    )
    run_id = ledger.start_run(
        conn,
        base_run.mode,
        base.source_id,
        base_run.evaluation_date,
        trigger="correction",
        review_of=base_run.run_id,
    )
    ledger.attach_run(conn, run_id, invoice_id, version_id)
    now = datetime.now(UTC)
    for change, old, new, location in applied:
        ledger.record_correction(
            conn,
            Correction(
                invoice_id=invoice_id,
                base_version=base.version,
                field=change.field,
                old_value=old,
                new_value=new,
                evidence_location=location,
                reviewer=request.reviewer,
                reason=request.reason,
                created_at=now,
                resulting_version=version,
            ),
            run_id,
        )
    fields = [c.field for c in request.changes]
    # Findings name header totals without "stated." (e.g. "total"); drop both spellings.
    excluded = frozenset(fields) | {f.removeprefix("stated.") for f in fields}
    carried = ledger.carried_findings(conn, base_run.run_id, exclude_fields=excluded)
    ledger.record_findings(conn, run_id, version_id, carried)
    ledger.update_run_status(conn, run_id, RunStatus.extracted)

    def audit(event: str, payload: dict[str, Any]) -> None:
        ledger.append_audit_event(
            conn,
            run_id,
            "review",
            event,
            payload,
            invoice_id=invoice_id,
            version_id=version_id,
            actor=request.reviewer,
        )

    audit("review_run_created", {"trigger": "correction", "review_of": base_run.run_id})
    audit(
        "correction_applied",
        {"fields": fields, "base_version": base.version, "resulting_version": version},
    )
    decision_runs = conn.execute(
        "SELECT run_id FROM decisions WHERE version_id = ? ORDER BY decision_id",
        (base.version_id,),
    ).fetchall()
    reviews = conn.execute(
        "SELECT review_id FROM human_reviews WHERE invoice_id = ? AND version = ? "
        "ORDER BY review_id",
        (invoice_id, base.version),
    ).fetchall()
    audit(
        "approvals_invalidated",
        {
            "superseded_version": base.version,
            "decision_run_ids": [r["run_id"] for r in decision_runs],
            "human_review_ids": [r["review_id"] for r in reviews],
        },
    )
    ledger.set_invoice_status(conn, invoice_id, InvoiceStatus.processing)
    return run_id


# --- Approve / decline ---------------------------------------------------------------------


def approve(
    invoice_id: str,
    expected_version: int,
    reviewer: str,
    reason: str,
    *,
    db_path: str | Path,
    events: logging.Logger | None = None,
    on_run_started: Callable[[str], None] | None = None,
) -> ProcessingResult:
    """Approve the waiting `expected_version` and run the human-review run: it revalidates
    and reaches the gate with this approval, and pays only if the gate approves. A repeated
    approve of the paid version returns the paying run's result and writes nothing (and starts
    no run, so `on_run_started` is not called). `on_run_started(run_id)` is called once, after
    the review run is committed and before it executes."""
    return _review(
        HumanReviewAction.approve,
        invoice_id,
        expected_version,
        reviewer,
        reason,
        db_path=db_path,
        events=events,
        on_run_started=on_run_started,
    )


def decline(
    invoice_id: str,
    expected_version: int,
    reviewer: str,
    reason: str,
    *,
    db_path: str | Path,
    events: logging.Logger | None = None,
    on_run_started: Callable[[str], None] | None = None,
) -> ProcessingResult:
    """Decline the waiting `expected_version`: the human-review run rejects it at the gate
    (`R3_human_declined`, Decision 14)."""
    return _review(
        HumanReviewAction.decline,
        invoice_id,
        expected_version,
        reviewer,
        reason,
        db_path=db_path,
        events=events,
        on_run_started=on_run_started,
    )


def _review(
    action: HumanReviewAction,
    invoice_id: str,
    expected_version: int,
    reviewer: str,
    reason: str,
    *,
    db_path: str | Path,
    events: logging.Logger | None,
    on_run_started: Callable[[str], None] | None,
) -> ProcessingResult:
    # The contract validates reviewer and reason before the database is touched.
    review = HumanReview(
        invoice_id=invoice_id,
        version=expected_version,
        action=action,
        reviewer=reviewer,
        reason=reason,
        policy_version=policy.POLICY_VERSION,
        created_at=datetime.now(UTC),
    )
    conn = connect(db_path)
    try:
        init_schema(conn)
        with write_transaction(conn):
            outcome = _record_review(conn, review)
    finally:
        conn.close()
    if isinstance(outcome, ProcessingResult):
        return outcome
    run_id, mode = outcome
    if on_run_started is not None:
        on_run_started(run_id)
    return service.run_existing_version(
        run_id,
        db_path=db_path,
        events=events,
        provider=NoModelProvider(mode),
        approval="human",
    )


def _record_review(
    conn: sqlite3.Connection, review: HumanReview
) -> ProcessingResult | tuple[str, ExecutionMode]:
    """Check and record one approve/decline inside the caller's write transaction. Returns
    the new run (id, mode), or the paying run's result for a repeated approve."""
    invoice_id, action = review.invoice_id, review.action
    current = _allowed(conn, invoice_id)  # unknown_invoice when there is no such invoice
    paid = conn.execute(
        "SELECT run_id, version FROM payments WHERE invoice_id = ?", (invoice_id,)
    ).fetchone()
    if paid is not None:
        if action is HumanReviewAction.approve and review.version == paid["version"]:
            return _load_result(conn, paid["run_id"])  # Decision 20: no writes
        code = R.already_paid if action is HumanReviewAction.decline else R.stale_version
        raise _refuse(code, current)
    if review.version != current.current_version:
        raise _refuse(R.stale_version, current)
    if ReviewAction(action.value) not in current.allowed:
        raise _refuse(R.action_not_allowed, current)
    version = ledger.get_version(conn, invoice_id, review.version)
    waiting = ledger.latest_outcome_run(conn, version.version_id)
    if waiting is None or waiting.status is not RunStatus.awaiting_human_approval:
        raise _refuse(R.action_not_allowed, current)

    run_id = ledger.start_run(
        conn,
        waiting.mode,
        version.source_id,
        waiting.evaluation_date,
        trigger="human_review",
        review_of=waiting.run_id,
    )
    ledger.attach_run(conn, run_id, invoice_id, version.version_id)
    ledger.record_human_review(conn, review, run_id)
    ledger.record_findings(
        conn, run_id, version.version_id, ledger.carried_findings(conn, waiting.run_id)
    )
    ledger.update_run_status(conn, run_id, RunStatus.extracted)
    ledger.append_audit_event(
        conn,
        run_id,
        "review",
        "review_run_created",
        {"trigger": "human_review", "review_of": waiting.run_id, "action": action.value},
        invoice_id=invoice_id,
        version_id=version.version_id,
        actor=review.reviewer,
    )
    ledger.set_invoice_status(conn, invoice_id, InvoiceStatus.processing)
    return run_id, waiting.mode


def load_result(run_id: str, *, db_path: str | Path) -> ProcessingResult:
    """The recorded result of a finished run, rebuilt from the ledger."""
    conn = connect(db_path)
    try:
        init_schema(conn)
        return _load_result(conn, run_id)
    finally:
        conn.close()


def _load_result(conn: sqlite3.Connection, run_id: str) -> ProcessingResult:
    run = conn.execute(
        "SELECT r.run_id, r.invoice_id, r.status, r.mode, r.error_code, r.error_message, "
        "r.prior_run_id, r.evaluation_date, s.content_hash, v.version FROM runs r "
        "JOIN sources s ON s.source_id = r.source_id "
        "LEFT JOIN invoice_versions v ON v.version_id = r.version_id WHERE r.run_id = ?",
        (run_id,),
    ).fetchone()
    if run is None:
        raise KeyError(f"unknown run: {run_id}")
    findings = conn.execute(
        "SELECT payload_json FROM findings WHERE run_id = ? ORDER BY finding_id", (run_id,)
    ).fetchall()
    pay = conn.execute(
        "SELECT receipt_id, amount, currency, created_at FROM payments WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    receipt = None
    if pay is not None:
        receipt = MockReceipt(
            receipt_id=pay["receipt_id"],
            amount=Decimal(pay["amount"]),
            currency=pay["currency"],
            paid_at=datetime.fromisoformat(pay["created_at"]),
        )
    decision = ledger.get_decision(conn, run_id)
    return ProcessingResult(
        run_id=run_id,
        invoice_id=run["invoice_id"],
        version=run["version"],
        status=RunStatus(run["status"]),
        mode=run["mode"],
        findings=[ValidationFinding.model_validate_json(r["payload_json"]) for r in findings],
        decision=decision,
        receipt=receipt,
        errors=[run["error_code"]] if run["error_code"] else [],
        error_message=run["error_message"],
        source_hash=run["content_hash"],
        prior_run_id=run["prior_run_id"],
        evaluation_date=(
            date.fromisoformat(run["evaluation_date"]) if run["evaluation_date"] else None
        ),
        model_calls_used=decision.model_calls_used if decision is not None else 0,
    )
