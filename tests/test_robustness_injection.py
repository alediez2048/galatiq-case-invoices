"""P6-01 campaign 2: force an exception at each offline stage; never an extra payment."""

import pytest

from invoice_processing import intake, ledger, parsers, payments, policy
from invoice_processing.agents import approval, ingestion, validation
from invoice_processing.codes import RunStatus
from invoice_processing.parsers.base import ExtractionError
from invoice_processing.service import process_invoice
from tests.robustness import CORPUS, EVAL, OFF, PaymentSpy, fresh_db, payment_count, query

TXT = CORPUS / "invoice_1001.txt"  # clean, pays 5000.00


def boom(*a, **k):
    raise RuntimeError("injected")


def runs(db):
    return [tuple(r) for r in query(db, "SELECT status, error_code FROM runs ORDER BY rowid")]


# One clean, auto-payable fixture per format; the parser for that format is the injection site.
PARSER_CASES = [
    ("parse_txt", "invoice_1001.txt"),
    ("parse_json", "invoice_1004.json"),
    ("parse_csv", "invoice_1006.csv"),
    ("parse_xml", "invoice_1014.xml"),
    ("parse_pdf", "invoice_1011.pdf"),
]


@pytest.mark.parametrize(("parser", "name"), PARSER_CASES)
def test_parser_exception_fails_without_payment_then_clean_rerun_pays_once(
    tmp_path, monkeypatch, parser, name
):
    db = fresh_db(tmp_path)
    spy = PaymentSpy(monkeypatch)
    with monkeypatch.context() as m:
        m.setattr(parsers, parser, boom)
        r = process_invoice(CORPUS / name, OFF, db, EVAL)
    assert r.status is RunStatus.failed and r.errors == ["unexpected_error"]
    assert r.receipt is None and payment_count(db) == 0 and spy.keys == []
    assert runs(db) == [("failed", "unexpected_error")]
    if name == "invoice_1014.xml":  # EUR: legitimately never auto-pays
        return
    again = process_invoice(CORPUS / name, OFF, db, EVAL)
    assert again.status is RunStatus.paid_mock and payment_count(db) == 1
    assert len(spy.keys) == 1


@pytest.mark.parametrize(("parser", "name"), PARSER_CASES)
def test_parser_extraction_error_keeps_its_code(tmp_path, monkeypatch, parser, name):
    db = fresh_db(tmp_path)

    def refuse(*a, **k):
        raise ExtractionError("injected_code", "refused")

    monkeypatch.setattr(parsers, parser, refuse)
    r = process_invoice(CORPUS / name, OFF, db, EVAL)
    assert r.status is RunStatus.failed and r.errors == ["injected_code"]
    assert payment_count(db) == 0
    assert query(db, "SELECT COUNT(*) FROM invoices")[0][0] == 0


def test_intake_exception_propagates_and_creates_no_run(tmp_path, monkeypatch):
    db = fresh_db(tmp_path)
    spy = PaymentSpy(monkeypatch)
    from invoice_processing import service

    monkeypatch.setattr(service.intake, "read_source", boom)
    with pytest.raises(RuntimeError, match="injected"):
        process_invoice(TXT, OFF, db, EVAL)
    assert query(db, "SELECT COUNT(*) FROM runs")[0][0] == 0
    assert payment_count(db) == 0 and spy.keys == []


def test_intake_error_codes_never_create_a_run(tmp_path):
    db = fresh_db(tmp_path)
    with pytest.raises(intake.IntakeError) as e:
        process_invoice(tmp_path / "missing.txt", OFF, db, EVAL)
    assert e.value.code == "not_found"
    assert query(db, "SELECT COUNT(*) FROM runs")[0][0] == 0


# (label, module, attribute) for stages that raise after the run exists, before payment.
PIPELINE_SITES = [
    ("normalization", ingestion, "normalize"),
    ("ingestion_agent", ingestion, "run"),
    ("validation", validation, "run"),
    ("approval", approval, "run"),
    ("gate", policy, "evaluate"),
    ("record_decision", ledger, "record_decision"),
]


@pytest.mark.parametrize(
    ("label", "module", "attr"), PIPELINE_SITES, ids=[s[0] for s in PIPELINE_SITES]
)
def test_pipeline_stage_exception_fails_without_payment(tmp_path, monkeypatch, label, module, attr):
    db = fresh_db(tmp_path)
    spy = PaymentSpy(monkeypatch)
    with monkeypatch.context() as m:
        m.setattr(module, attr, boom)
        r = process_invoice(TXT, OFF, db, EVAL)
    assert r.status is RunStatus.failed and r.errors == ["unexpected_error"]
    assert payment_count(db) == 0 and spy.keys == []
    assert runs(db) == [("failed", "unexpected_error")]
    again = process_invoice(TXT, OFF, db, EVAL)
    assert again.status is RunStatus.paid_mock and again.prior_run_id is None
    assert payment_count(db) == 1 and len(spy.keys) == 1


