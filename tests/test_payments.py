from datetime import UTC, date
from decimal import Decimal

import pytest

from invoice_processing import ledger, payments
from invoice_processing.codes import (
    DEFAULT_SEVERITY,
    ExecutionMode,
    FindingCode,
    GateOutcome,
    Recommendation,
)
from invoice_processing.policy import POLICY_VERSION
from invoice_processing.schemas import ApprovalDecision, SourceDocument, ValidationFinding
from tests.helpers import inv_1001


def approved_run(
    conn,
    total="5000.00",
    outcome="approved",
    currency="USD",
    decision_version_id=None,
    n=1,
):
    source = SourceDocument(
        source_id=f"src-{n}",
        content_hash=f"hash-{n}",
        original_name="f.txt",
        format="txt",
        size_bytes=10,
        parser_version="t1",
    )
    source_id, _ = ledger.record_source(conn, source)
    inv = inv_1001().model_copy(deep=True)
    inv.stated.total = Decimal(total)
    inv.currency = currency
    invoice_id = ledger.upsert_invoice(
        conn, inv.vendor_key, inv.invoice_number_key, source.content_hash
    )
    version_id, _ = ledger.record_version(conn, invoice_id, inv, source_id)
    run_id = ledger.start_run(conn, ExecutionMode.offline, source_id, date(2026, 2, 1))
    ledger.attach_run(conn, run_id, invoice_id, version_id)
    ledger.record_decision(
        conn,
        run_id,
        decision_version_id or version_id,
        ApprovalDecision(
            initial_recommendation=Recommendation.approve,
            final_decision=GateOutcome(outcome),
            policy_version=POLICY_VERSION,
            mode=ExecutionMode.offline,
        ),
    )
    return invoice_id, version_id, run_id


def add_review(conn, invoice_id, action="approve", version=1, policy_version=POLICY_VERSION):
    conn.execute(
        "INSERT INTO human_reviews (invoice_id, version, action, reviewer, reason, "
        "policy_version, created_at) VALUES (?, ?, ?, 'rev', 'ok', ?, ?)",
        (invoice_id, version, action, policy_version, ledger.utcnow()),
    )


def count_payments(conn):
    return conn.execute("SELECT COUNT(*) FROM payments").fetchone()[0]


@pytest.fixture
def calls(monkeypatch):
    recorded = []
    monkeypatch.setattr(
        payments,
        "mock_payment",
        lambda *a, **k: recorded.append((*a, k["idempotency_key"])) or {"status": "success"},
    )
    return recorded


def test_pay_twice_same_receipt_one_call(conn, calls):
    ids = approved_run(conn)
    first, second = payments.pay(conn, *ids), payments.pay(conn, *ids)
    assert first.created and not second.created
    assert first.receipt.receipt_id == second.receipt.receipt_id and len(calls) == 1
    assert first.receipt.amount == Decimal("5000.00")
    assert first.receipt.currency == "USD"
    assert first.receipt.paid_at.tzinfo is not None
    assert first.receipt.paid_at.utcoffset() == UTC.utcoffset(None)
    assert first.receipt.paid_at == second.receipt.paid_at
    assert first.payment_id == second.payment_id
    assert calls[0] == ("Widgets Inc.", Decimal("5000.00"), "USD", f"invoice:{ids[0]}")
    events = [
        e for e in ledger.list_audit_events(conn, ids[2]) if e["event"] == "payment_succeeded"
    ]
    assert len(events) == 1
    assert events[0]["payload"]["receipt_id"] == first.receipt.receipt_id


@pytest.mark.parametrize("outcome", ["rejected", "needs_review", "awaiting_human_approval"])
def test_non_approved_raises_no_payment(conn, calls, outcome):
    ids = approved_run(conn, outcome=outcome)
    with pytest.raises(payments.PaymentNotAuthorized) as exc:
        payments.pay(conn, *ids)
    assert exc.value.reason == "not_approved"
    assert count_payments(conn) == 0 and calls == []


