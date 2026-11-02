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
        "clientSecret",
        "sessionToken",
        "xai_api_key",
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
        "inputTokens",
        "tokenizer",
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


def test_finish_run_twice_raises_and_keeps_first_finalization(conn, rid):
    finish_run(conn, rid, RunStatus.failed, "first")
    before = conn.execute("SELECT * FROM runs WHERE run_id=?", (rid,)).fetchone()
    with pytest.raises(IllegalTransition):
        finish_run(conn, rid, RunStatus.failed, "second")
    after = conn.execute("SELECT * FROM runs WHERE run_id=?", (rid,)).fetchone()
    assert tuple(before) == tuple(after)


_PATH_TO = {
    RunStatus.failed: [],
    RunStatus.duplicate: [],
    RunStatus.rejected: [RunStatus.extracted, RunStatus.validated, RunStatus.approval_pending],
    RunStatus.needs_review: [
        RunStatus.extracted,
        RunStatus.validated,
        RunStatus.approval_pending,
    ],
    RunStatus.paid_mock: [
        RunStatus.extracted,
        RunStatus.validated,
        RunStatus.approval_pending,
        RunStatus.approved,
    ],
}


def finished_run(conn, sid, invoice_id, version_id, status, retry_of=None):
    r = start_run(conn, ExecutionMode.offline, sid, EVAL)
    ledger.attach_run(conn, r, invoice_id, version_id)
    if retry_of is not None:
        with storage.write_transaction(conn):
            conn.execute("UPDATE runs SET retry_of = ? WHERE run_id = ?", (retry_of, r))
    for s in _PATH_TO[status]:
        update_run_status(conn, r, s)
    finish_run(conn, r, status)
    return r


def add_payment(conn, invoice_id, version, run_id, receipt_id="rcpt-1"):
    with storage.write_transaction(conn):
        conn.execute(
            "INSERT INTO payments VALUES (?, ?, ?, ?, '5000.00', 'USD', ?, 'success', "
            "'2026-01-01T00:00:00Z')",
            (f"pay-{receipt_id}", invoice_id, version, run_id, receipt_id),
        )


@pytest.fixture
def two_versions(conn, sid):
    inv = upsert_invoice(conn, "widgets inc.", "1001", "hash-1")
    v1, _ = ledger.record_version(conn, inv, inv_1001(), sid)
    changed = inv_1001().model_copy(update={"currency": "EUR"})
    v2, _ = ledger.record_version(conn, inv, changed, sid)
    return inv, v1, v2


def current(conn, sid, inv, version_id, retry_of=None):
    r = start_run(conn, ExecutionMode.offline, sid, EVAL)
    ledger.attach_run(conn, r, inv, version_id)
    if retry_of is not None:
        with storage.write_transaction(conn):
            conn.execute("UPDATE runs SET retry_of = ? WHERE run_id = ?", (retry_of, r))
    return r


def test_check_identity_new_without_prior_runs(conn, sid, two_versions):
    inv, v1, _ = two_versions
    check = ledger.check_identity(conn, inv, v1, current(conn, sid, inv, v1))
    assert check == ledger.IdentityCheck(kind="new", prior=None)


def test_check_identity_duplicate_of_paid_same_version(conn, sid, two_versions):
    inv, v1, _ = two_versions
    paid = finished_run(conn, sid, inv, v1, RunStatus.paid_mock)
    add_payment(conn, inv, 1, paid)
    check = ledger.check_identity(conn, inv, v1, current(conn, sid, inv, v1))
    assert check.kind == "duplicate"
    assert check.prior.run_id == paid and check.prior.status is RunStatus.paid_mock
    assert check.prior.receipt.receipt_id == "rcpt-1"


def test_check_identity_revision_after_payment(conn, sid, two_versions):
    inv, v1, v2 = two_versions
    paid = finished_run(conn, sid, inv, v1, RunStatus.paid_mock)
    add_payment(conn, inv, 1, paid)
    check = ledger.check_identity(conn, inv, v2, current(conn, sid, inv, v2))
    assert check.kind == "revision_after_payment" and check.prior.run_id == paid


def test_check_identity_duplicate_of_unpaid_outcome(conn, sid, two_versions):
    inv, v1, _ = two_versions
    rejected = finished_run(conn, sid, inv, v1, RunStatus.rejected)
    check = ledger.check_identity(conn, inv, v1, current(conn, sid, inv, v1))
    assert check.kind == "duplicate"
    assert check.prior.run_id == rejected and check.prior.receipt is None


