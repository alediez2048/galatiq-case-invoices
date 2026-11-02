"""Append-only review history: SQLite triggers refuse edits and deletes (Decision 2)."""

import sqlite3
from datetime import UTC, date, datetime

import pytest

from invoice_processing import ledger, payments, seed, storage
from invoice_processing.codes import ExecutionMode, HumanReviewAction, RunStatus, SourceFormat
from invoice_processing.policy import POLICY_VERSION
from invoice_processing.schemas import Correction, HumanReview, SourceDocument
from invoice_processing.service import process_invoice
from tests.test_payments import approved_run

IMMUTABLE = [
    "sources",
    "invoice_versions",
    "corrections",
    "human_reviews",
    "payments",
    "audit_events",
    "findings",
    "decisions",
]
EVAL = date(2026, 1, 31)


@pytest.fixture
def conn_with_history(db_path):
    c = storage.connect(db_path)
    storage.init_schema(c)
    seed.seed_inventory(c)
    c.close()
    paid = process_invoice("data/invoices/invoice_1001.txt", ExecutionMode.offline, db_path, EVAL)
    assert paid.status is RunStatus.paid_mock
    # a paid invoice cannot be superseded, so the correction goes to a rejected one
    rejected = process_invoice(
        "data/invoices/invoice_1002.txt", ExecutionMode.offline, db_path, EVAL
    )
    assert rejected.status is RunStatus.rejected
    c = storage.connect(db_path)
    storage.init_schema(c)
    run = c.execute(
        "SELECT run_id, invoice_id, source_id FROM runs WHERE run_id = ?", (rejected.run_id,)
    ).fetchone()
    base = ledger.get_version(c, run["invoice_id"], 1)
    _, v2 = ledger.record_correction_version(
        c, run["invoice_id"], base.invoice, run["source_id"], base_version=1
    )
    now = datetime(2026, 1, 31, tzinfo=UTC)
    ledger.record_correction(
        c,
        Correction(
            invoice_id=run["invoice_id"],
            base_version=1,
            field="stated.total",
            old_value=None,
            new_value="1.00",
            evidence_location="line:9",
            reviewer="Ana",
            reason="check",
            created_at=now,
            resulting_version=v2,
        ),
        run["run_id"],
    )
    ledger.record_human_review(
        c,
        HumanReview(
            invoice_id=run["invoice_id"],
            version=1,
            action=HumanReviewAction.approve,
            reviewer="Ana",
            reason="ok",
            policy_version=POLICY_VERSION,
            created_at=now,
        ),
        run["run_id"],
    )
    yield c
    c.close()


def write(conn, sql, args=()):
    with storage.write_transaction(conn):
        conn.execute(sql, args)


def test_every_immutable_table_has_rows(conn_with_history):
    for table in IMMUTABLE:
        assert conn_with_history.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] > 0


def test_trigger_names(conn):
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")}
    assert names == {f"immutable_{t}_{op}" for t in IMMUTABLE for op in ("update", "delete")}


@pytest.mark.parametrize("table", IMMUTABLE)
def test_delete_rejected(conn_with_history, table):
    before = conn_with_history.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    with pytest.raises(sqlite3.DatabaseError, match=f"immutable:{table}"):
        write(conn_with_history, f"DELETE FROM {table}")
    assert conn_with_history.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == before


@pytest.mark.parametrize(
    ("table", "column"),
    [
        ("sources", "original_name"),
        ("invoice_versions", "payload_json"),
        ("corrections", "reason"),
        ("human_reviews", "reason"),
        ("payments", "amount"),
        ("audit_events", "payload_json"),
        ("findings", "severity"),
        ("decisions", "payload_json"),
    ],
)
def test_update_rejected(conn_with_history, table, column):
    with pytest.raises(sqlite3.DatabaseError, match=f"immutable:{table}"):
        write(conn_with_history, f"UPDATE {table} SET {column} = 'changed'")


@pytest.mark.parametrize(
    ("table", "allowed"),
    [("sources", "extracted_text"), ("invoice_versions", "version_status"), ("payments", "run_id")],
)
def test_every_other_column_of_an_exception_table_is_guarded(conn_with_history, table, allowed):
    # A column added later and left out of the trigger's comparison would fail here.
    columns = [r["name"] for r in conn_with_history.execute(f"PRAGMA table_info({table})")]
    for column in columns:
        if column == allowed:
            continue
        with pytest.raises(sqlite3.DatabaseError, match=f"immutable:{table}"):
            write(
                conn_with_history,
                f"UPDATE {table} SET {column} = "
                f"CASE WHEN {column} IS NULL THEN 'x' ELSE {column} || 'x' END",
            )


def test_noop_update_rejected(conn_with_history):
    with pytest.raises(sqlite3.DatabaseError, match="immutable:invoice_versions"):
        write(conn_with_history, "UPDATE invoice_versions SET version_status = version_status")


def test_version_status_current_to_superseded_allowed(conn_with_history):
    c = conn_with_history
    write(c, "UPDATE invoice_versions SET version_status = 'superseded' WHERE version = 2")
    statuses = c.execute(
        "SELECT version, version_status FROM invoice_versions WHERE origin = 'correction'"
    ).fetchall()
    assert [tuple(r) for r in statuses] == [(2, "superseded")]


