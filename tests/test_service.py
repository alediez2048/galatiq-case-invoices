import shutil
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from invoice_processing import ledger, payments, seed, storage
from invoice_processing.agents import validation
from invoice_processing.codes import ExecutionMode, FindingCode, RunStatus
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


def test_unparsed_line_is_surfaced_as_info_and_audited(tmp_path):
    text = FIXTURE.read_text().rstrip("\n") + "\nRemit To: Acct 999-NEW-BANK\n"
    src = tmp_path / "extra.txt"
    src.write_text(text)
    line_no = len(text.splitlines())
    db = tmp_db(tmp_path)
    r = process_invoice(src, OFF, db, EVAL)
    assert r.status is RunStatus.paid_mock
    unparsed = [f for f in r.findings if f.code.value == "unparsed_line"]
    assert len(unparsed) == 1
    assert unparsed[0].severity.value == "info"
    assert unparsed[0].evidence[0].location == f"line:{line_no}"
    c = connect(db)
    try:
        events = ledger.list_audit_events(c, r.run_id)
    finally:
        c.close()
    extracted = [e for e in events if e["event"] == "extracted"][0]["payload"]
    assert extracted["issues"] == [
        {
            "code": "unparsed_line",
            "location": f"line:{line_no}",
            "snippet": "Remit To: Acct 999-NEW-BANK",
        }
    ]


def test_currency_assumed_finding_recorded_once(tmp_path):
    db = tmp_db(tmp_path)
    r = process_invoice(FIXTURE, OFF, db, EVAL)
    n = count(db, "findings", f"WHERE code='currency_assumed_usd' AND run_id='{r.run_id}'")
    assert n == 1


CORPUS_EVAL = date(2026, 1, 31)


@pytest.fixture
def seeded_db(tmp_path):
    return tmp_db(tmp_path)


def run(name, db):
    return process_invoice(f"data/invoices/{name}", OFF, db, CORPUS_EVAL)


def n_payments(db):
    return count(db, "payments")


def invoice_row(db, invoice_id):
    c = connect(db)
    try:
        row = c.execute(
            "SELECT status, current_version FROM invoices WHERE invoice_id = ?", (invoice_id,)
        ).fetchone()
        return tuple(row)
    finally:
        c.close()


@pytest.mark.parametrize(
    ("first", "second", "first_status", "second_status"),
    [
        ("invoice_1011.txt", "invoice_1011.pdf", RunStatus.paid_mock, RunStatus.duplicate),
        ("invoice_1012.txt", "invoice_1012.pdf", RunStatus.paid_mock, RunStatus.duplicate),
        ("invoice_1013.json", "invoice_1013.pdf", RunStatus.rejected, RunStatus.duplicate),
    ],
)
def test_alternate_format_is_duplicate(seeded_db, first, second, first_status, second_status):
    a = run(first, seeded_db)
    before = invoice_row(seeded_db, a.invoice_id)
    b = run(second, seeded_db)
    assert (a.status, b.status) == (first_status, second_status)
    assert b.prior_run_id == a.run_id and b.invoice_id == a.invoice_id
    assert b.receipt == a.receipt
    assert n_payments(seeded_db) == (1 if first_status is RunStatus.paid_mock else 0)
    assert invoice_row(seeded_db, a.invoice_id) == before
    c = connect(seeded_db)
    try:
        row = c.execute(
            "SELECT status, prior_run_id FROM runs WHERE run_id = ?", (b.run_id,)
        ).fetchone()
        events = ledger.list_audit_events(c, b.run_id)
    finally:
        c.close()
    assert tuple(row) == ("duplicate", a.run_id)
    dup = [e for e in events if e["stage"] == "ingestion" and e["event"] == "duplicate"]
    assert len(dup) == 1
    assert dup[0]["payload"]["prior_run_id"] == a.run_id
    assert dup[0]["payload"]["prior_status"] == first_status.value
    assert dup[0]["payload"]["match"] == "semantic"


def test_revision_after_payment(seeded_db):
    a = run("invoice_1004.json", seeded_db)
    b = run("invoice_1004_revised.json", seeded_db)
    assert a.status is RunStatus.paid_mock and a.receipt.amount == Decimal("1890.00")
    assert b.status is RunStatus.needs_review and b.receipt is None
    assert FindingCode.revision_after_payment in {f.code for f in b.findings}
    assert n_payments(seeded_db) == 1
    assert invoice_row(seeded_db, a.invoice_id) == ("paid_mock", 1)


def test_revision_after_payment_reverse_order(seeded_db):
    a = run("invoice_1004_revised.json", seeded_db)
    b = run("invoice_1004.json", seeded_db)
    assert a.status is RunStatus.paid_mock and a.receipt.amount == Decimal("5940.00")
    assert b.status is RunStatus.needs_review
    assert FindingCode.revision_after_payment in {f.code for f in b.findings}
    assert n_payments(seeded_db) == 1


def test_version_conflict_when_prior_unpaid(seeded_db, tmp_path):
    # 1013 JSON is rejected; a changed copy of it under the same identity conflicts.
    a = run("invoice_1013.json", seeded_db)
    changed = tmp_path / "invoice_1013_changed.json"
    original = Path("data/invoices/invoice_1013.json").read_text()
    changed.write_text(original.replace('"quantity": 1,', '"quantity": 2,'))
    b = process_invoice(changed, OFF, seeded_db, CORPUS_EVAL)
    assert a.status is RunStatus.rejected
    conflict = [f for f in b.findings if f.code is FindingCode.version_conflict]
    assert len(conflict) == 1
    assert conflict[0].severity.value == "review" and conflict[0].observed == a.run_id
    assert b.invoice_id == a.invoice_id
    assert n_payments(seeded_db) == 0


def test_failed_prior_format_is_not_duplicate(seeded_db, monkeypatch):
    # First attempt fails inside validation; the PDF afterwards processes normally and pays.
    def boom(*a, **k):
        raise RuntimeError("injected")

    with monkeypatch.context() as m:
        m.setattr(validation, "run", boom)
        first = run("invoice_1011.txt", seeded_db)
    assert first.status is RunStatus.failed
    second = run("invoice_1011.pdf", seeded_db)
    assert second.status is RunStatus.paid_mock and second.prior_run_id is None
    assert n_payments(seeded_db) == 1