def test_check_identity_duplicate_picks_latest_outcome(conn, sid, two_versions):
    inv, v1, _ = two_versions
    finished_run(conn, sid, inv, v1, RunStatus.rejected)
    later = finished_run(conn, sid, inv, v1, RunStatus.needs_review)
    check = ledger.check_identity(conn, inv, v1, current(conn, sid, inv, v1))
    assert check.kind == "duplicate" and check.prior.run_id == later


def test_check_identity_version_conflict(conn, sid, two_versions):
    inv, v1, v2 = two_versions
    rejected = finished_run(conn, sid, inv, v1, RunStatus.rejected)
    check = ledger.check_identity(conn, inv, v2, current(conn, sid, inv, v2))
    assert check.kind == "version_conflict" and check.prior.run_id == rejected


def test_check_identity_ignores_failed_duplicate_and_retry_runs(conn, sid, two_versions):
    inv, v1, v2 = two_versions
    finished_run(conn, sid, inv, v1, RunStatus.failed)
    finished_run(conn, sid, inv, v1, RunStatus.duplicate)
    original = finished_run(conn, sid, inv, v2, RunStatus.failed)
    finished_run(conn, sid, inv, v1, RunStatus.rejected, retry_of=original)
    assert ledger.check_identity(conn, inv, v1, current(conn, sid, inv, v1)).kind == "new"
    assert ledger.check_identity(conn, inv, v2, current(conn, sid, inv, v2)).kind == "new"


def test_check_identity_retry_of_paid_same_version_is_duplicate(conn, sid, two_versions):
    # another run paid and did not fail: the retry must not re-decide a paid identity
    inv, v1, _ = two_versions
    paid = finished_run(conn, sid, inv, v1, RunStatus.paid_mock)
    add_payment(conn, inv, 1, paid)
    original = finished_run(conn, sid, inv, v1, RunStatus.failed)
    retry = current(conn, sid, inv, v1, retry_of=original)
    check = ledger.check_identity(conn, inv, v1, retry)
    assert check.kind == "duplicate" and check.prior.run_id == paid


def test_check_identity_retry_of_failed_payer_is_new(conn, sid, two_versions):
    # the payer paid, then crashed: the retry replays pay(), which returns the receipt
    inv, v1, _ = two_versions
    original = finished_run(conn, sid, inv, v1, RunStatus.failed)
    add_payment(conn, inv, 1, original)
    retry = current(conn, sid, inv, v1, retry_of=original)
    assert ledger.check_identity(conn, inv, v1, retry).kind == "new"


def test_check_identity_retry_still_sees_revision_after_payment(conn, sid, two_versions):
    inv, v1, v2 = two_versions
    paid = finished_run(conn, sid, inv, v1, RunStatus.paid_mock)
    add_payment(conn, inv, 1, paid)
    original = finished_run(conn, sid, inv, v2, RunStatus.failed)
    retry = current(conn, sid, inv, v2, retry_of=original)
    check = ledger.check_identity(conn, inv, v2, retry)
    assert check.kind == "revision_after_payment" and check.prior.run_id == paid


def test_check_identity_retry_never_duplicate_of_unpaid_same_version(conn, sid, two_versions):
    inv, v1, _ = two_versions
    finished_run(conn, sid, inv, v1, RunStatus.rejected)
    original = finished_run(conn, sid, inv, v1, RunStatus.failed)
    retry = current(conn, sid, inv, v1, retry_of=original)
    assert ledger.check_identity(conn, inv, v1, retry).kind == "new"


def test_check_identity_retry_sees_version_conflict(conn, sid, two_versions):
    inv, v1, v2 = two_versions
    rejected = finished_run(conn, sid, inv, v1, RunStatus.rejected)
    original = finished_run(conn, sid, inv, v2, RunStatus.failed)
    retry = current(conn, sid, inv, v2, retry_of=original)
    check = ledger.check_identity(conn, inv, v2, retry)
    assert check.kind == "version_conflict" and check.prior.run_id == rejected


def test_check_identity_retry_excludes_its_own_retry_chain(conn, sid, two_versions):
    # An original whose outcome would otherwise conflict (forced here: retries require a
    # failed original in practice) and a sibling retry are both excluded.
    inv, v1, v2 = two_versions
    original = finished_run(conn, sid, inv, v1, RunStatus.rejected)
    sibling = finished_run(conn, sid, inv, v1, RunStatus.needs_review, retry_of=original)
    retry = current(conn, sid, inv, v2, retry_of=sibling)
    assert ledger.check_identity(conn, inv, v2, retry).kind == "new"
    # the same history is a conflict for an unrelated run
    assert ledger.check_identity(conn, inv, v2, current(conn, sid, inv, v2)).kind == (
        "version_conflict"
    )


