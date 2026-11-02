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
from typing import Any, Literal

from invoice_processing import storage, transitions
from invoice_processing.codes import (
    BUSINESS_OUTCOMES,
    TERMINAL_RUN_STATUSES,
    ExecutionMode,
    InvoiceStatus,
    RunStatus,
    Severity,
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
    r"|(?-i:[a-z](?:Secret|Token|Password|Passwd|Credential|Cookie|Bearer)(?:$|[A-Z]))"  # camelCase
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
    conn: sqlite3.Connection,
    mode: ExecutionMode,
    source_id: str,
    evaluation_date: date,
    retry_of: str | None = None,
    mode_switch_of: str | None = None,
) -> str:
    run_id = _new_id("run")
    with storage.atomic(conn):
        conn.execute(
            "INSERT INTO runs (run_id, source_id, mode, status, stage, retry_of, "
            "mode_switch_of, evaluation_date, started_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                source_id,
                mode.value,
                RunStatus.received.value,
                RunStatus.received.value,
                retry_of,
                mode_switch_of,
                evaluation_date.isoformat(),
                utcnow(),
            ),
        )
    return run_id


def latest_run_in_other_mode(
    conn: sqlite3.Connection, source_id: str, mode: ExecutionMode
) -> str | None:
    """The latest run of this source in a mode other than `mode`, if any (any status)."""
    row = conn.execute(
        "SELECT run_id FROM runs WHERE source_id = ? AND mode != ? "
        "ORDER BY started_at DESC, rowid DESC LIMIT 1",
        (source_id, mode.value),
    ).fetchone()
    return None if row is None else row["run_id"]


@dataclass(frozen=True)
class RunSummary:
    run_id: str
    mode: ExecutionMode
    status: RunStatus
    error_code: str | None
    content_hash: str


def get_run(conn: sqlite3.Connection, run_id: str) -> RunSummary | None:
    row = conn.execute(
        "SELECT r.run_id, r.mode, r.status, r.error_code, s.content_hash FROM runs r "
        "JOIN sources s ON s.source_id = r.source_id WHERE r.run_id = ?",
        (run_id,),
    ).fetchone()
    if row is None:
        return None
    return RunSummary(
        row["run_id"],
        ExecutionMode(row["mode"]),
        RunStatus(row["status"]),
        row["error_code"],
        row["content_hash"],
    )


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


def list_findings(
    conn: sqlite3.Connection, run_id: str, severity: Severity | None = None
) -> list[dict[str, Any]]:
    """Recorded findings of one run (read-only), optionally of one severity."""
    sql = "SELECT payload_json FROM findings WHERE run_id = ?"
    args: list[Any] = [run_id]
    if severity is not None:
        sql += " AND severity = ?"
        args.append(severity.value)
    rows = conn.execute(sql + " ORDER BY finding_id", args).fetchall()
    return [json.loads(r["payload_json"]) for r in rows]


def invoice_history(
    conn: sqlite3.Connection, invoice_id: str, exclude_run_id: str | None = None
) -> dict[str, Any]:
    """Versions, earlier run outcomes and payment status of one invoice identity (read-only)."""
    versions = conn.execute(
        "SELECT version, origin, created_at FROM invoice_versions "
        "WHERE invoice_id = ? ORDER BY version",
        (invoice_id,),
    ).fetchall()
    runs = conn.execute(
        "SELECT r.run_id, r.status, r.mode, v.version, r.started_at FROM runs r "
        "LEFT JOIN invoice_versions v ON v.version_id = r.version_id "
        "WHERE r.invoice_id = ? AND r.run_id != ? ORDER BY r.started_at, r.rowid",
        (invoice_id, exclude_run_id or ""),
    ).fetchall()
    pay = conn.execute(
        "SELECT version, receipt_id, status, amount, currency FROM payments WHERE invoice_id = ?",
        (invoice_id,),
    ).fetchone()
    return {
        "versions": [dict(v) for v in versions],
        "runs": [dict(r) for r in runs],
        "payment": None if pay is None else dict(pay),
    }


@dataclass(frozen=True)
class PriorOutcome:
    run_id: str
    status: RunStatus
    invoice_id: str | None
    receipt: MockReceipt | None


_OUTCOME_VALUES = tuple(sorted(s.value for s in BUSINESS_OUTCOMES))
_OUTCOME_SLOTS = ",".join("?" * len(_OUTCOME_VALUES))


