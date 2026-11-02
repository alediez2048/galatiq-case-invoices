"""The single write path to the SQLite ledger.

Every write joins the caller's open transaction (or opens its own) via storage.atomic.
"""

import hashlib
import json
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from invoice_processing import storage, transitions
from invoice_processing.codes import (
    BUSINESS_OUTCOMES,
    TERMINAL_RUN_STATUSES,
    ExecutionMode,
    InvoiceStatus,
    RunStatus,
)
from invoice_processing.money import MINOR_UNITS, canonical_amount
from invoice_processing.schemas import (
    ApprovalDecision,
    HumanReview,
    MockReceipt,
    NormalizedInvoice,
    SourceDocument,
    ValidationFinding,
)

# Credential-like names only; a bare "key" must be the whole name so that business
# fields such as vendor_key or invoice_number_key are kept.
REDACTED_KEY = re.compile(
    r"^key$"
    r"|(api|access|private|auth)[_-]?(key|token)"  # also matches camelCase (apiKey, accessToken)
    r"|(^|[_-])(token|(secret|password|passwd|authorization|credential|cookie|bearer)s?)($|[_-])",
    re.I,
)
# Plural "tokens" (usage counts such as input_tokens) is deliberately kept.


def utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def record_source(conn: sqlite3.Connection, source: SourceDocument) -> tuple[str, bool]:
    with storage.atomic(conn):
        row = conn.execute(
            "SELECT source_id FROM sources WHERE content_hash = ?", (source.content_hash,)
        ).fetchone()
        if row is not None:
            return row["source_id"], True
        conn.execute(
            "INSERT INTO sources (source_id, content_hash, original_name, format, size_bytes, "
            "parser_version, extracted_text, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                source.source_id,
                source.content_hash,
                source.original_name,
                source.format.value,
                source.size_bytes,
                source.parser_version,
                source.extracted_text,
                utcnow(),
            ),
        )
        return source.source_id, False


def set_extracted_text(conn: sqlite3.Connection, source_id: str, text: str) -> None:
    with storage.atomic(conn):
        conn.execute(
            "UPDATE sources SET extracted_text = ? WHERE source_id = ? AND extracted_text IS NULL",
            (text, source_id),
        )


def upsert_invoice(
    conn: sqlite3.Connection,
    vendor_key: str | None,
    invoice_number_key: str | None,
    content_hash: str,
) -> str:
    if not (vendor_key and vendor_key.strip()) or not (
        invoice_number_key and invoice_number_key.strip()
    ):
        vendor_key, invoice_number_key = "pending", f"pending:{content_hash}"
    with storage.atomic(conn):
        row = conn.execute(
            "SELECT invoice_id FROM invoices WHERE vendor_key = ? AND invoice_number_key = ?",
            (vendor_key, invoice_number_key),
        ).fetchone()
        if row is not None:
            return row["invoice_id"]
        invoice_id = _new_id("inv")
        now = utcnow()
        conn.execute(
            "INSERT INTO invoices (invoice_id, vendor_key, invoice_number_key, current_version, "
            "status, created_at, updated_at) VALUES (?, ?, ?, NULL, ?, ?, ?)",
            (invoice_id, vendor_key, invoice_number_key, InvoiceStatus.processing.value, now, now),
        )
        return invoice_id


def _money(amount: Decimal | None, currency: str | None) -> str | None:
    if amount is None:
        return None
    if currency in MINOR_UNITS:
        return canonical_amount(amount, currency)
    return str(amount)