def test_start_run_records_retry_and_mode_switch_links(conn, sid):
    original = start_run(conn, ExecutionMode.live, sid, EVAL)
    retry = start_run(conn, ExecutionMode.live, sid, EVAL, retry_of=original)
    switch = start_run(conn, ExecutionMode.offline, sid, EVAL, mode_switch_of=retry)
    row = conn.execute(
        "SELECT retry_of, mode_switch_of FROM runs WHERE run_id = ?", (retry,)
    ).fetchone()
    assert tuple(row) == (original, None)
    row = conn.execute(
        "SELECT retry_of, mode_switch_of FROM runs WHERE run_id = ?", (switch,)
    ).fetchone()
    assert tuple(row) == (None, retry)
    # only the latest run of the source counts: it is offline now
    assert ledger.latest_run_in_other_mode(conn, sid, ExecutionMode.offline) is None
    assert ledger.latest_run_in_other_mode(conn, sid, ExecutionMode.live) == switch


def test_check_identity_provisional_identity_is_always_new(conn, sid):
    inv = upsert_invoice(conn, None, None, "hash-1")
    v1, _ = ledger.record_version(conn, inv, inv_1001(), sid)
    finished_run(conn, sid, inv, v1, RunStatus.rejected)
    assert ledger.check_identity(conn, inv, v1, current(conn, sid, inv, v1)).kind == "new"


def test_check_identity_same_version_payment_by_interrupted_run_is_new(conn, sid, two_versions):
    # A run that paid and then crashed is marked failed; the replay goes back through pay(),
    # which returns the existing receipt, so the invoice ends paid_mock instead of stuck.
    inv, v1, v2 = two_versions
    crashed = finished_run(conn, sid, inv, v1, RunStatus.failed)
    add_payment(conn, inv, 1, crashed)
    assert ledger.check_identity(conn, inv, v1, current(conn, sid, inv, v1)).kind == "new"
    revision = ledger.check_identity(conn, inv, v2, current(conn, sid, inv, v2))
    assert revision.kind == "revision_after_payment" and revision.prior.run_id == crashed


def test_check_identity_failed_payer_beats_earlier_same_version_outcome(conn, sid, two_versions):
    # A non-paying outcome on the paid version must not turn the replay into a duplicate
    # carrying the receipt; the replay goes back through pay() instead.
    inv, v1, _ = two_versions
    finished_run(conn, sid, inv, v1, RunStatus.needs_review)
    crashed = finished_run(conn, sid, inv, v1, RunStatus.failed)
    add_payment(conn, inv, 1, crashed)
    assert ledger.check_identity(conn, inv, v1, current(conn, sid, inv, v1)).kind == "new"


def test_check_identity_failed_payer_beats_other_version_outcome(conn, sid, two_versions):
    inv, v1, v2 = two_versions
    crashed = finished_run(conn, sid, inv, v1, RunStatus.failed)
    add_payment(conn, inv, 1, crashed)
    finished_run(conn, sid, inv, v2, RunStatus.needs_review)
    assert ledger.check_identity(conn, inv, v1, current(conn, sid, inv, v1)).kind == "new"


def test_check_identity_payment_beats_later_outcome_on_revision(conn, sid, two_versions):
    inv, v1, v2 = two_versions
    paid = finished_run(conn, sid, inv, v1, RunStatus.paid_mock)
    add_payment(conn, inv, 1, paid)
    finished_run(conn, sid, inv, v2, RunStatus.needs_review)
    check = ledger.check_identity(conn, inv, v2, current(conn, sid, inv, v2))
    assert check.kind == "revision_after_payment" and check.prior.run_id == paid
    assert check.prior.receipt.receipt_id == "rcpt-1"


def test_find_prior_outcome_receipt_only_for_paying_run(conn, sid, two_versions):
    # An exact replay of a non-paying run never reports the invoice's receipt as its own.
    inv, v1, v2 = two_versions
    paid = finished_run(conn, sid, inv, v1, RunStatus.paid_mock)
    add_payment(conn, inv, 1, paid)
    other = ledger.record_source(conn, make_source(2))[0]
    review = finished_run(conn, other, inv, v2, RunStatus.needs_review)
    prior = ledger.find_prior_outcome(conn, "hash-2")
    assert prior.run_id == review and prior.receipt is None
    assert ledger.find_prior_outcome(conn, "hash-1").receipt.receipt_id == "rcpt-1"


