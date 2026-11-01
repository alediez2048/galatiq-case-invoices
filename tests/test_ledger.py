from datetime import date
from decimal import Decimal

import pytest

from invoice_processing import ledger, storage
from invoice_processing.codes import ExecutionMode, InvoiceStatus, RunStatus
from invoice_processing.ledger import (
    append_audit_event,
    finish_run,
    list_audit_events,
    semantic_hash,
    start_run,
    update_run_status,
    upsert_invoice,
)
from invoice_processing.schemas import SourceDocument
from invoice_processing.transitions import IllegalTransition
from tests.helpers import inv_1001

EVAL = date(2026, 1, 1)


def make_source(n: int = 1, content_hash: str | None = None) -> SourceDocument:
    return SourceDocument(
        source_id=f"src-{n}",
        content_hash=content_hash or f"hash-{n}",
        original_name=f"f{n}.txt",
        format="txt",
        size_bytes=10,
        parser_version="t1",
    )


@pytest.fixture
def sid(conn):
    return ledger.record_source(conn, make_source())[0]


@pytest.fixture
def rid(conn, sid):
    return start_run(conn, ExecutionMode.offline, sid, EVAL)


def test_record_source_twice_returns_one_row(conn):
    first = ledger.record_source(conn, make_source())
    second = ledger.record_source(conn, make_source(2, content_hash="hash-1"))
    assert first == ("src-1", False)
    assert second == ("src-1", True)
    assert conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 1


def test_semantic_hash_ignores_filename_whitespace_and_line_order():
    a = inv_1001()
    b = a.model_copy(
        update={
            "source_id": "b",
            "lines": list(reversed(a.lines)),
            "vendor_name": "  Widgets   Inc. ",
        }
    )
    assert semantic_hash(a) == semantic_hash(b)
    c = a.model_copy(
        update={"lines": [a.lines[0].model_copy(update={"quantity": Decimal("11")}), a.lines[1]]}
    )
    assert semantic_hash(a) != semantic_hash(c)
    d = a.model_copy(update={"stated": a.stated.model_copy(update={"total": Decimal("5E+3")})})
    assert semantic_hash(a) == semantic_hash(d)


def test_provisional_identities_differ_per_source(conn):
    i1 = upsert_invoice(conn, None, "INV-1009", "h1")
    i2 = upsert_invoice(conn, "", None, "h2")
    assert i1 != i2
    row = conn.execute(
        "SELECT vendor_key, invoice_number_key, status FROM invoices WHERE invoice_id=?", (i1,)
    ).fetchone()
    assert tuple(row) == ("pending", "pending:h1", "processing")


def test_upsert_same_identity_returns_same_invoice(conn):
    a = upsert_invoice(conn, "widgets inc.", "INV-1001", "h1")
    b = upsert_invoice(conn, "widgets inc.", "INV-1001", "h2")
    assert a == b and a.startswith("inv-")
    assert conn.execute("SELECT COUNT(*) FROM invoices").fetchone()[0] == 1


def test_record_version_dedupes_by_semantic_hash(conn, sid):
    inv = upsert_invoice(conn, "widgets inc.", "INV-1001", "h")
    first = ledger.record_version(conn, inv, inv_1001(), sid)
    again = ledger.record_version(conn, inv, inv_1001(), sid)
    assert first[1] == 1 and again == first
    changed = inv_1001().model_copy(update={"currency": "EUR"})
    _, v2 = ledger.record_version(conn, inv, changed, sid)
    assert v2 == 2
    cur = conn.execute("SELECT current_version FROM invoices WHERE invoice_id=?", (inv,))
    assert cur.fetchone()[0] == 2


def test_record_version_does_not_move_current_version_when_paid(conn, sid):
    inv = upsert_invoice(conn, "widgets inc.", "INV-1001", "h")
    ledger.record_version(conn, inv, inv_1001(), sid)
    ledger.set_invoice_status(conn, inv, InvoiceStatus.paid_mock)
    ledger.record_version(conn, inv, inv_1001().model_copy(update={"currency": "EUR"}), sid)
    row = conn.execute("SELECT current_version FROM invoices WHERE invoice_id=?", (inv,))
    assert row.fetchone()[0] == 1