def _receipt(conn: sqlite3.Connection, run_id: str) -> MockReceipt | None:
    """The receipt this run paid, if any; another run's payment is never reported as its own."""
    pay = conn.execute(
        "SELECT receipt_id, amount, currency, created_at FROM payments WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if pay is None:
        return None
    return MockReceipt(
        receipt_id=pay["receipt_id"],
        amount=Decimal(pay["amount"]),
        currency=pay["currency"],
        paid_at=datetime.fromisoformat(pay["created_at"]),
    )


def _prior(conn: sqlite3.Connection, row: sqlite3.Row) -> PriorOutcome:
    run_id = row["run_id"]
    return PriorOutcome(run_id, RunStatus(row["status"]), row["invoice_id"], _receipt(conn, run_id))


def find_prior_outcome(conn: sqlite3.Connection, content_hash: str) -> PriorOutcome | None:
    row = conn.execute(
        "SELECT r.run_id, r.status, r.invoice_id FROM runs r "
        "JOIN sources s ON s.source_id = r.source_id "
        f"WHERE s.content_hash = ? AND r.retry_of IS NULL AND r.status IN ({_OUTCOME_SLOTS}) "
        "ORDER BY r.started_at DESC, r.rowid DESC LIMIT 1",
        (content_hash, *_OUTCOME_VALUES),
    ).fetchone()
    return None if row is None else _prior(conn, row)


IdentityKind = Literal["new", "duplicate", "revision_after_payment", "version_conflict"]


@dataclass(frozen=True)
class IdentityCheck:
    kind: IdentityKind
    prior: PriorOutcome | None


def _retry_chain(conn: sqlite3.Connection, run_id: str) -> list[str]:
    """Every run linked to this one by retry_of: its ancestors back to the original run and
    every retry descending from that original (siblings included); this run excluded."""
    rows = conn.execute(
        "WITH RECURSIVE up(run_id, retry_of) AS ("
        "  SELECT run_id, retry_of FROM runs WHERE run_id = ?"
        "  UNION SELECT r.run_id, r.retry_of FROM runs r JOIN up ON r.run_id = up.retry_of),"
        " root(run_id) AS (SELECT run_id FROM up WHERE retry_of IS NULL),"
        " down(run_id) AS ("
        "  SELECT run_id FROM root"
        "  UNION SELECT r.run_id FROM runs r JOIN down ON r.retry_of = down.run_id)"
        " SELECT run_id FROM down WHERE run_id != ?",
        (run_id, run_id),
    ).fetchall()
    return [r["run_id"] for r in rows]


def check_identity(
    conn: sqlite3.Connection, invoice_id: str, version_id: str, run_id: str
) -> IdentityCheck:
    """Compare this run's invoice version with earlier outcomes for the same identity.

    1. A payment decides first: a different version is a revision; the same version is a
       duplicate of the paying run, or "new" when that run failed (it paid, then crashed) so
       the replay re-enters pay(), which returns the existing receipt.
    2. Otherwise the latest business outcome of a non-retry run of the same version makes
       this run a duplicate; failed and duplicate runs never count.
    3. Failing that, such an outcome of another version is a version conflict.

    A retry run (retry_of set) is never a duplicate: rule 1 sends a same-version payment
    back through pay() and rule 2 is skipped, but revisions and version conflicts still
    apply, with the run being retried and its retry chain excluded from prior outcomes.
    """
    new = IdentityCheck("new", None)
    this = conn.execute("SELECT retry_of FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if this is None:
        return new
    is_retry = this["retry_of"] is not None
    identity = conn.execute(
        "SELECT invoice_number_key FROM invoices WHERE invoice_id = ?", (invoice_id,)
    ).fetchone()
    if identity is None or identity["invoice_number_key"].startswith("pending:"):
        return new
    version = conn.execute(
        "SELECT version FROM invoice_versions WHERE version_id = ? AND invoice_id = ?",
        (version_id, invoice_id),
    ).fetchone()
    if version is None:
        return new

    payment = conn.execute(
        "SELECT p.version, r.run_id, r.status, r.invoice_id FROM payments p "
        "JOIN runs r ON r.run_id = p.run_id WHERE p.invoice_id = ?",
        (invoice_id,),
    ).fetchone()
    if payment is not None:
        if payment["version"] != version["version"]:
            return IdentityCheck("revision_after_payment", _prior(conn, payment))
        # The payment outranks every other run of this identity, so history is not consulted.
        if is_retry or payment["status"] == RunStatus.failed.value:
            return new
        return IdentityCheck("duplicate", _prior(conn, payment))

    excluded = [run_id, *(_retry_chain(conn, run_id) if is_retry else [])]
    slots = ",".join("?" * len(excluded))
    base = (
        f"SELECT run_id, status, invoice_id FROM runs WHERE invoice_id = ? "
        f"AND run_id NOT IN ({slots}) AND retry_of IS NULL AND status IN ({_OUTCOME_SLOTS}) "
        "AND version_id {op} ? ORDER BY started_at DESC, rowid DESC LIMIT 1"
    )
    args = (invoice_id, *excluded, *_OUTCOME_VALUES, version_id)
    if not is_retry:
        same = conn.execute(base.format(op="="), args).fetchone()
        if same is not None:
            return IdentityCheck("duplicate", _prior(conn, same))
    other = conn.execute(base.format(op="!="), args).fetchone()
    if other is not None:
        return IdentityCheck("version_conflict", _prior(conn, other))
    return new


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