def test_find_prior_outcome_ignores_retry_and_duplicate_runs(conn, sid):
    original = start_run(conn, ExecutionMode.offline, sid, EVAL)
    finish_run(conn, original, RunStatus.failed, "x")
    retry = start_run(conn, ExecutionMode.offline, sid, EVAL)
    with storage.write_transaction(conn):
        conn.execute("UPDATE runs SET retry_of = ? WHERE run_id = ?", (original, retry))
    for s in _PATH_TO[RunStatus.rejected]:
        update_run_status(conn, retry, s)
    finish_run(conn, retry, RunStatus.rejected)
    dup = start_run(conn, ExecutionMode.offline, sid, EVAL)
    finish_run(conn, dup, RunStatus.duplicate)
    assert ledger.find_prior_outcome(conn, "hash-1") is None


def test_find_prior_outcome_returns_latest_of_several(conn, sid):
    inv = upsert_invoice(conn, "widgets inc.", "1001", "hash-1")
    v1, _ = ledger.record_version(conn, inv, inv_1001(), sid)
    finished_run(conn, sid, inv, v1, RunStatus.rejected)
    later = finished_run(conn, sid, inv, v1, RunStatus.needs_review)
    prior = ledger.find_prior_outcome(conn, "hash-1")
    assert prior.run_id == later and prior.status is RunStatus.needs_review


def test_mark_interrupted_runs_leaves_terminal_runs(conn, sid):
    done = start_run(conn, ExecutionMode.offline, sid, EVAL)
    for s in _PATH_TO[RunStatus.rejected]:
        update_run_status(conn, done, s)
    finish_run(conn, done, RunStatus.rejected)
    assert ledger.mark_interrupted_runs(conn, "9999") == []
    row = conn.execute("SELECT status, error_code FROM runs WHERE run_id=?", (done,)).fetchone()
    assert tuple(row) == ("rejected", None)


def test_1011_txt_and_pdf_share_semantic_hash(conn):
    from pathlib import Path

    from invoice_processing import intake, seed
    from invoice_processing.limits import DEFAULT_LIMITS
    from invoice_processing.normalize import normalize
    from invoice_processing.parsers import parse_document

    seed.seed_inventory(conn)

    def digest(name):
        source, raw = intake.read_source(Path("data/invoices") / name)
        draft = parse_document(source, raw, DEFAULT_LIMITS).draft
        return semantic_hash(normalize(draft, storage.inventory_items(conn))[0])

    assert digest("invoice_1011.txt") == digest("invoice_1011.pdf")


# --- Phase 4: version ledger and review records -------------------------------------------


def versions(conn, inv):
    return [
        tuple(r)
        for r in conn.execute(
            "SELECT version, parent_version, origin, version_status FROM invoice_versions "
            "WHERE invoice_id = ? ORDER BY version",
            (inv,),
        )
    ]


def current_version(conn, inv):
    row = conn.execute("SELECT current_version FROM invoices WHERE invoice_id = ?", (inv,))
    return row.fetchone()[0]


def test_record_version_origin_defaults_to_source(conn, sid):
    inv = upsert_invoice(conn, "widgets inc.", "INV-1001", "h")
    ledger.record_version(conn, inv, inv_1001(), sid)
    assert versions(conn, inv) == [(1, None, "source", "current")]


def test_correction_versions_increment_and_link_parent(conn, sid):
    inv = upsert_invoice(conn, "widgets inc.", "INV-1001", "h")
    ledger.record_version(conn, inv, inv_1001(), sid)
    fixed = inv_1001().model_copy(update={"currency": "EUR"})
    v2_id, v2 = ledger.record_correction_version(conn, inv, fixed, sid, base_version=1)
    _, v3 = ledger.record_correction_version(conn, inv, inv_1001(), sid, base_version=2)
    assert (v2, v3) == (2, 3)
    assert versions(conn, inv) == [
        (1, None, "source", "superseded"),
        (2, 1, "correction", "superseded"),
        (3, 2, "correction", "current"),
    ]
    assert current_version(conn, inv) == 3
    assert ledger.get_version(conn, inv, 2).version_id == v2_id