def test_run_lifecycle_and_audit_order(conn, rid):
    update_run_status(conn, rid, RunStatus.extracted)
    for n in range(3):
        append_audit_event(conn, rid, "s", f"e{n}", {"n": n})
    finish_run(conn, rid, RunStatus.failed, "boom", "it broke")
    assert [e["event"] for e in list_audit_events(conn, rid)] == ["e0", "e1", "e2"]
    assert ledger.get_run_status(conn, rid) == RunStatus.failed
    row = conn.execute("SELECT finished_at, error_code FROM runs WHERE run_id=?", (rid,))
    finished_at, code = tuple(row.fetchone())
    assert finished_at and code == "boom"


def test_finish_run_rejects_non_terminal(conn, rid):
    update_run_status(conn, rid, RunStatus.extracted)
    with pytest.raises(IllegalTransition):
        finish_run(conn, rid, RunStatus.validated)


def test_finish_run_same_status_finalizes(conn, rid):
    for s in (RunStatus.extracted, RunStatus.validated, RunStatus.approval_pending):
        update_run_status(conn, rid, s)
    update_run_status(conn, rid, RunStatus.rejected)
    finish_run(conn, rid, RunStatus.rejected, prior_run_id=None)
    row = conn.execute("SELECT status, finished_at FROM runs WHERE run_id=?", (rid,)).fetchone()
    assert row["status"] == "rejected" and row["finished_at"]


def test_finish_run_different_terminal_status_raises(conn, rid):
    finish_run(conn, rid, RunStatus.failed, "x")
    with pytest.raises(IllegalTransition):
        finish_run(conn, rid, RunStatus.rejected)


def test_update_run_status_rejects_illegal(conn, rid):
    with pytest.raises(IllegalTransition):
        update_run_status(conn, rid, RunStatus.paid_mock)


def test_audit_payload_redacts_secret_keys(conn, rid):
    append_audit_event(conn, rid, "x", "y", {"api_key": "sk-1", "ok": 1})
    assert list_audit_events(conn, rid)[0]["payload"] == {"ok": 1}


def test_audit_payload_redacts_nested_keys(conn, rid):
    append_audit_event(conn, rid, "x", "y", {"headers": {"authorization": "x"}, "ok": 1})
    assert list_audit_events(conn, rid)[0]["payload"] == {"headers": {}, "ok": 1}


def test_redact_recurses_into_lists():
    out = ledger.redact({"items": [{"token": "t", "n": 1}, 5]})
    assert out == {"items": [{"n": 1}, 5]}


@pytest.mark.parametrize(
    "key",
    [
        "api_key",
        "API_KEY",
        "auth_token",
        "token",
        "secret",
        "client_secret",
        "password",
        "authorization",
        "xai_api_key",
        "x-api-key",
        "api-key",
        "auth-token",
        "access_key",
        "private_key",
        "cookie",
        "bearer",
        "apiKey",
        "accessToken",
        "authToken",
    ],
)
def test_redacted_key_matches_credentials(key):
    assert ledger.REDACTED_KEY.search(key)


@pytest.mark.parametrize(
    "key",
    [
        "vendor_key",
        "invoice_number_key",
        "source_hash",
        "receipt_id",
        "keyboard",
        "input_tokens",
        "prompt_tokens",
        "total_tokens",
    ],
)
def test_redacted_key_keeps_business_fields(key):
    assert not ledger.REDACTED_KEY.search(key)


def test_find_prior_outcome_skips_failed_runs(conn, sid):
    r1 = start_run(conn, ExecutionMode.offline, sid, EVAL)
    finish_run(conn, r1, RunStatus.failed, "x")
    assert ledger.find_prior_outcome(conn, "hash-1") is None
    r2 = start_run(conn, ExecutionMode.offline, sid, EVAL)
    inv = upsert_invoice(conn, "widgets inc.", "INV-1001", "hash-1")
    ledger.attach_run(conn, r2, inv, None)
    for s in (
        RunStatus.extracted,
        RunStatus.validated,
        RunStatus.approval_pending,
        RunStatus.approved,
        RunStatus.paid_mock,
    ):
        update_run_status(conn, r2, s)
    prior = ledger.find_prior_outcome(conn, "hash-1")
    assert prior is not None
    assert (prior.run_id, prior.status, prior.invoice_id) == (r2, RunStatus.paid_mock, inv)
    assert prior.receipt is None


