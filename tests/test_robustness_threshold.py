"""P6-01 campaign 5: the 10,000.00 high-value threshold, offline expectations.

Rule: total <= 10,000.00 with a clean invoice -> paid_mock; total > 10,000.00 ->
awaiting_human_approval and no payment. Fixtures live in tests/fixtures/robustness/ and
include cases where tax or shipping pushes a below-threshold subtotal over the line.
"""

from decimal import Decimal

import pytest

from invoice_processing.codes import RunStatus
from invoice_processing.policy import HIGH_VALUE_THRESHOLD_USD
from invoice_processing.service import process_invoice
from tests.robustness import EVAL, FIXTURES, OFF, fresh_db, payment_count, query

# file -> (stated total, subtotal as lines, expected status)
CASES = {
    "threshold_9999_99": ("9999.99", RunStatus.paid_mock),
    "threshold_10000_00": ("10000.00", RunStatus.paid_mock),
    "threshold_10000_01": ("10000.01", RunStatus.awaiting_human_approval),
    "threshold_sub_9999_99_tax_pushes_to_10000_00": ("10000.00", RunStatus.paid_mock),
    "threshold_sub_9999_99_tax_pushes_over": ("10000.01", RunStatus.awaiting_human_approval),
    "threshold_sub_9500_tax_ship_to_10000_00": ("10000.00", RunStatus.paid_mock),
    "threshold_sub_9500_tax_ship_over": ("10000.01", RunStatus.awaiting_human_approval),
    "threshold_sub_10000_shipping_over": ("10000.01", RunStatus.awaiting_human_approval),
}


def test_every_fixture_has_a_case():
    assert sorted(p.stem for p in FIXTURES.glob("threshold_*.json")) == sorted(CASES)


def test_threshold_constant_is_ten_thousand():
    assert HIGH_VALUE_THRESHOLD_USD == Decimal("10000.00")


@pytest.mark.parametrize("name", sorted(CASES))
def test_threshold_boundary(tmp_path, name):
    total, expected = CASES[name]
    db = fresh_db(tmp_path)
    r = process_invoice(FIXTURES / f"{name}.json", OFF, db, EVAL)
    assert r.status is expected
    stored = query(
        db,
        "SELECT json_extract(payload_json, '$.stated.total') FROM invoice_versions",
    )[0][0]
    assert Decimal(str(stored)) == Decimal(total)
    if expected is RunStatus.paid_mock:
        assert r.receipt.amount == Decimal(total)
        assert payment_count(db) == 1
    else:
        assert r.receipt is None and payment_count(db) == 0
        assert r.decision is not None and "R3_high_value" in r.decision.reasons


@pytest.mark.parametrize("name", sorted(CASES))
def test_threshold_rerun_never_changes_payment_count(tmp_path, name):
    _, expected = CASES[name]
    db = fresh_db(tmp_path)
    for _ in range(2):
        process_invoice(FIXTURES / f"{name}.json", OFF, db, EVAL)
    assert payment_count(db) == (1 if expected is RunStatus.paid_mock else 0)
