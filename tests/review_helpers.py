"""Shared builders for the Phase 4 review tests (corrections, approvals, supersede)."""

from datetime import date
from pathlib import Path

from invoice_processing import review, seed, storage
from invoice_processing.codes import ExecutionMode
from invoice_processing.reasoning import ReasoningProvider
from invoice_processing.schemas import CorrectionRequest, FieldChange, ProcessingResult
from invoice_processing.service import process_invoice

ROOT = Path(__file__).resolve().parent.parent
INVOICES = ROOT / "data" / "invoices"
REVIEW = ROOT / "tests" / "fixtures" / "review"
EVAL = date(2026, 1, 31)


def seeded_db(tmp_path: Path) -> Path:
    db = tmp_path / "review.db"
    conn = storage.connect(db)
    try:
        storage.init_schema(conn)
        seed.seed_inventory(conn)
    finally:
        conn.close()
    return db


def process(
    path: Path,
    db: Path,
    mode: ExecutionMode = ExecutionMode.offline,
    provider: ReasoningProvider | None = None,
) -> ProcessingResult:
    return process_invoice(path, mode, db, EVAL, provider=provider)


def count(db: Path, sql: str, *args) -> int:
    conn = storage.connect(db)
    try:
        return conn.execute(sql, args).fetchone()[0]
    finally:
        conn.close()


def payment_count(db: Path, invoice_id: str) -> int:
    return count(db, "SELECT COUNT(*) FROM payments WHERE invoice_id = ?", invoice_id)


def change(field: str, value: str, loc: str) -> FieldChange:
    return FieldChange(field=field, new_value=value, evidence_location=loc)


def correct(
    db: Path,
    result: ProcessingResult,
    *changes: FieldChange,
    reason: str = "Misread total",
    reviewer: str = "Ana",
    provider: ReasoningProvider | None = None,
    expected_version: int | None = None,
) -> ProcessingResult:
    request = CorrectionRequest(
        invoice_id=result.invoice_id,
        expected_version=result.version if expected_version is None else expected_version,
        changes=list(changes),
        reason=reason,
        reviewer=reviewer,
    )
    return review.submit_correction(request, db_path=db, provider=provider)