def test_find_prior_outcome_returns_receipt(conn, sid):
    r = start_run(conn, ExecutionMode.offline, sid, EVAL)
    inv = upsert_invoice(conn, "widgets inc.", "INV-1001", "hash-1")
    _, v = ledger.record_version(conn, inv, inv_1001(), sid)
    ledger.attach_run(conn, r, inv, None)
    with storage.write_transaction(conn):
        conn.execute(
            "INSERT INTO payments VALUES ('pay-1', ?, ?, ?, '5000.00', 'USD', 'rcpt-1', "
            "'paid_mock', '2026-01-01T00:00:00Z')",
            (inv, v, r),
        )
    for s in (
        RunStatus.extracted,
        RunStatus.validated,
        RunStatus.approval_pending,
        RunStatus.approved,
        RunStatus.paid_mock,
    ):
        update_run_status(conn, r, s)
    prior = ledger.find_prior_outcome(conn, "hash-1")
    assert prior.receipt.receipt_id == "rcpt-1"
    assert prior.receipt.amount == Decimal("5000.00")


def test_mark_interrupted_runs(conn, rid):
    update_run_status(conn, rid, RunStatus.extracted)
    update_run_status(conn, rid, RunStatus.validated)
    assert ledger.mark_interrupted_runs(conn, "0000") == []
    assert ledger.mark_interrupted_runs(conn, "9999") == [rid]
    row = conn.execute("SELECT status, error_code FROM runs WHERE run_id=?", (rid,)).fetchone()
    assert tuple(row) == ("failed", "interrupted")


def test_set_invoice_status_never_leaves_paid_mock(conn):
    inv = upsert_invoice(conn, "v", "n", "h")
    ledger.set_invoice_status(conn, inv, InvoiceStatus.rejected)
    ledger.set_invoice_status(conn, inv, InvoiceStatus.paid_mock)
    ledger.set_invoice_status(conn, inv, InvoiceStatus.failed)
    row = conn.execute("SELECT status FROM invoices WHERE invoice_id=?", (inv,)).fetchone()
    assert row[0] == "paid_mock"


def test_get_human_review_latest_matching(conn, sid):
    inv = upsert_invoice(conn, "widgets inc.", "INV-1001", "h")
    ledger.record_version(conn, inv, inv_1001(), sid)
    with storage.write_transaction(conn):
        for action, reviewer in (("decline", "a"), ("approve", "b")):
            conn.execute(
                "INSERT INTO human_reviews (invoice_id, version, action, reviewer, reason, "
                "policy_version, created_at) VALUES (?, 1, ?, ?, 'r', 'p1', 't')",
                (inv, action, reviewer),
            )
    review = ledger.get_human_review(conn, inv, 1, "p1")
    assert review is not None and review.reviewer == "b"
    assert ledger.get_human_review(conn, inv, 1, "p2") is None


def test_findings_and_decision_roundtrip(conn, rid):
    from invoice_processing.codes import (
        FindingCode,
        GateOutcome,
        Recommendation,
        Severity,
    )
    from invoice_processing.schemas import ApprovalDecision, ValidationFinding

    ledger.record_findings(
        conn, rid, None, [ValidationFinding(code=FindingCode.zero_stock, severity=Severity.blocker)]
    )
    decision = ApprovalDecision(
        initial_recommendation=Recommendation.reject,
        final_decision=GateOutcome.rejected,
        policy_version="p1",
        mode=ExecutionMode.offline,
    )
    ledger.record_decision(conn, rid, None, decision)
    assert conn.execute("SELECT code FROM findings").fetchone()[0] == "zero_stock"
    assert conn.execute("SELECT final_decision FROM decisions").fetchone()[0] == "rejected"
