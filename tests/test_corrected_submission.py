"""Corrected-invoice submissions (P4-05, Decision 22): the explicit corrected path supersedes
the earlier versions of the same identity; a plain upload stays a version conflict."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from invoice_processing import ledger, review, service, storage
from invoice_processing.codes import ExecutionMode, FindingCode, ReviewRefusal, RunStatus
from tests.review_helpers import EVAL, INVOICES, REVIEW, count, payment_count, process, seeded_db

THRESHOLD = Path(__file__).resolve().parent / "fixtures" / "threshold"
ORIGINAL = INVOICES / "invoice_1013.json"
CORRECTED = REVIEW / "inv_1013_corrected.json"


def version_row(db: Path, invoice_id: str, version: int) -> dict:
    conn = storage.connect(db)
    try:
        row = conn.execute(
            "SELECT version_status, origin FROM invoice_versions "
            "WHERE invoice_id = ? AND version = ?",
            (invoice_id, version),
        ).fetchone()
        return dict(row)
    finally:
        conn.close()


def run_row(db: Path, run_id: str) -> dict:
    conn = storage.connect(db)
    try:
        return dict(conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone())
    finally:
        conn.close()


def audit(db: Path, run_id: str) -> list[dict]:
    conn = storage.connect(db)
    try:
        rows = conn.execute(
            "SELECT event, actor, payload_json FROM audit_events WHERE run_id = ? "
            "ORDER BY event_id",
            (run_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def submit(db: Path, invoice_id: str, path: Path = CORRECTED, **kwargs):
    kwargs.setdefault("reason", "Vendor reissued invoice")
    kwargs.setdefault("reviewer", "Ana")
    return review.submit_corrected_invoice(
        invoice_id,
        path,
        kwargs.pop("reason"),
        kwargs.pop("reviewer"),
        db_path=db,
        evaluation_date=EVAL,
        **kwargs,
    )


def refused(fn, *args, **kwargs) -> review.ReviewRefused:
    with pytest.raises(review.ReviewRefused) as e:
        fn(*args, **kwargs)
    return e.value


def test_corrected_1013_supersedes(tmp_path):
    db = seeded_db(tmp_path)
    r1 = process(ORIGINAL, db)
    assert r1.status == "rejected"
    started: list[str] = []
    r2 = submit(db, r1.invoice_id, on_run_started=started.append)
    assert r2.invoice_id == r1.invoice_id and r2.version == 2
    assert r2.status == "awaiting_human_approval"
    assert started == [r2.run_id]
    assert version_row(db, r1.invoice_id, 1)["version_status"] == "superseded"
    assert version_row(db, r1.invoice_id, 2) == {"version_status": "current", "origin": "source"}
    run = run_row(db, r2.run_id)
    assert run["trigger"] == "corrected_submission" and run["prior_run_id"] is None
    events = [e for e in audit(db, r2.run_id) if e["event"] == "corrected_submission"]
    assert len(events) == 1 and events[0]["actor"] == "Ana"
    assert "Vendor reissued invoice" in events[0]["payload_json"]
    codes = {f.code for f in r2.findings}
    assert FindingCode.version_conflict not in codes and FindingCode.total_mismatch not in codes
    r3 = review.approve(r1.invoice_id, 2, "Ana", "ok", db_path=db)
    assert r3.status == "paid_mock" and payment_count(db, r1.invoice_id) == 1


def test_plain_upload_is_version_conflict(tmp_path):
    db = seeded_db(tmp_path)
    r1 = process(ORIGINAL, db)
    r2 = process(CORRECTED, db)
    assert r2.invoice_id == r1.invoice_id and r2.status == "needs_review"
    assert FindingCode.version_conflict in {f.code for f in r2.findings}
    assert version_row(db, r1.invoice_id, 1)["version_status"] == "current"
    assert run_row(db, r2.run_id)["trigger"] == "submission"


def test_plain_upload_first_then_corrected_path_still_supersedes(tmp_path):  # Review Focus 4
    db = seeded_db(tmp_path)
    r1 = process(ORIGINAL, db)
    plain = process(CORRECTED, db)
    assert plain.status == "needs_review" and plain.version == 2
    r3 = submit(db, r1.invoice_id)
    assert r3.status == "awaiting_human_approval" and r3.version == 2
    assert r3.prior_run_id is None  # the byte-level duplicate check was skipped
    assert FindingCode.version_conflict not in {f.code for f in r3.findings}
    assert version_row(db, r1.invoice_id, 1)["version_status"] == "superseded"
    assert version_row(db, r1.invoice_id, 2)["version_status"] == "current"
    assert review.approve(r1.invoice_id, 2, "Ana", "ok", db_path=db).status == "paid_mock"


def test_corrected_matching_a_superseded_version_is_version_conflict(tmp_path):
    db = seeded_db(tmp_path)
    r1 = process(ORIGINAL, db)
    submit(db, r1.invoice_id)  # v1 superseded; v2 awaiting approval
    review.decline(r1.invoice_id, 2, "Ana", "Wrong PO", db_path=db)  # v2 rejected
    again = submit(db, r1.invoice_id, path=ORIGINAL)  # semantically v1
    assert again.version == 1 and again.status == "rejected"  # its own blockers still apply
    assert FindingCode.version_conflict in {f.code for f in again.findings}
    assert version_row(db, r1.invoice_id, 1)["version_status"] == "superseded"
    assert review.allowed_actions(r1.invoice_id, db_path=db).current_version == 2


def test_wrong_identity_refused(tmp_path):
    db = seeded_db(tmp_path)
    r1 = process(ORIGINAL, db)
    r2 = submit(db, r1.invoice_id, path=REVIEW / "source_error.json")
    assert r2.status == "failed" and r2.errors == ["corrected_identity_mismatch"]
    assert r2.invoice_id is None
    assert count(db, "SELECT COUNT(*) FROM invoices WHERE invoice_number_key LIKE '%4001%'") == 0
    assert (
        count(db, "SELECT COUNT(*) FROM invoice_versions WHERE invoice_id = ?", r1.invoice_id) == 1
    )
    assert version_row(db, r1.invoice_id, 1)["version_status"] == "current"
    assert review.allowed_actions(r1.invoice_id, db_path=db).status == "rejected"


def test_not_eligible(tmp_path):
    db = seeded_db(tmp_path)
    paid = process(INVOICES / "invoice_1001.txt", db)
    assert refused(submit, db, paid.invoice_id).code is ReviewRefusal.already_paid
    waiting = process(THRESHOLD / "valid_10000_01.json", db)
    e = refused(submit, db, waiting.invoice_id)
    assert e.code is ReviewRefusal.action_not_allowed
    assert e.current.status == "awaiting_human_approval"
    assert refused(submit, db, "inv-nope").code is ReviewRefusal.unknown_invoice
    r1 = process(ORIGINAL, db)
    runs = count(db, "SELECT COUNT(*) FROM runs")
    with pytest.raises(ValidationError):
        submit(db, r1.invoice_id, reason="   ")
    with pytest.raises(ValidationError):
        submit(db, r1.invoice_id, reviewer="")
    assert count(db, "SELECT COUNT(*) FROM runs") == runs


def test_not_eligible_when_an_earlier_version_awaits_approval(tmp_path):
    db = seeded_db(tmp_path)
    r1 = process(ORIGINAL, db)
    submit(db, r1.invoice_id)  # v2 awaiting approval
    e = refused(submit, db, r1.invoice_id)
    assert e.code is ReviewRefusal.action_not_allowed


def test_mode_defaults_to_latest_run(tmp_path, monkeypatch):
    db = seeded_db(tmp_path)
    r1 = process(ORIGINAL, db)
    seen: list[ExecutionMode] = []
    real = service.process_invoice

    def spy(path, mode, *args, **kwargs):
        seen.append(mode)
        return real(path, mode, *args, **kwargs)

    monkeypatch.setattr(service, "process_invoice", spy)
    assert submit(db, r1.invoice_id).mode == "offline"
    assert seen == [ExecutionMode.offline]


def test_superseded_history_kept(tmp_path):
    db = seeded_db(tmp_path)
    r1 = process(ORIGINAL, db)
    conn = storage.connect(db)
    try:
        before = (
            ledger.list_findings(conn, r1.run_id),
            ledger.get_decision(conn, r1.run_id),
            ledger.get_version(conn, r1.invoice_id, 1).invoice,
        )
    finally:
        conn.close()
    submit(db, r1.invoice_id)
    conn = storage.connect(db)
    try:
        after = (
            ledger.list_findings(conn, r1.run_id),
            ledger.get_decision(conn, r1.run_id),
            ledger.get_version(conn, r1.invoice_id, 1).invoice,
        )
        assert ledger.get_run(conn, r1.run_id).status is RunStatus.rejected
    finally:
        conn.close()
    assert after == before and before[1] is not None
    assert review.load_result(r1.run_id, db_path=db).status == "rejected"


def test_failed_corrected_submission_retry_keeps_the_link(tmp_path, monkeypatch):
    db = seeded_db(tmp_path)
    r1 = process(ORIGINAL, db)
    from invoice_processing.agents import approval

    real = approval.run
    monkeypatch.setattr(approval, "run", lambda *a, **k: (_ for _ in ()).throw(RuntimeError()))
    failed = submit(db, r1.invoice_id)
    assert failed.status == "failed" and failed.errors == ["unexpected_error"]
    monkeypatch.setattr(approval, "run", real)
    retried = service.retry_run(failed.run_id, CORRECTED, db, EVAL)
    assert retried.status == "awaiting_human_approval" and retried.version == 2
    assert FindingCode.version_conflict not in {f.code for f in retried.findings}
    assert run_row(db, retried.run_id)["trigger"] == "corrected_submission"