def test_missing_decision_raises_not_approved(conn, calls):
    invoice_id, version_id, run_id = approved_run(conn)
    with pytest.raises(payments.PaymentNotAuthorized) as exc:
        payments.pay(conn, invoice_id, version_id, "run-nope")
    assert exc.value.reason == "not_approved"
    assert count_payments(conn) == 0 and calls == []


def test_decision_bound_to_other_version_raises_not_approved(conn, calls):
    invoice_id, version_id, run_id = approved_run(conn)
    ids = approved_run(conn, n=2, decision_version_id=version_id)
    # decision for run 2 is bound to run 1's version; paying run 2's own version must fail
    with pytest.raises(payments.PaymentNotAuthorized) as exc:
        payments.pay(conn, ids[0], ids[1], ids[2])
    assert exc.value.reason == "not_approved"
    assert count_payments(conn) == 0 and calls == []


def test_non_usd_raises_not_usd(conn, calls):
    ids = approved_run(conn, currency="EUR")
    with pytest.raises(payments.PaymentNotAuthorized) as exc:
        payments.pay(conn, *ids)
    assert exc.value.reason == "not_usd"
    assert count_payments(conn) == 0 and calls == []


def test_high_value_without_human_review_raises(conn, calls):
    ids = approved_run(conn, total="10000.01")
    with pytest.raises(payments.PaymentNotAuthorized) as exc:
        payments.pay(conn, *ids)
    assert exc.value.reason == "human_approval_required"
    assert count_payments(conn) == 0 and calls == []


def test_high_value_with_decline_review_raises(conn, calls):
    ids = approved_run(conn, total="10000.01")
    add_review(conn, ids[0], action="decline")
    with pytest.raises(payments.PaymentNotAuthorized) as exc:
        payments.pay(conn, *ids)
    assert exc.value.reason == "human_approval_required"
    assert count_payments(conn) == 0 and calls == []


def test_high_value_with_stale_policy_review_raises(conn, calls):
    ids = approved_run(conn, total="10000.01")
    add_review(conn, ids[0], policy_version="old")
    with pytest.raises(payments.PaymentNotAuthorized) as exc:
        payments.pay(conn, *ids)
    assert exc.value.reason == "human_approval_required"
    assert count_payments(conn) == 0


def test_high_value_with_matching_review_pays(conn, calls):
    ids = approved_run(conn, total="10000.01")
    add_review(conn, ids[0])
    result = payments.pay(conn, *ids)
    assert result.created and result.receipt.amount == Decimal("10000.01")
    assert len(calls) == 1 and count_payments(conn) == 1


def test_threshold_exact_pays_without_review(conn, calls):
    ids = approved_run(conn, total="10000.00")
    assert payments.pay(conn, *ids).created


def _disagreement(conn, run_id, version_id):
    ledger.record_findings(
        conn,
        run_id,
        version_id,
        [
            ValidationFinding(
                code=FindingCode.model_disagreement,
                severity=DEFAULT_SEVERITY[FindingCode.model_disagreement],
            )
        ],
    )


def test_model_disagreement_without_review_raises(conn, calls):
    invoice_id, version_id, run_id = approved_run(conn)
    _disagreement(conn, run_id, version_id)
    with pytest.raises(payments.PaymentNotAuthorized) as exc:
        payments.pay(conn, invoice_id, version_id, run_id)
    assert exc.value.reason == "human_approval_required"
    assert count_payments(conn) == 0 and calls == []


def test_model_disagreement_with_review_pays(conn, calls):
    invoice_id, version_id, run_id = approved_run(conn)
    _disagreement(conn, run_id, version_id)
    add_review(conn, invoice_id)
    assert payments.pay(conn, invoice_id, version_id, run_id).created