def test_correction_version_inserted_even_with_equal_semantic_hash(conn, sid):
    inv = upsert_invoice(conn, "widgets inc.", "INV-1001", "h")
    v1_id, _ = ledger.record_version(conn, inv, inv_1001(), sid)
    # invoice_date is not in the semantic hash, so this correction hashes like version 1
    dated = inv_1001().model_copy(update={"invoice_date": date(2026, 1, 2)})
    assert semantic_hash(dated) == semantic_hash(inv_1001())
    v2_id, v2 = ledger.record_correction_version(conn, inv, dated, sid, base_version=1)
    assert v2 == 2 and v2_id != v1_id
    assert ledger.get_version(conn, inv, 2).invoice.invoice_date == date(2026, 1, 2)
    # a later plain upload of the same content still takes the first match
    assert ledger.record_version(conn, inv, inv_1001(), sid) == (v1_id, 1)


def test_record_version_hash_match_returns_first_payload_and_keeps_current(conn, sid):
    other = ledger.record_source(conn, make_source(2))[0]
    inv = upsert_invoice(conn, "widgets inc.", "INV-1001", "h")
    v1_id, _ = ledger.record_version(conn, inv, inv_1001(), sid)
    ledger.record_version(conn, inv, inv_1001().model_copy(update={"currency": "EUR"}), sid)
    assert current_version(conn, inv) == 2
    again = inv_1001().model_copy(update={"source_id": other, "notes": "resent"})
    assert ledger.record_version(conn, inv, again, other) == (v1_id, 1)
    assert current_version(conn, inv) == 2  # a repeat of an older version does not move it
    first = ledger.get_version(conn, inv, 1)
    assert first.source_id == sid and first.invoice == inv_1001()
    assert versions(conn, inv) == [(1, None, "source", "current"), (2, 1, "source", "current")]


def test_record_version_supersede_marks_others(conn, sid):
    inv = upsert_invoice(conn, "widgets inc.", "INV-1001", "h")
    ledger.record_version(conn, inv, inv_1001(), sid)
    ledger.record_version(conn, inv, inv_1001().model_copy(update={"currency": "EUR"}), sid)
    corrected = inv_1001().model_copy(update={"currency": "GBP"})
    _, v3 = ledger.record_version(conn, inv, corrected, sid, supersede=True)
    assert v3 == 3 and current_version(conn, inv) == 3
    assert [v[3] for v in versions(conn, inv)] == ["superseded", "superseded", "current"]


def test_record_version_supersede_on_hash_match_changes_nothing(conn, sid):
    inv = upsert_invoice(conn, "widgets inc.", "INV-1001", "h")
    v1 = ledger.record_version(conn, inv, inv_1001(), sid)
    assert ledger.record_version(conn, inv, inv_1001(), sid, supersede=True) == v1
    assert versions(conn, inv) == [(1, None, "source", "current")]


def test_get_invoice_and_get_version(conn, sid):
    inv = upsert_invoice(conn, "widgets inc.", "INV-1001", "h")
    v1_id, _ = ledger.record_version(conn, inv, inv_1001(), sid)
    row = ledger.get_invoice(conn, inv)
    assert row == ledger.InvoiceRow(inv, "widgets inc.", "INV-1001", InvoiceStatus.processing, 1)
    version = ledger.get_version(conn, inv, 1)
    assert (version.version_id, version.version, version.parent_version) == (v1_id, 1, None)
    assert (version.origin, version.version_status, version.source_id) == (
        "source",
        "current",
        sid,
    )
    with pytest.raises(KeyError):
        ledger.get_invoice(conn, "inv-nope")
    with pytest.raises(KeyError):
        ledger.get_version(conn, inv, 2)


def test_get_source_roundtrip(conn, sid):
    assert ledger.get_source(conn, sid) == make_source()
    with pytest.raises(KeyError):
        ledger.get_source(conn, "src-nope")


def test_start_run_records_trigger_and_review_of(conn, sid):
    base = start_run(conn, ExecutionMode.offline, sid, EVAL)
    review = start_run(conn, ExecutionMode.offline, sid, EVAL, trigger="correction", review_of=base)
    rows = conn.execute("SELECT run_id, trigger, review_of FROM runs ORDER BY rowid").fetchall()
    assert [tuple(r) for r in rows] == [(base, "submission", None), (review, "correction", base)]