def semantic_hash(invoice: NormalizedInvoice) -> str:
    cur = invoice.currency
    lines = sorted(
        (
            [
                line.item,
                None if line.quantity is None else f"{line.quantity.normalize():f}",
                _money(line.unit_price, cur),
            ]
            for line in invoice.lines
        ),
        key=lambda row: json.dumps(row),
    )
    material = {
        "vendor_key": invoice.vendor_key,
        "invoice_number_key": invoice.invoice_number_key,
        "currency": cur,
        "due_date": invoice.due_date.isoformat() if invoice.due_date else None,
        "lines": lines,
        "total": _money(invoice.stated.total, cur),
    }
    blob = json.dumps(material, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


def record_version(
    conn: sqlite3.Connection,
    invoice_id: str,
    invoice: NormalizedInvoice,
    source_id: str,
    origin: str = "extracted",
) -> tuple[str, int]:
    digest = semantic_hash(invoice)
    with storage.atomic(conn):
        row = conn.execute(
            "SELECT version_id, version FROM invoice_versions "
            "WHERE invoice_id = ? AND semantic_hash = ?",
            (invoice_id, digest),
        ).fetchone()
        if row is not None:
            return row["version_id"], row["version"]
        latest = conn.execute(
            "SELECT COALESCE(MAX(version), 0) FROM invoice_versions WHERE invoice_id = ?",
            (invoice_id,),
        ).fetchone()[0]
        version = latest + 1
        version_id = _new_id("ver")
        now = utcnow()
        conn.execute(
            "INSERT INTO invoice_versions (version_id, invoice_id, version, parent_version, "
            "origin, source_id, semantic_hash, payload_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                version_id,
                invoice_id,
                version,
                latest or None,
                origin,
                source_id,
                digest,
                invoice.model_dump_json(),
                now,
            ),
        )
        conn.execute(
            "UPDATE invoices SET current_version = ?, updated_at = ? "
            "WHERE invoice_id = ? AND status != ?",
            (version, now, invoice_id, InvoiceStatus.paid_mock.value),
        )
        return version_id, version


def start_run(
    conn: sqlite3.Connection, mode: ExecutionMode, source_id: str, evaluation_date: date
) -> str:
    run_id = _new_id("run")
    with storage.atomic(conn):
        conn.execute(
            "INSERT INTO runs (run_id, source_id, mode, status, stage, evaluation_date, "
            "started_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                source_id,
                mode.value,
                RunStatus.received.value,
                RunStatus.received.value,
                evaluation_date.isoformat(),
                utcnow(),
            ),
        )
    return run_id


def attach_run(
    conn: sqlite3.Connection, run_id: str, invoice_id: str, version_id: str | None
) -> None:
    with storage.atomic(conn):
        conn.execute(
            "UPDATE runs SET invoice_id = ?, version_id = ? WHERE run_id = ?",
            (invoice_id, version_id, run_id),
        )


def get_run_status(conn: sqlite3.Connection, run_id: str) -> RunStatus:
    row = conn.execute("SELECT status FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        raise KeyError(f"unknown run: {run_id}")
    return RunStatus(row["status"])


def update_run_status(conn: sqlite3.Connection, run_id: str, status: RunStatus) -> None:
    with storage.atomic(conn):
        transitions.check(get_run_status(conn, run_id), status)
        conn.execute(
            "UPDATE runs SET status = ?, stage = ? WHERE run_id = ?",
            (status.value, status.value, run_id),
        )


def finish_run(
    conn: sqlite3.Connection,
    run_id: str,
    status: RunStatus,
    error_code: str | None = None,
    error_message: str | None = None,
    prior_run_id: str | None = None,
) -> None:
    if status not in TERMINAL_RUN_STATUSES:
        raise transitions.IllegalTransition(f"finish_run needs a terminal status, got {status}")
    with storage.atomic(conn):
        current = get_run_status(conn, run_id)
        finished = conn.execute(
            "SELECT finished_at FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()[0]
        if finished is not None:
            raise transitions.IllegalTransition(f"run {run_id} is already finished")
        if current != status:  # same status just finalizes (agent nodes already advanced it)
            transitions.check(current, status)
        conn.execute(
            "UPDATE runs SET status = ?, stage = ?, error_code = ?, error_message = ?, "
            "prior_run_id = ?, finished_at = ? WHERE run_id = ?",
            (status.value, status.value, error_code, error_message, prior_run_id, utcnow(), run_id),
        )


def set_invoice_status(conn: sqlite3.Connection, invoice_id: str, status: InvoiceStatus) -> None:
    with storage.atomic(conn):
        conn.execute(
            "UPDATE invoices SET status = ?, updated_at = ? WHERE invoice_id = ? AND status != ?",
            (status.value, utcnow(), invoice_id, InvoiceStatus.paid_mock.value),
        )


def record_findings(
    conn: sqlite3.Connection,
    run_id: str,
    version_id: str | None,
    findings: list[ValidationFinding],
) -> None:
    with storage.atomic(conn):
        conn.executemany(
            "INSERT INTO findings (run_id, version_id, code, severity, payload_json) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                (run_id, version_id, f.code.value, f.severity.value, f.model_dump_json())
                for f in findings
            ],
        )


def record_decision(
    conn: sqlite3.Connection,
    run_id: str,
    version_id: str | None,
    decision: ApprovalDecision,
) -> None:
    with storage.atomic(conn):
        conn.execute(
            "INSERT INTO decisions (run_id, version_id, payload_json, final_decision, "
            "policy_version, mode, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                version_id,
                decision.model_dump_json(),
                decision.final_decision.value,
                decision.policy_version,
                decision.mode.value,
                utcnow(),
            ),
        )


