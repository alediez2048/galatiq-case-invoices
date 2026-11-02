"""Guarded, idempotent mock payment (P1-05).

`pay` is the only caller of `mock_payment`. It rereads persisted state inside one write
transaction and never trusts in-memory graph state, so it cannot pay a non-approved,
non-USD or unapproved high-value invoice, and cannot pay the same invoice twice.
"""

import sqlite3
import sys
import uuid
from datetime import datetime
from decimal import Decimal

from invoice_processing import ledger, storage
from invoice_processing.codes import FindingCode, GateOutcome, HumanReviewAction
from invoice_processing.money import canonical_amount, format_money
from invoice_processing.policy import HIGH_VALUE_THRESHOLD_USD, POLICY_VERSION
from invoice_processing.schemas import MockReceipt, NormalizedInvoice, PaymentResult


class PaymentNotAuthorized(RuntimeError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def mock_payment(
    vendor: str, amount: Decimal, currency: str, idempotency_key: str
) -> dict[str, str]:
    # stderr keeps stdout JSON-only.
    print(
        f"Paying {vendor} {format_money(amount, currency)} (idempotency_key={idempotency_key})",
        file=sys.stderr,
    )
    return {"status": "success"}


def _result(row: sqlite3.Row, created: bool) -> PaymentResult:
    return PaymentResult(
        payment_id=row["payment_id"],
        receipt=MockReceipt(
            receipt_id=row["receipt_id"],
            amount=Decimal(row["amount"]),
            currency=row["currency"],
            paid_at=datetime.fromisoformat(row["created_at"]),
        ),
        created=created,
    )


def pay(conn: sqlite3.Connection, invoice_id: str, version_id: str, run_id: str) -> PaymentResult:
    """Pay an approved invoice once.

    mock_payment runs inside the write transaction; a crash between it and COMMIT rolls back
    the record, and a replay calls mock_payment again with the same idempotency_key - a real
    gateway must dedupe on it.
    """
    with storage.write_transaction(conn):
        existing = conn.execute(
            "SELECT p.payment_id, p.receipt_id, p.amount, p.currency, p.created_at, "
            "p.version = v.version AS same_version FROM payments p "
            "LEFT JOIN invoice_versions v ON v.version_id = ? AND v.invoice_id = p.invoice_id "
            "WHERE p.invoice_id = ?",
            (version_id, invoice_id),
        ).fetchone()
        if existing is not None:
            # One payment per invoice identity: only a replay of the paid version gets the
            # receipt back; any other version is a revision and is never paid.
            if not existing["same_version"]:
                raise PaymentNotAuthorized("revision_after_payment")
            return _result(existing, created=False)

        decision = conn.execute(
            "SELECT final_decision, version_id FROM decisions WHERE run_id = ?", (run_id,)
        ).fetchone()
        if (
            decision is None
            or decision["final_decision"] != GateOutcome.approved.value
            or decision["version_id"] != version_id
        ):
            raise PaymentNotAuthorized("not_approved")

        row = conn.execute(
            "SELECT version, payload_json FROM invoice_versions "
            "WHERE version_id = ? AND invoice_id = ?",
            (version_id, invoice_id),
        ).fetchone()
        if row is None:
            raise PaymentNotAuthorized("not_approved")
        invoice = NormalizedInvoice.model_validate_json(row["payload_json"])
        if invoice.currency != "USD":
            raise PaymentNotAuthorized("not_usd")
        total = invoice.stated.total
        if total is None:
            raise PaymentNotAuthorized("no_total")

        disagreement = conn.execute(
            "SELECT 1 FROM findings WHERE run_id = ? AND code = ? LIMIT 1",
            (run_id, FindingCode.model_disagreement.value),
        ).fetchone()
        if total > HIGH_VALUE_THRESHOLD_USD or disagreement is not None:
            review = ledger.get_human_review(conn, invoice_id, row["version"], POLICY_VERSION)
            if review is None or review.action != HumanReviewAction.approve:
                raise PaymentNotAuthorized("human_approval_required")

        amount = canonical_amount(total, "USD")
        vendor = invoice.vendor_name or ""
        result = mock_payment(
            vendor, Decimal(amount), "USD", idempotency_key=f"invoice:{invoice_id}"
        )
        if result.get("status") != "success":
            raise PaymentNotAuthorized("mock_payment_failed")

        payment_id = "pay-" + uuid.uuid4().hex
        receipt_id = "rcpt-" + uuid.uuid4().hex[:12]
        now = ledger.utcnow()
        conn.execute(
            "INSERT INTO payments (payment_id, invoice_id, version, run_id, amount, currency, "
            "receipt_id, status, created_at) VALUES (?, ?, ?, ?, ?, 'USD', ?, 'success', ?)",
            (payment_id, invoice_id, row["version"], run_id, amount, receipt_id, now),
        )
        ledger.append_audit_event(
            conn,
            run_id,
            "payment",
            "payment_succeeded",
            {"receipt_id": receipt_id, "amount": amount, "currency": "USD"},
            invoice_id=invoice_id,
            version_id=version_id,
        )
        return PaymentResult(
            payment_id=payment_id,
            receipt=MockReceipt(
                receipt_id=receipt_id,
                amount=Decimal(amount),
                currency="USD",
                paid_at=datetime.fromisoformat(now),
            ),
            created=True,
        )


def record_rejection(
    conn: sqlite3.Connection,
    run_id: str,
    invoice_id: str | None,
    version_id: str | None,
    codes: list[FindingCode],
) -> None:
    ledger.append_audit_event(
        conn,
        run_id,
        "payment",
        "rejection_recorded",
        {"codes": [c.value for c in codes]},
        invoice_id=invoice_id,
        version_id=version_id,
    )