def test_mock_payment_failure_raises_and_leaves_nothing(conn, monkeypatch):
    monkeypatch.setattr(payments, "mock_payment", lambda *a, **k: {"status": "error"})
    ids = approved_run(conn)
    with pytest.raises(payments.PaymentNotAuthorized) as exc:
        payments.pay(conn, *ids)
    assert exc.value.reason == "mock_payment_failed"
    assert count_payments(conn) == 0
    assert not [
        e for e in ledger.list_audit_events(conn, ids[2]) if e["event"] == "payment_succeeded"
    ]


def test_failure_inside_transaction_leaves_nothing(conn, calls, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(payments.ledger, "append_audit_event", boom)
    ids = approved_run(conn)
    with pytest.raises(RuntimeError):
        payments.pay(conn, *ids)
    assert count_payments(conn) == 0
    assert not conn.in_transaction
    assert not [
        e for e in ledger.list_audit_events(conn, ids[2]) if e["event"] == "payment_succeeded"
    ]


def test_mock_payment_prints_to_stderr_only(capsys):
    assert payments.mock_payment("Widgets Inc.", Decimal("5000"), "USD", "invoice:inv-1") == {
        "status": "success"
    }
    out, err = capsys.readouterr()
    assert out == ""
    assert "Paying Widgets Inc." in err and "USD 5,000.00" in err
    assert "invoice:inv-1" in err


def test_record_rejection_never_pays(conn, calls):
    invoice_id, version_id, run_id = approved_run(conn, outcome="rejected")
    payments.record_rejection(conn, run_id, invoice_id, version_id, [FindingCode.non_usd_currency])
    events = [
        e for e in ledger.list_audit_events(conn, run_id) if e["event"] == "rejection_recorded"
    ]
    assert len(events) == 1 and events[0]["stage"] == "payment"
    assert events[0]["payload"] == {"codes": ["non_usd_currency"]}
    assert calls == [] and count_payments(conn) == 0


def test_idempotency_key_stable_across_rolled_back_attempt_and_retry(conn, calls, monkeypatch):
    ids = approved_run(conn)
    real = ledger.append_audit_event

    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(payments.ledger, "append_audit_event", boom)
    with pytest.raises(RuntimeError):
        payments.pay(conn, *ids)
    monkeypatch.setattr(payments.ledger, "append_audit_event", real)
    assert payments.pay(conn, *ids).created
    assert len(calls) == 2
    assert calls[0][3] == calls[1][3] == f"invoice:{ids[0]}"
    assert count_payments(conn) == 1


def test_amount_is_quantized_before_paying(conn, calls):
    ids = approved_run(conn, total="5000.004")
    result = payments.pay(conn, *ids)
    assert calls[0][1] == Decimal("5000.00")
    assert result.receipt.amount == Decimal("5000.00")
    assert conn.execute("SELECT amount FROM payments").fetchone()[0] == "5000.00"


def test_second_approved_run_same_invoice_returns_first_receipt(conn, calls):
    invoice_id, version_id, run_id = approved_run(conn)
    first = payments.pay(conn, invoice_id, version_id, run_id)
    source_id = conn.execute("SELECT source_id FROM runs WHERE run_id = ?", (run_id,)).fetchone()[0]
    run2 = ledger.start_run(conn, ExecutionMode.offline, source_id, date(2026, 2, 1))
    ledger.attach_run(conn, run2, invoice_id, version_id)
    ledger.record_decision(
        conn,
        run2,
        version_id,
        ApprovalDecision(
            initial_recommendation=Recommendation.approve,
            final_decision=GateOutcome.approved,
            policy_version=POLICY_VERSION,
            mode=ExecutionMode.offline,
        ),
    )
    second = payments.pay(conn, invoice_id, version_id, run2)
    assert not second.created
    assert second.receipt.receipt_id == first.receipt.receipt_id
    assert len(calls) == 1 and count_payments(conn) == 1


def test_pay_inside_open_transaction_raises(conn, calls):
    ids = approved_run(conn)
    conn.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(RuntimeError):
            payments.pay(conn, *ids)
    finally:
        conn.execute("ROLLBACK")
    assert calls == [] and count_payments(conn) == 0
