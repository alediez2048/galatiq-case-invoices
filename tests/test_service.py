import shutil
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from invoice_processing import ledger, payments, seed, storage
from invoice_processing.agents import validation
from invoice_processing.codes import ExecutionMode, RunStatus
from invoice_processing.intake import IntakeError
from invoice_processing.service import process_invoice
from invoice_processing.storage import connect

FIXTURE = Path("data/invoices/invoice_1001.txt")
EVAL = date(2026, 1, 20)
OFF = ExecutionMode.offline


def tmp_db(tmp_path) -> Path:
    db = tmp_path / "svc.db"
    c = connect(db)
    storage.init_schema(c)
    seed.seed_inventory(c)
    c.close()
    return db


def count(db, table, where=""):
    c = connect(db)
    try:
        return c.execute(f"SELECT COUNT(*) FROM {table} {where}").fetchone()[0]
    finally:
        c.close()


def test_inv_1001_offline_paid(tmp_path):
    r = process_invoice(FIXTURE, OFF, tmp_db(tmp_path), EVAL)
    assert r.status is RunStatus.paid_mock and r.receipt.amount == Decimal("5000.00")
    assert r.receipt.currency == "USD"
    assert r.evaluation_date == EVAL and r.source_hash and r.invoice_id
    assert r.decision is not None and r.errors == []
    assert {"ingestion", "validation", "approval", "payment"} <= set(r.timings_ms)


def test_rerun_is_duplicate_one_payment(tmp_path):
    db = tmp_db(tmp_path)
    first = process_invoice(FIXTURE, OFF, db, EVAL)
    second = process_invoice(FIXTURE, OFF, db, EVAL)
    assert second.status is RunStatus.duplicate and second.prior_run_id == first.run_id
    assert second.receipt.receipt_id == first.receipt.receipt_id
    c = connect(db)
    assert c.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == 1
    assert c.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 2
    assert c.execute("SELECT status FROM invoices").fetchone()[0] == "paid_mock"


def test_same_bytes_new_filename_is_duplicate(tmp_path):
    db = tmp_db(tmp_path)
    first = process_invoice(FIXTURE, OFF, db, EVAL)
    copy = tmp_path / "renamed_copy.txt"
    shutil.copy(FIXTURE, copy)
    second = process_invoice(copy, OFF, db, EVAL)
    assert second.status is RunStatus.duplicate and second.prior_run_id == first.run_id
    assert count(db, "payments") == 1


def test_missing_file_raises_and_creates_no_run(tmp_path):
    db = tmp_db(tmp_path)
    with pytest.raises(IntakeError):
        process_invoice(tmp_path / "nope.txt", OFF, db, EVAL)
    assert count(db, "runs") == 0


def test_failed_then_rerun_is_normal(tmp_path, monkeypatch):
    db = tmp_db(tmp_path)

    def boom(*a, **k):
        raise RuntimeError("injected")

    with monkeypatch.context() as m:
        m.setattr(validation, "run", boom)
        first = process_invoice(FIXTURE, OFF, db, EVAL)
    assert first.status is RunStatus.failed and count(db, "payments") == 0
    second = process_invoice(FIXTURE, OFF, db, EVAL)
    assert second.status is RunStatus.paid_mock and second.prior_run_id is None
    assert count(db, "payments") == 1


def test_injected_validation_exception_fails_without_payment(tmp_path, monkeypatch):
    db = tmp_db(tmp_path)

    def boom(*a, **k):
        raise RuntimeError("secret detail")

    monkeypatch.setattr(validation, "run", boom)
    r = process_invoice(FIXTURE, OFF, db, EVAL)
    assert r.status is RunStatus.failed and r.errors == ["unexpected_error"]
    assert count(db, "payments") == 0
    c = connect(db)
    row = c.execute("SELECT status, error_code, error_message FROM runs").fetchone()
    assert tuple(row) == ("failed", "unexpected_error", "RuntimeError")
    events = ledger.list_audit_events(c, r.run_id)
    assert any(e["stage"] == "service" and e["event"] == "failed" for e in events)