def test_latest_outcome_run_and_get_decision(conn, sid, two_versions):
    from invoice_processing.codes import GateOutcome, Recommendation
    from invoice_processing.schemas import ApprovalDecision

    inv, v1, v2 = two_versions
    assert ledger.latest_outcome_run(conn, v1) is None
    finished_run(conn, sid, inv, v1, RunStatus.rejected)
    later = finished_run(conn, sid, inv, v1, RunStatus.needs_review)
    finished_run(conn, sid, inv, v1, RunStatus.failed)
    finished_run(conn, sid, inv, v2, RunStatus.rejected)
    run = ledger.latest_outcome_run(conn, v1)
    assert run == ledger.RunRow(
        later, RunStatus.needs_review, ExecutionMode.offline, EVAL, "submission", None
    )
    assert ledger.get_decision(conn, later) is None
    decision = ApprovalDecision(
        initial_recommendation=Recommendation.review,
        final_decision=GateOutcome.needs_review,
        policy_version="p1",
        mode=ExecutionMode.offline,
    )
    ledger.record_decision(conn, later, v1, decision)
    assert ledger.get_decision(conn, later) == decision


def test_record_correction_and_human_review(conn, sid, rid):
    from datetime import UTC, datetime

    from invoice_processing.codes import HumanReviewAction
    from invoice_processing.schemas import Correction, HumanReview

    inv = upsert_invoice(conn, "widgets inc.", "INV-1001", "h")
    ledger.record_version(conn, inv, inv_1001(), sid)
    ledger.record_correction_version(conn, inv, inv_1001(), sid, base_version=1)
    at = datetime(2026, 1, 31, 12, tzinfo=UTC)
    correction = Correction(
        invoice_id=inv,
        base_version=1,
        field="stated.total",
        old_value=None,
        new_value="5000.00",
        evidence_location="line:9",
        reviewer="Ana",
        reason="Total was blank",
        created_at=at,
        resulting_version=2,
    )
    cid = ledger.record_correction(conn, correction, rid)
    row = conn.execute("SELECT * FROM corrections WHERE correction_id = ?", (cid,)).fetchone()
    assert (row["from_version"], row["to_version"], row["run_id"], row["old_value"]) == (
        1,
        2,
        rid,
        None,
    )
    assert datetime.fromisoformat(row["created_at"]) == at
    review = HumanReview(
        invoice_id=inv,
        version=2,
        action=HumanReviewAction.decline,
        reviewer="Ana",
        reason="Vendor unknown",
        policy_version="p1",
    )
    hid = ledger.record_human_review(conn, review, rid)
    row = conn.execute("SELECT * FROM human_reviews WHERE review_id = ?", (hid,)).fetchone()
    assert (row["version"], row["action"], row["run_id"]) == (2, "decline", rid)
    assert row["created_at"]  # filled in when the review carries none
    assert ledger.get_human_review(conn, inv, 2, "p1").action is HumanReviewAction.decline


def test_carried_findings_only_ingestion_codes_and_excludes_fields(conn, rid):
    from invoice_processing.codes import FindingCode, Severity
    from invoice_processing.schemas import ValidationFinding

    def f(code, field=None):
        return ValidationFinding(code=code, severity=Severity.review, field=field)

    ledger.record_findings(
        conn,
        rid,
        None,
        [
            f(FindingCode.ambiguous_date, "due_date"),  # ingestion
            f(FindingCode.unparseable_value, "stated.total"),  # ingestion, corrected below
            f(FindingCode.risk_signal_urgency),  # ingestion, no field
            f(FindingCode.total_mismatch, "stated.total"),  # validation
            f(FindingCode.zero_stock),  # validation
            f(FindingCode.non_usd_currency, "currency"),  # gate
            f(FindingCode.model_disagreement),  # gate
        ],
    )
    carried = ledger.carried_findings(conn, rid)
    assert [x.code for x in carried] == [
        FindingCode.ambiguous_date,
        FindingCode.unparseable_value,
        FindingCode.risk_signal_urgency,
    ]
    kept = ledger.carried_findings(conn, rid, exclude_fields=frozenset({"stated.total"}))
    assert [x.code for x in kept] == [FindingCode.ambiguous_date, FindingCode.risk_signal_urgency]


def test_audit_actor_recorded(conn, rid):
    append_audit_event(conn, rid, "review", "correction_recorded", {}, actor="Ana")
    append_audit_event(conn, rid, "x", "y", {})
    rows = conn.execute("SELECT actor FROM audit_events ORDER BY event_id").fetchall()
    assert [r[0] for r in rows] == ["Ana", None]