def test_payment_exception_before_commit_rolls_back_then_pays_once(tmp_path, monkeypatch):
    db = fresh_db(tmp_path)
    spy = PaymentSpy(monkeypatch)
    real = payments.mock_payment

    def crash(*a, **k):
        spy.keys.append(k.get("idempotency_key"))
        raise RuntimeError("gateway down")

    with monkeypatch.context() as m:
        m.setattr(payments, "mock_payment", crash)
        r = process_invoice(TXT, OFF, db, EVAL)
    assert r.status is RunStatus.failed and payment_count(db) == 0
    assert runs(db) == [("failed", "unexpected_error")]
    monkeypatch.setattr(payments, "mock_payment", real)
    second = process_invoice(TXT, OFF, db, EVAL)
    assert second.status is RunStatus.paid_mock and payment_count(db) == 1


def test_gateway_declining_is_refused_not_paid(tmp_path, monkeypatch):
    db = fresh_db(tmp_path)
    monkeypatch.setattr(payments, "mock_payment", lambda *a, **k: {"status": "error"})
    r = process_invoice(TXT, OFF, db, EVAL)
    assert r.status is RunStatus.failed
    assert r.errors == ["payment_not_authorized:mock_payment_failed"]
    assert payment_count(db) == 0


def test_failure_between_gateway_and_commit_replays_with_same_idempotency_key(
    tmp_path, monkeypatch
):
    """Gateway called, then the INSERT-side write fails: rolled back; the replay re-calls the
    gateway with the *same* key (the documented at-least-once contract) and records once."""
    db = fresh_db(tmp_path)
    spy = PaymentSpy(monkeypatch)
    real_audit = ledger.append_audit_event

    def fail_payment_audit(conn, run_id, stage, event, *a, **k):
        if event == "payment_succeeded":
            raise RuntimeError("disk full")
        return real_audit(conn, run_id, stage, event, *a, **k)

    with monkeypatch.context() as m:
        m.setattr(ledger, "append_audit_event", fail_payment_audit)
        first = process_invoice(TXT, OFF, db, EVAL)
    assert first.status is RunStatus.failed and payment_count(db) == 0
    assert len(spy.keys) == 1
    second = process_invoice(TXT, OFF, db, EVAL)
    assert second.status is RunStatus.paid_mock and payment_count(db) == 1
    assert len(spy.keys) == 2 and spy.keys[0] == spy.keys[1]


def test_payment_exception_after_commit_rerun_reveals_existing_payment(tmp_path, monkeypatch):
    db = fresh_db(tmp_path)
    spy = PaymentSpy(monkeypatch)
    real = ledger.update_run_status

    def fail_on_paid(conn, run_id, status):
        if status is RunStatus.paid_mock:
            raise RuntimeError("post-commit failure")
        return real(conn, run_id, status)

    with monkeypatch.context() as m:
        m.setattr(ledger, "update_run_status", fail_on_paid)
        first = process_invoice(TXT, OFF, db, EVAL)
    assert first.status is RunStatus.failed and first.errors == ["unexpected_error"]
    assert payment_count(db) == 1 and len(spy.keys) == 1  # committed before the failure
    receipt_id = query(db, "SELECT receipt_id FROM payments")[0][0]

    second = process_invoice(TXT, OFF, db, EVAL)
    assert payment_count(db) == 1 and len(spy.keys) == 1  # no second gateway call
    assert second.receipt is not None and second.receipt.receipt_id == receipt_id
    assert second.status in (RunStatus.paid_mock, RunStatus.duplicate)
    third = process_invoice(TXT, OFF, db, EVAL)
    assert third.status is RunStatus.duplicate
    assert payment_count(db) == 1 and len(spy.keys) == 1


@pytest.mark.xfail(
    strict=True,
    reason="duplicate of a post-commit-recovered run carries no receipt — see results doc",
)
def test_duplicate_after_post_commit_recovery_still_shows_receipt(tmp_path, monkeypatch):
    db = fresh_db(tmp_path)
    real = ledger.update_run_status

    def fail_on_paid(conn, run_id, status):
        if status is RunStatus.paid_mock:
            raise RuntimeError("post-commit failure")
        return real(conn, run_id, status)

    with monkeypatch.context() as m:
        m.setattr(ledger, "update_run_status", fail_on_paid)
        process_invoice(TXT, OFF, db, EVAL)  # pays, then fails after commit
    recovered = process_invoice(TXT, OFF, db, EVAL)  # reveals the payment (created=False)
    third = process_invoice(TXT, OFF, db, EVAL)
    assert third.status is RunStatus.duplicate
    assert third.receipt is not None and third.receipt.receipt_id == recovered.receipt.receipt_id


def test_set_invoice_status_failure_after_payment_keeps_paid_run(tmp_path, monkeypatch):
    db = fresh_db(tmp_path)
    monkeypatch.setattr(ledger, "set_invoice_status", boom)
    r = process_invoice(TXT, OFF, db, EVAL)
    assert r.status is RunStatus.paid_mock and r.errors == ["unexpected_error"]
    assert payment_count(db) == 1