def test_interrupted_run_then_rerun_does_not_pay_twice(tmp_path, monkeypatch):
    db = tmp_db(tmp_path)
    real_pay = payments.mock_payment
    pay_calls = []

    def spy(*a, **k):
        pay_calls.append(1)
        return real_pay(*a, **k)

    monkeypatch.setattr(payments, "mock_payment", spy)
    real_update = ledger.update_run_status

    def crash_on_paid(conn, run_id, status):
        if status is RunStatus.paid_mock:
            raise KeyboardInterrupt
        return real_update(conn, run_id, status)

    with monkeypatch.context() as m:
        m.setattr(ledger, "update_run_status", crash_on_paid)
        with pytest.raises(KeyboardInterrupt):
            process_invoice(FIXTURE, OFF, db, EVAL)
    c = connect(db)
    first = c.execute("SELECT run_id, status FROM runs").fetchone()
    assert count(db, "payments") == 1
    assert first["status"] == "approved"
    receipt_before = c.execute("SELECT receipt_id FROM payments").fetchone()[0]
    c.close()

    second = process_invoice(FIXTURE, OFF, db, EVAL)
    c = connect(db)
    old = c.execute(
        "SELECT status, error_code FROM runs WHERE run_id = ?", (first["run_id"],)
    ).fetchone()
    assert tuple(old) == ("failed", "interrupted")
    assert second.status is RunStatus.paid_mock
    assert second.receipt.receipt_id == receipt_before
    assert count(db, "payments") == 1
    assert len(pay_calls) == 1


def test_process_invoice_marks_interrupted_runs_first(tmp_path):
    db = tmp_db(tmp_path)
    c = connect(db)
    source = __import__("invoice_processing.intake", fromlist=["x"]).read_source(FIXTURE)[0]
    ledger.record_source(c, source)
    stale = ledger.start_run(c, OFF, source.source_id, EVAL)
    c.close()
    r = process_invoice(FIXTURE, OFF, db, EVAL)
    c = connect(db)
    row = c.execute("SELECT status, error_code FROM runs WHERE run_id = ?", (stale,)).fetchone()
    assert tuple(row) == ("failed", "interrupted")
    assert r.run_id != stale and r.status is RunStatus.paid_mock


def test_live_mode_raises_and_creates_no_run(tmp_path):
    from invoice_processing.reasoning import ProviderUnavailable

    db = tmp_db(tmp_path)
    with pytest.raises(ProviderUnavailable):
        process_invoice(FIXTURE, ExecutionMode.live, db, EVAL)
    assert count(db, "runs") == 0


def test_error_after_terminal_keeps_run_status(tmp_path, monkeypatch):
    db = tmp_db(tmp_path)

    def boom(*a, **k):
        raise RuntimeError("late failure")

    monkeypatch.setattr(ledger, "set_invoice_status", boom)
    r = process_invoice(FIXTURE, OFF, db, EVAL)
    assert r.status is RunStatus.paid_mock and r.errors == ["unexpected_error"]
    c = connect(db)
    assert c.execute("SELECT status FROM runs").fetchone()[0] == "paid_mock"
    assert count(db, "payments") == 1
    events = ledger.list_audit_events(c, r.run_id)
    assert any(e["stage"] == "service" and e["event"] == "failed" for e in events)


def test_duplicate_of_non_paid_outcome_leaves_invoice_status(tmp_path, monkeypatch):
    from invoice_processing import service

    db = tmp_db(tmp_path)
    big = tmp_path / "big.txt"
    text = FIXTURE.read_text()
    text = text.replace("qty: 10", "qty: 1000").replace("$5,000.00", "$255,000.00")
    big.write_text(text)
    first = process_invoice(big, OFF, db, EVAL)
    assert first.status is RunStatus.rejected
    c = connect(db)
    before = c.execute("SELECT status FROM invoices").fetchone()[0]
    assert before == "rejected"
    c.close()

    built = []
    real_build = service.build_graph
    monkeypatch.setattr(
        service, "build_graph", lambda *a, **k: built.append(1) or real_build(*a, **k)
    )
    second = process_invoice(big, OFF, db, EVAL)
    assert second.status is RunStatus.duplicate and second.prior_run_id == first.run_id
    assert built == []
    c = connect(db)
    assert c.execute("SELECT status FROM invoices").fetchone()[0] == before