def test_version_status_superseded_to_current_rejected(conn_with_history):
    with pytest.raises(sqlite3.DatabaseError, match="immutable:invoice_versions"):
        write(
            conn_with_history,
            "UPDATE invoice_versions SET version_status = 'current' "
            "WHERE version_status = 'superseded'",
        )


def test_version_status_change_with_another_column_rejected(conn_with_history):
    with pytest.raises(sqlite3.DatabaseError, match="immutable:invoice_versions"):
        write(
            conn_with_history,
            "UPDATE invoice_versions SET version_status = 'superseded', payload_json = '{}' "
            "WHERE version = 2",
        )


def test_extracted_text_fill_allowed_once(conn_with_history):
    c = conn_with_history
    # Processing fills extracted_text for every format (Decision 9), so use a fresh source.
    processed = c.execute("SELECT extracted_text FROM sources ORDER BY rowid").fetchone()[0]
    assert processed.startswith("INVOICE")
    source = SourceDocument(
        source_id="src-unprocessed",
        content_hash="0" * 64,
        original_name="unprocessed.txt",
        format=SourceFormat.txt,
        size_bytes=1,
        parser_version="test",
    )
    source_id, _ = ledger.record_source(c, source)

    def text():
        row = c.execute("SELECT extracted_text FROM sources WHERE source_id = ?", (source_id,))
        return row.fetchone()[0]

    assert text() is None
    ledger.set_extracted_text(c, source_id, "INVOICE text")
    ledger.set_extracted_text(c, source_id, "other")  # guarded by the WHERE: a no-op
    assert text() == "INVOICE text"
    for value in ("other", None):
        with pytest.raises(sqlite3.DatabaseError, match="immutable:sources"):
            write(
                c, "UPDATE sources SET extracted_text = ? WHERE source_id = ?", (value, source_id)
            )
    assert text() == "INVOICE text"


def test_extracted_text_fill_with_another_column_rejected(conn_with_history):
    with pytest.raises(sqlite3.DatabaseError, match="immutable:sources"):
        write(conn_with_history, "UPDATE sources SET extracted_text = 't', original_name = 'n'")


def _other_run(conn):
    source_id = conn.execute("SELECT source_id FROM runs").fetchone()[0]
    return ledger.start_run(conn, ExecutionMode.offline, source_id, EVAL)


def test_payment_repoint_only_from_failed_run(conn_with_history):
    c = conn_with_history
    payer = c.execute("SELECT run_id FROM payments").fetchone()[0]
    assert ledger.get_run_status(c, payer) is RunStatus.paid_mock
    other = _other_run(c)
    with pytest.raises(sqlite3.DatabaseError, match="immutable:payments"):
        write(c, "UPDATE payments SET run_id = ?", (other,))
    write(c, "UPDATE runs SET status = 'failed' WHERE run_id = ?", (payer,))
    with pytest.raises(sqlite3.DatabaseError, match="immutable:payments"):
        write(c, "UPDATE payments SET run_id = ?, amount = '1.00'", (other,))
    write(c, "UPDATE payments SET run_id = ?", (other,))
    assert c.execute("SELECT run_id FROM payments").fetchone()[0] == other


def test_concurrent_style_second_pay_same_version_returns_receipt_without_update(conn, monkeypatch):
    monkeypatch.setattr(payments, "mock_payment", lambda *a, **k: {"status": "success"})
    invoice_id, version_id, run1 = approved_run(conn)
    first = payments.pay(conn, invoice_id, version_id, run1)
    _, _, run2 = approved_run(conn, n=2)  # same identity and version, its own approved decision
    second = payments.pay(conn, invoice_id, version_id, run2)
    assert first.created and not second.created
    assert second.receipt == first.receipt
    assert conn.execute("SELECT run_id FROM payments").fetchone()[0] == run1
    events = conn.execute("SELECT event FROM audit_events WHERE event LIKE '%repoint%'")
    assert events.fetchall() == []


def test_mutable_tables_stay_mutable(conn_with_history):
    c = conn_with_history
    write(c, "INSERT INTO idempotency_keys VALUES ('k', 'e', '{}', 't')")
    write(c, "UPDATE idempotency_keys SET response_json = '[]'")
    write(c, "DELETE FROM idempotency_keys")
    write(c, "UPDATE invoices SET updated_at = 'now'")
    write(c, "UPDATE inventory SET stock = stock")
    ledger.mark_interrupted_runs(c, started_before="9999")


def _replace_existing_row(conn, table):
    """INSERT OR REPLACE a copy of the table's first row (same key): a hidden DELETE."""
    row = conn.execute(f"SELECT * FROM {table} LIMIT 1").fetchone()
    cols = row.keys()
    slots = ",".join("?" * len(cols))
    write(conn, f"INSERT OR REPLACE INTO {table} ({','.join(cols)}) VALUES ({slots})", tuple(row))


@pytest.mark.parametrize("table", IMMUTABLE)
def test_insert_or_replace_rejected(conn_with_history, table):
    # REPLACE deletes the conflicting row; delete triggers fire only with recursive_triggers.
    before = [tuple(r) for r in conn_with_history.execute(f"SELECT * FROM {table}")]
    with pytest.raises(sqlite3.DatabaseError, match=f"immutable:{table}"):
        _replace_existing_row(conn_with_history, table)
    assert [tuple(r) for r in conn_with_history.execute(f"SELECT * FROM {table}")] == before


def test_connections_enable_recursive_triggers(conn):
    assert conn.execute("PRAGMA recursive_triggers").fetchone()[0] == 1