def get_human_review(
    conn: sqlite3.Connection, invoice_id: str, version: int, policy_version: str
) -> HumanReview | None:
    row = conn.execute(
        "SELECT invoice_id, version, action, reviewer, reason, policy_version "
        "FROM human_reviews WHERE invoice_id = ? AND version = ? AND policy_version = ? "
        "AND action IN ('approve', 'decline') ORDER BY review_id DESC LIMIT 1",
        (invoice_id, version, policy_version),
    ).fetchone()
    return None if row is None else HumanReview(**dict(row))


def redact(value: Any) -> Any:
    """Recursively drop credential-like keys from dicts (including dicts inside lists)."""
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items() if not REDACTED_KEY.search(str(k))}
    if isinstance(value, list | tuple):
        return [redact(v) for v in value]
    return value


def append_audit_event(
    conn: sqlite3.Connection,
    run_id: str | None,
    stage: str,
    event: str,
    payload: dict[str, Any],
    invoice_id: str | None = None,
    version_id: str | None = None,
) -> None:
    body = json.dumps(redact(payload), sort_keys=True, default=str)
    with storage.atomic(conn):
        conn.execute(
            "INSERT INTO audit_events (run_id, invoice_id, version_id, stage, event, "
            "payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, invoice_id, version_id, stage, event, body, utcnow()),
        )


def list_audit_events(conn: sqlite3.Connection, run_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT stage, event, payload_json, created_at FROM audit_events "
        "WHERE run_id = ? ORDER BY event_id",
        (run_id,),
    ).fetchall()
    return [
        {
            "stage": r["stage"],
            "event": r["event"],
            "payload": json.loads(r["payload_json"]) if r["payload_json"] else {},
            "created_at": r["created_at"],
        }
        for r in rows
    ]


@dataclass(frozen=True)
class PriorOutcome:
    run_id: str
    status: RunStatus
    invoice_id: str | None
    receipt: MockReceipt | None


def find_prior_outcome(conn: sqlite3.Connection, content_hash: str) -> PriorOutcome | None:
    outcomes = ",".join("?" * len(BUSINESS_OUTCOMES))
    row = conn.execute(
        "SELECT r.run_id, r.status, r.invoice_id FROM runs r "
        "JOIN sources s ON s.source_id = r.source_id "
        f"WHERE s.content_hash = ? AND r.retry_of IS NULL AND r.status IN ({outcomes}) "
        "ORDER BY r.started_at DESC, r.rowid DESC LIMIT 1",
        (content_hash, *sorted(s.value for s in BUSINESS_OUTCOMES)),
    ).fetchone()
    if row is None:
        return None
    receipt = None
    if row["invoice_id"] is not None:
        pay = conn.execute(
            "SELECT receipt_id, amount, currency, created_at FROM payments WHERE invoice_id = ?",
            (row["invoice_id"],),
        ).fetchone()
        if pay is not None:
            receipt = MockReceipt(
                receipt_id=pay["receipt_id"],
                amount=Decimal(pay["amount"]),
                currency=pay["currency"],
                paid_at=datetime.fromisoformat(pay["created_at"]),
            )
    return PriorOutcome(row["run_id"], RunStatus(row["status"]), row["invoice_id"], receipt)


def mark_interrupted_runs(conn: sqlite3.Connection, started_before: str) -> list[str]:
    terminal = ",".join("?" * len(TERMINAL_RUN_STATUSES))
    with storage.atomic(conn):
        ids = [
            r["run_id"]
            for r in conn.execute(
                f"SELECT run_id FROM runs WHERE status NOT IN ({terminal}) AND started_at < ?",
                (*[s.value for s in TERMINAL_RUN_STATUSES], started_before),
            )
        ]
        now = utcnow()
        for run_id in ids:
            conn.execute(
                "UPDATE runs SET status = ?, stage = ?, error_code = 'interrupted', "
                "finished_at = ? WHERE run_id = ?",
                (RunStatus.failed.value, RunStatus.failed.value, now, run_id),
            )
        return ids
