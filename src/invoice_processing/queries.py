"""Read models for the HTTP API: counts, lists, detail views, and rebuilt results.

Every function here is read-only. Results are rebuilt from the ledger tables, so what the API
returns is what was persisted, never transient UI state.
"""

from __future__ import annotations

import csv
import io
import json
import sqlite3
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict

from invoice_processing import ledger, storage
from invoice_processing.codes import (
    BUSINESS_OUTCOMES,
    TERMINAL_RUN_STATUSES,
    ExecutionMode,
    InvoiceStatus,
    ModelErrorCode,
    RunStatus,
    SourceFormat,
)
from invoice_processing.money import DecimalStr
from invoice_processing.schemas import (
    ApprovalDecision,
    EvidenceRef,
    LineItem,
    MockReceipt,
    NormalizationEvent,
    NormalizedInvoice,
    ProcessingResult,
    ValidationFinding,
)

PAGE_SIZE = 20
RECENT_LIMIT = 5


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NotFound(LookupError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------------------- overview


class OutcomeCounts(ApiModel):
    paid_mock: int = 0
    needs_review: int = 0
    awaiting_human_approval: int = 0
    rejected: int = 0
    failed: int = 0
    processing: int = 0


class CurrencyTotal(ApiModel):
    currency: str
    amount: DecimalStr
    paid_count: int


class InvoiceSummary(ApiModel):
    invoice_id: str
    vendor_name: str | None = None
    invoice_number: str | None = None
    total: DecimalStr | None = None
    currency: str | None = None
    due_date: str | None = None
    outcome: InvoiceStatus
    mode: ExecutionMode | None = None
    latest_run_id: str | None = None
    current_version: int | None = None
    updated_at: str


class Overview(ApiModel):
    documents: int
    unique_invoices: int
    runs: int
    duplicates: int
    outcomes: OutcomeCounts
    paid_totals: list[CurrencyTotal]
    recent_invoices: list[InvoiceSummary]


class InvoiceList(ApiModel):
    items: list[InvoiceSummary]
    page: int
    page_size: int
    total: int


_SUMMARY_SQL = """
SELECT * FROM (
  SELECT i.invoice_id AS invoice_id, i.status AS outcome, i.current_version AS current_version,
         i.updated_at AS updated_at, i.rowid AS ord,
         json_extract(v.payload_json, '$.vendor_name') AS vendor_name,
         json_extract(v.payload_json, '$.invoice_number') AS invoice_number,
         json_extract(v.payload_json, '$.stated.total') AS total,
         json_extract(v.payload_json, '$.currency') AS currency,
         json_extract(v.payload_json, '$.due_date') AS due_date,
         (SELECT r.run_id FROM runs r WHERE r.invoice_id = i.invoice_id
            ORDER BY r.started_at DESC, r.rowid DESC LIMIT 1) AS latest_run_id,
         (SELECT r.mode FROM runs r WHERE r.invoice_id = i.invoice_id
            ORDER BY r.started_at DESC, r.rowid DESC LIMIT 1) AS mode
  FROM invoices i
  LEFT JOIN invoice_versions v
    ON v.invoice_id = i.invoice_id AND v.version = i.current_version
)
"""


def _summary(row: sqlite3.Row) -> InvoiceSummary:
    total = row["total"]
    return InvoiceSummary(
        invoice_id=row["invoice_id"],
        vendor_name=row["vendor_name"],
        invoice_number=row["invoice_number"],
        total=None if total is None else Decimal(str(total)),
        currency=row["currency"],
        due_date=row["due_date"],
        outcome=InvoiceStatus(row["outcome"]),
        mode=None if row["mode"] is None else ExecutionMode(row["mode"]),
        latest_run_id=row["latest_run_id"],
        current_version=row["current_version"],
        updated_at=row["updated_at"],
    )


def _like(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def list_invoices(
    conn: sqlite3.Connection,
    status: InvoiceStatus | None = None,
    mode: ExecutionMode | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = PAGE_SIZE,
) -> InvoiceList:
    where: list[str] = []
    args: list[Any] = []
    if status is not None:
        where.append("outcome = ?")
        args.append(status.value)
    if mode is not None:
        where.append("mode = ?")
        args.append(mode.value)
    if q and q.strip():
        pattern = _like(q.strip())
        where.append(
            "(vendor_name LIKE ? ESCAPE '\\' OR invoice_number LIKE ? ESCAPE '\\' "
            "OR invoice_id LIKE ? ESCAPE '\\')"
        )
        args.extend([pattern] * 3)
    clause = f" WHERE {' AND '.join(where)}" if where else ""
    total = conn.execute(f"SELECT COUNT(*) FROM ({_SUMMARY_SQL}){clause}", args).fetchone()[0]
    rows = conn.execute(
        f"{_SUMMARY_SQL}{clause} ORDER BY updated_at DESC, ord DESC LIMIT ? OFFSET ?",
        (*args, page_size, (page - 1) * page_size),
    ).fetchall()
    return InvoiceList(
        items=[_summary(r) for r in rows], page=page, page_size=page_size, total=total
    )


def overview(conn: sqlite3.Connection) -> Overview:
    count = {
        "documents": "SELECT COUNT(*) FROM sources",
        "unique_invoices": "SELECT COUNT(*) FROM invoices",
        "runs": "SELECT COUNT(*) FROM runs",
        "duplicates": "SELECT COUNT(*) FROM runs WHERE status = 'duplicate'",
    }
    totals = {key: conn.execute(sql).fetchone()[0] for key, sql in count.items()}
    outcomes = OutcomeCounts()
    for row in conn.execute("SELECT status, COUNT(*) AS n FROM invoices GROUP BY status"):
        if row["status"] in OutcomeCounts.model_fields:
            setattr(outcomes, row["status"], row["n"])

    paid: dict[str, tuple[Decimal, int]] = {}
    # Every currency that appears on a current invoice is listed, so an unpaid EUR shows as 0.00.
    for row in conn.execute(
        "SELECT DISTINCT json_extract(v.payload_json, '$.currency') AS currency FROM invoices i "
        "JOIN invoice_versions v ON v.invoice_id = i.invoice_id AND v.version = i.current_version"
    ):
        if row["currency"]:
            paid[row["currency"]] = (Decimal("0.00"), 0)
    for row in conn.execute("SELECT amount, currency FROM payments WHERE status != 'failed'"):
        amount, n = paid.get(row["currency"], (Decimal("0.00"), 0))
        paid[row["currency"]] = (amount + Decimal(row["amount"]), n + 1)
    paid_totals = [
        CurrencyTotal(currency=cur, amount=amount, paid_count=n)
        for cur, (amount, n) in sorted(paid.items())
    ]
    recent = list_invoices(conn, page=1, page_size=RECENT_LIMIT).items
    return Overview(**totals, outcomes=outcomes, paid_totals=paid_totals, recent_invoices=recent)


# ---------------------------------------------------------------------------- results


def _receipt_where(conn: sqlite3.Connection, column: str, value: str) -> MockReceipt | None:
    pay = conn.execute(
        "SELECT receipt_id, amount, currency, created_at FROM payments "
        f"WHERE {column} = ? ORDER BY created_at DESC LIMIT 1",
        (value,),
    ).fetchone()
    if pay is None:
        return None
    return MockReceipt(
        receipt_id=pay["receipt_id"],
        amount=Decimal(pay["amount"]),
        currency=pay["currency"],
        paid_at=datetime.fromisoformat(pay["created_at"]),
    )


def _findings(conn: sqlite3.Connection, run_id: str) -> list[ValidationFinding]:
    rows = conn.execute(
        "SELECT payload_json FROM findings WHERE run_id = ? ORDER BY finding_id", (run_id,)
    )
    return [ValidationFinding.model_validate_json(r["payload_json"]) for r in rows]


def _decision(conn: sqlite3.Connection, run_id: str) -> ApprovalDecision | None:
    row = conn.execute("SELECT payload_json FROM decisions WHERE run_id = ?", (run_id,)).fetchone()
    return None if row is None else ApprovalDecision.model_validate_json(row["payload_json"])


def _run_row(conn: sqlite3.Connection, run_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        raise NotFound("run_not_found", f"No run with id {run_id}.")
    return row


# Mirrors service._result / service.RETRYABLE_ERROR_CODES (asserted equal in tests): a model
# failure can be retried or run offline; a crash or unexpected error only retried.
_RECOVERY_ACTIONS = ["retry", "run offline as a separate simulation"]
_MODEL_ERROR_CODES = frozenset(c.value for c in ModelErrorCode)


def next_actions_for(error_code: str | None) -> list[str]:
    if error_code in _MODEL_ERROR_CODES:
        return list(_RECOVERY_ACTIONS)
    if error_code in ("unexpected_error", "interrupted"):
        return ["retry"]
    return []


def build_result(conn: sqlite3.Connection, run_id: str) -> ProcessingResult:
    """The ProcessingResult of a finished run, rebuilt from persisted rows.

    Stage timings are not persisted, so ``timings_ms`` is empty here.
    """
    run = _run_row(conn, run_id)
    status = RunStatus(run["status"])
    duplicate = status is RunStatus.duplicate
    source = conn.execute(
        "SELECT content_hash FROM sources WHERE source_id = ?", (run["source_id"],)
    ).fetchone()
    receipt_run = run["prior_run_id"] if duplicate and run["prior_run_id"] else run_id
    next_actions = next_actions_for(run["error_code"]) if status is RunStatus.failed else []
    model_calls = conn.execute(
        "SELECT COUNT(*) FROM audit_events WHERE run_id = ? AND event = 'model_call'", (run_id,)
    ).fetchone()[0]
    version = conn.execute(
        "SELECT version FROM invoice_versions WHERE version_id = ?", (run["version_id"],)
    ).fetchone()
    return ProcessingResult(
        run_id=run_id,
        invoice_id=run["invoice_id"],
        version=None if version is None else version["version"],
        status=status,
        mode=ExecutionMode(run["mode"]),
        findings=[] if duplicate else _findings(conn, run_id),
        decision=None if duplicate else _decision(conn, run_id),
        receipt=_receipt_where(conn, "run_id", receipt_run),
        prior_run_id=run["prior_run_id"],
        errors=[run["error_code"]] if run["error_code"] else [],
        error_message=run["error_message"],
        source_hash=source["content_hash"] if source else None,
        evaluation_date=run["evaluation_date"],
        model_calls_used=model_calls,
        recoverable=bool(next_actions),
        next_actions=next_actions,
    )


class AuditEventView(ApiModel):
    stage: str
    event: str
    payload: dict[str, Any]
    created_at: str


class RunSourceView(ApiModel):
    source_id: str
    original_name: str
    format: SourceFormat


class RunView(ApiModel):
    run_id: str
    status: RunStatus
    stage: str | None
    mode: ExecutionMode
    terminal: bool
    invoice_id: str | None = None
    source: RunSourceView
    started_at: str
    finished_at: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    prior_run_id: str | None = None  # set on a duplicate run: the run that holds the outcome
    retry_of: str | None = None  # set on an explicit retry (P3-08): the failed run it retries
    # set when the same bytes ran in the other mode (P3-08): the latest such run
    mode_switch_of: str | None = None
    events: list[AuditEventView]
    result: ProcessingResult | None = None


def _events(conn: sqlite3.Connection, run_id: str) -> list[AuditEventView]:
    return [AuditEventView(**e) for e in ledger.list_audit_events(conn, run_id)]


def _is_terminal(run: sqlite3.Row) -> bool:
    return RunStatus(run["status"]) in TERMINAL_RUN_STATUSES and run["finished_at"] is not None


def get_run(conn: sqlite3.Connection, run_id: str) -> RunView:
    run = _run_row(conn, run_id)
    status = RunStatus(run["status"])
    terminal = _is_terminal(run)
    src = conn.execute(
        "SELECT source_id, original_name, format FROM sources WHERE source_id = ?",
        (run["source_id"],),
    ).fetchone()
    return RunView(
        run_id=run_id,
        status=status,
        stage=run["stage"],
        mode=ExecutionMode(run["mode"]),
        terminal=terminal,
        invoice_id=run["invoice_id"],
        source=RunSourceView(**dict(src)),
        started_at=run["started_at"],
        finished_at=run["finished_at"],
        error_code=run["error_code"],
        error_message=run["error_message"],
        prior_run_id=run["prior_run_id"],
        retry_of=run["retry_of"],
        mode_switch_of=run["mode_switch_of"],
        events=_events(conn, run_id),
        result=build_result(conn, run_id) if terminal else None,
    )


# ---------------------------------------------------------------------------- invoice detail


class StockLine(ApiModel):
    item: str | None
    quantity: DecimalStr | None
    unit_price: DecimalStr | None
    line_total: DecimalStr | None
    requested_total: DecimalStr | None  # all lines of this item on the invoice, summed
    available: int | None  # None when the item is not in inventory
    evidence: list[EvidenceRef]


class VersionView(ApiModel):
    version: int
    parent_version: int | None
    origin: str
    source_id: str
    original_name: str | None = None
    revision: str | None = None
    total: DecimalStr | None = None
    currency: str | None = None
    lines: list[LineItem] = []
    receipt: MockReceipt | None = None  # mock payment made against this version, if any
    created_at: str


class CorrectionView(ApiModel):
    from_version: int
    to_version: int
    field: str
    old_value: str | None
    new_value: str
    evidence_location: str
    reviewer: str
    reason: str
    created_at: str


class HumanReviewView(ApiModel):
    version: int
    action: str
    reviewer: str
    reason: str
    policy_version: str
    created_at: str


class RunSummary(ApiModel):
    run_id: str
    status: RunStatus
    mode: ExecutionMode
    source_id: str
    original_name: str | None = None
    prior_run_id: str | None
    retry_of: str | None = None
    evaluation_date: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    provider: str | None = None  # from the run's decision, when one was recorded
    model: str | None = None
    started_at: str
    finished_at: str | None
    events: list[AuditEventView] = []


class SourceSummary(ApiModel):
    source_id: str
    original_name: str
    format: SourceFormat
    size_bytes: int
    page_count: int | None = None


class InvoiceDetail(ApiModel):
    invoice_id: str
    outcome: InvoiceStatus
    current_version: int | None
    vendor_name: str | None
    invoice_number: str | None
    mode: ExecutionMode | None
    latest_run_id: str | None
    decision_run_id: str | None
    source_id: str | None
    source: SourceSummary | None = None  # the source of the current version
    evaluation_date: str | None = None  # of the latest run; drives the "Overdue" warning
    latest_result: ProcessingResult | None = None  # the latest run's result once terminal
    invoice: NormalizedInvoice | None
    normalization_events: list[NormalizationEvent]
    findings: list[ValidationFinding]
    line_items: list[StockLine]
    decision: ApprovalDecision | None
    receipt: MockReceipt | None
    versions: list[VersionView]
    corrections: list[CorrectionView]
    human_reviews: list[HumanReviewView]
    runs: list[RunSummary]
    # "retry" when the latest run is a recoverable failure (P3-08); review actions are
    # TODO(P5-04), populated by the review service once it exists.
    allowed_actions: list[str]


def _rows(conn: sqlite3.Connection, sql: str, *args: Any) -> list[sqlite3.Row]:
    return conn.execute(sql, args).fetchall()


def _decision_run(runs: list[sqlite3.Row]) -> sqlite3.Row | None:
    """The run that holds the invoice's findings and decision: latest business outcome,
    otherwise the latest non-duplicate run."""
    ordered = sorted(runs, key=lambda r: (r["started_at"], r["rowid"]), reverse=True)
    for run in ordered:
        if RunStatus(run["status"]) in BUSINESS_OUTCOMES:
            return run
    for run in ordered:
        if RunStatus(run["status"]) is not RunStatus.duplicate:
            return run
    return None


def latest_business_run_id(conn: sqlite3.Connection, invoice_id: str) -> str | None:
    runs = _rows(conn, "SELECT rowid, * FROM runs WHERE invoice_id = ?", invoice_id)
    run = _decision_run(runs)
    return None if run is None else run["run_id"]


def get_invoice(conn: sqlite3.Connection, invoice_id: str) -> InvoiceDetail:
    inv = conn.execute("SELECT * FROM invoices WHERE invoice_id = ?", (invoice_id,)).fetchone()
    if inv is None:
        raise NotFound("invoice_not_found", f"No invoice with id {invoice_id}.")
    runs = _rows(conn, "SELECT rowid, * FROM runs WHERE invoice_id = ?", invoice_id)
    latest = max(runs, key=lambda r: (r["started_at"], r["rowid"]), default=None)
    decision_run = _decision_run(runs)

    version_row = conn.execute(
        "SELECT payload_json, source_id FROM invoice_versions WHERE invoice_id = ? AND version = ?",
        (invoice_id, inv["current_version"]),
    ).fetchone()
    invoice = (
        None
        if version_row is None
        else NormalizedInvoice.model_validate_json(version_row["payload_json"])
    )

    lines: list[StockLine] = []
    if invoice is not None:
        names = [ln.item for ln in invoice.lines if ln.item]
        stock = storage.get_stock(conn, names)
        requested: dict[str, Decimal] = {}
        for ln in invoice.lines:
            if ln.item and ln.quantity is not None:
                requested[ln.item] = requested.get(ln.item, Decimal(0)) + ln.quantity
        for ln in invoice.lines:
            lines.append(_stock_line(ln, requested, stock))

    terminal = latest is not None and _is_terminal(latest)
    latest_result = build_result(conn, latest["run_id"]) if terminal else None
    allowed = (
        ["retry"]
        if latest_result is not None
        and latest_result.status is RunStatus.failed
        and "retry" in latest_result.next_actions
        else []
    )
    return InvoiceDetail(
        invoice_id=invoice_id,
        outcome=InvoiceStatus(inv["status"]),
        current_version=inv["current_version"],
        vendor_name=invoice.vendor_name if invoice else None,
        invoice_number=invoice.invoice_number if invoice else None,
        mode=None if latest is None else ExecutionMode(latest["mode"]),
        latest_run_id=None if latest is None else latest["run_id"],
        decision_run_id=None if decision_run is None else decision_run["run_id"],
        source_id=None if version_row is None else version_row["source_id"],
        source=None if version_row is None else _source_summary(conn, version_row["source_id"]),
        evaluation_date=None if latest is None else latest["evaluation_date"],
        latest_result=latest_result,
        invoice=invoice,
        normalization_events=[] if invoice is None else invoice.normalization_events,
        findings=[] if decision_run is None else _findings(conn, decision_run["run_id"]),
        line_items=lines,
        decision=None if decision_run is None else _decision(conn, decision_run["run_id"]),
        receipt=_receipt_where(conn, "invoice_id", invoice_id),
        versions=_versions(conn, invoice_id),
        corrections=[
            CorrectionView(**{k: r[k] for k in CorrectionView.model_fields})
            for r in _rows(
                conn,
                "SELECT * FROM corrections WHERE invoice_id = ? ORDER BY correction_id",
                invoice_id,
            )
        ],
        human_reviews=[
            HumanReviewView(**{k: r[k] for k in HumanReviewView.model_fields})
            for r in _rows(
                conn,
                "SELECT * FROM human_reviews WHERE invoice_id = ? ORDER BY review_id",
                invoice_id,
            )
        ],
        runs=[
            _run_summary(conn, r) for r in sorted(runs, key=lambda r: (r["started_at"], r["rowid"]))
        ],
        allowed_actions=allowed,
    )


def _source_summary(conn: sqlite3.Connection, source_id: str) -> SourceSummary | None:
    row = conn.execute(
        "SELECT source_id, original_name, format, size_bytes, extracted_text FROM sources "
        "WHERE source_id = ?",
        (source_id,),
    ).fetchone()
    if row is None:
        return None
    pages = _pdf_pages(row["extracted_text"]) if row["format"] == SourceFormat.pdf.value else None
    return SourceSummary(
        source_id=row["source_id"],
        original_name=row["original_name"],
        format=SourceFormat(row["format"]),
        size_bytes=row["size_bytes"],
        page_count=None if pages is None else len(pages),
    )


def _versions(conn: sqlite3.Connection, invoice_id: str) -> list[VersionView]:
    rows = _rows(
        conn,
        "SELECT v.version, v.parent_version, v.origin, v.source_id, v.payload_json, v.created_at, "
        "s.original_name FROM invoice_versions v LEFT JOIN sources s ON s.source_id = v.source_id "
        "WHERE v.invoice_id = ? ORDER BY v.version",
        invoice_id,
    )
    paid = {
        r["version"]: MockReceipt(
            receipt_id=r["receipt_id"],
            amount=Decimal(r["amount"]),
            currency=r["currency"],
            paid_at=datetime.fromisoformat(r["created_at"]),
        )
        for r in _rows(
            conn,
            "SELECT version, receipt_id, amount, currency, created_at FROM payments "
            "WHERE invoice_id = ? AND status != 'failed'",
            invoice_id,
        )
    }
    out: list[VersionView] = []
    for r in rows:
        payload = NormalizedInvoice.model_validate_json(r["payload_json"])
        out.append(
            VersionView(
                version=r["version"],
                parent_version=r["parent_version"],
                origin=r["origin"],
                source_id=r["source_id"],
                original_name=r["original_name"],
                revision=payload.revision,
                total=payload.stated.total,
                currency=payload.currency,
                lines=payload.lines,
                receipt=paid.get(r["version"]),
                created_at=r["created_at"],
            )
        )
    return out


def _run_summary(conn: sqlite3.Connection, run: sqlite3.Row) -> RunSummary:
    name = conn.execute(
        "SELECT original_name FROM sources WHERE source_id = ?", (run["source_id"],)
    ).fetchone()
    decision = _decision(conn, run["run_id"])
    return RunSummary(
        run_id=run["run_id"],
        status=RunStatus(run["status"]),
        mode=ExecutionMode(run["mode"]),
        source_id=run["source_id"],
        original_name=None if name is None else name["original_name"],
        prior_run_id=run["prior_run_id"],
        retry_of=run["retry_of"],
        evaluation_date=run["evaluation_date"],
        error_code=run["error_code"],
        error_message=run["error_message"],
        provider=None if decision is None else decision.provider,
        model=None if decision is None else decision.model,
        started_at=run["started_at"],
        finished_at=run["finished_at"],
        events=_events(conn, run["run_id"]),
    )


def _stock_line(
    ln: LineItem, requested: dict[str, Decimal], stock: dict[str, int | None]
) -> StockLine:
    return StockLine(
        item=ln.item,
        quantity=ln.quantity,
        unit_price=ln.unit_price,
        line_total=ln.line_total,
        requested_total=requested.get(ln.item) if ln.item else None,
        available=stock.get(ln.item) if ln.item else None,
        evidence=ln.evidence,
    )


# ---------------------------------------------------------------------------- sources


class SourceLine(ApiModel):
    anchor: str  # matches EvidenceRef.location for line-addressed formats ("line:9")
    text: str


class SourceRow(ApiModel):
    anchor: str  # "row:3"
    cells: list[str]


class SourceContent(ApiModel):
    source_id: str
    content_hash: str
    original_name: str
    format: SourceFormat
    size_bytes: int
    page_count: int | None = None
    lines: list[SourceLine]
    rows: list[SourceRow] | None = None
    original_url: str | None = None  # set when the original bytes are available for preview
    preview_limitation: str | None = None  # why the readable view may differ from the original


class SourceRecord(ApiModel):
    source_id: str
    content_hash: str
    original_name: str
    format: SourceFormat
    size_bytes: int
    extracted_text: str | None = None


def get_source_record(conn: sqlite3.Connection, source_id: str) -> SourceRecord:
    row = conn.execute(
        "SELECT source_id, content_hash, original_name, format, size_bytes, extracted_text "
        "FROM sources WHERE source_id = ?",
        (source_id,),
    ).fetchone()
    if row is None:
        raise NotFound("source_not_found", f"No source with id {source_id}.")
    return SourceRecord(**dict(row))


PDF_PREVIEW_LIMITATION = (
    "Text below is what the parser extracted from the PDF; layout, images and handwriting "
    "are not shown."
)
MISSING_ORIGINAL_LIMITATION = (
    "The original file is no longer available; showing the text stored at intake."
)


def _pdf_pages(extracted_text: str | None) -> list[str]:
    # Same page separator the PDF parser joins with, so anchors equal evidence locations.
    return extracted_text.split("\n\f\n") if extracted_text else []


def source_content(record: SourceRecord, raw_text: str | None, has_original: bool) -> SourceContent:
    """Readable lines (and CSV rows) for a source. PDFs use the extracted text, one anchor per
    page and line; other formats use the original text when it is still on disk."""
    page_count: int | None = None
    lines: list[SourceLine] = []
    rows: list[SourceRow] | None = None
    if record.format is SourceFormat.pdf:
        pages = _pdf_pages(record.extracted_text)
        page_count = len(pages)
        for p, page in enumerate(pages, start=1):
            for n, text in enumerate(page.splitlines(), start=1):
                lines.append(SourceLine(anchor=f"page:{p},line:{n}", text=text))
    else:
        text = raw_text if raw_text is not None else (record.extracted_text or "")
        lines = [SourceLine(anchor=f"line:{n}", text=t) for n, t in enumerate(text.splitlines(), 1)]
        if record.format is SourceFormat.csv:
            try:
                parsed = list(csv.reader(io.StringIO(text)))
            except csv.Error:
                parsed = []
            rows = [SourceRow(anchor=f"row:{n}", cells=r) for n, r in enumerate(parsed, 1)]
    return SourceContent(
        source_id=record.source_id,
        content_hash=record.content_hash,
        original_name=record.original_name,
        format=record.format,
        size_bytes=record.size_bytes,
        page_count=page_count,
        lines=lines,
        rows=rows,
        original_url=f"/api/sources/{record.source_id}/original" if has_original else None,
        preview_limitation=(
            PDF_PREVIEW_LIMITATION
            if record.format is SourceFormat.pdf
            else None
            if has_original
            else MISSING_ORIGINAL_LIMITATION
        ),
    )


def dump_json(model: BaseModel) -> str:
    return json.dumps(json.loads(model.model_dump_json()), indent=2) + "\n"
