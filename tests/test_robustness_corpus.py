"""P6-01 campaign 1: whole corpus through one ledger, forward then reverse order."""

import pytest

from invoice_processing.codes import RunStatus
from invoice_processing.service import process_invoice
from tests.robustness import CORPUS, EVAL, OFF, PaymentSpy, fresh_db, payment_count, query

NAMES = sorted(p.name for p in CORPUS.iterdir() if p.is_file())

# Identities (vendor_key, invoice_number_key) whose paid/unpaid fate must not depend on order.
PAID_IDENTITIES = {
    ("acme industrial supplies", "1006"),
    ("consolidated materials group", "1010"),
    ("precision parts ltd.", "1004"),
    ("quickship distributers", "1012"),
    ("reliable components inc.", "1015"),
    ("summit manufacturing co.", "1011"),
    ("widgets inc.", "1001"),
}


def run_corpus(order, tmp_path, monkeypatch):
    db = fresh_db(tmp_path)
    spy = PaymentSpy(monkeypatch)
    results = {n: process_invoice(CORPUS / n, OFF, db, EVAL) for n in order}
    return db, spy, results


def identity_table(db):
    """identity -> (invoice status, paid amount or None, payment count)."""
    rows = query(
        db,
        "SELECT i.vendor_key, i.invoice_number_key, i.status, p.amount, "
        "(SELECT COUNT(*) FROM payments q WHERE q.invoice_id = i.invoice_id) "
        "FROM invoices i LEFT JOIN payments p ON p.invoice_id = i.invoice_id",
    )
    return {(r[0], r[1]): (r[2], r[3], r[4]) for r in rows}


@pytest.fixture(scope="module")
def both_orders(tmp_path_factory):
    out = {}
    for label, order in (("forward", NAMES), ("reverse", NAMES[::-1])):
        mp = pytest.MonkeyPatch()
        try:
            out[label] = run_corpus(order, tmp_path_factory.mktemp(label), mp)
        finally:
            mp.undo()
    return out


@pytest.mark.parametrize("label", ["forward", "reverse"])
def test_one_payment_per_identity(both_orders, label):
    db, spy, results = both_orders[label]
    table = identity_table(db)
    assert all(count <= 1 for _, _, count in table.values())
    assert {k for k, v in table.items() if v[2] == 1} == PAID_IDENTITIES
    # gateway calls == rows == distinct idempotency keys == paid runs
    paid_runs = [r for r in results.values() if r.status is RunStatus.paid_mock]
    assert len(spy.keys) == len(set(spy.keys)) == payment_count(db) == len(PAID_IDENTITIES)
    assert len(paid_runs) == len(PAID_IDENTITIES)
    # every run ended in a terminal, non-failed state
    assert RunStatus.failed not in {r.status for r in results.values()}


def test_identical_outcome_per_identity_across_orders(both_orders):
    """'Identical' means: same identity set, same invoice status per identity, same paid set.

    Allowed to differ with order: which *file* of a format twin (1011/1012 txt vs pdf,
    1013 json vs pdf) is the paid/rejected one and which is the 'duplicate'; and for
    INV-1004 which version (original 1890.00 vs revised 5940.00) arrived first and so is
    the one paid. The later one is routed to needs_review (revision_after_payment).
    """
    fwd = identity_table(both_orders["forward"][0])
    rev = identity_table(both_orders["reverse"][0])
    assert fwd.keys() == rev.keys()
    for key in fwd:
        assert fwd[key][0] == rev[key][0], key  # invoice status
        assert fwd[key][2] == rev[key][2], key  # payment count
        if key != ("precision parts ltd.", "1004"):
            assert fwd[key][1] == rev[key][1], key  # paid amount
    assert fwd[("precision parts ltd.", "1004")][1] == "1890.00"
    assert rev[("precision parts ltd.", "1004")][1] == "5940.00"


@pytest.mark.parametrize(
    "twin_a,twin_b,paid_amount",
    [
        ("invoice_1011.txt", "invoice_1011.pdf", "3000.00"),
        ("invoice_1012.txt", "invoice_1012.pdf", "9975.00"),
    ],
)
def test_format_twin_first_processed_is_paid_second_is_duplicate(
    both_orders, twin_a, twin_b, paid_amount
):
    for label in ("forward", "reverse"):
        _, _, results = both_orders[label]
        # forward order is alphabetical: .pdf sorts before .txt, reverse the opposite
        order = [n for n in (NAMES if label == "forward" else NAMES[::-1]) if n in (twin_a, twin_b)]
        assert results[order[0]].status is RunStatus.paid_mock
        assert results[order[1]].status is RunStatus.duplicate
        assert results[order[1]].receipt.receipt_id == results[order[0]].receipt.receipt_id
        assert str(results[order[0]].receipt.amount) == paid_amount


def test_rejected_twin_1013_second_is_duplicate_without_receipt(both_orders):
    for label in ("forward", "reverse"):
        _, _, results = both_orders[label]
        order = [n for n in (NAMES if label == "forward" else NAMES[::-1]) if "1013" in n]
        assert results[order[0]].status is RunStatus.rejected
        assert results[order[1]].status is RunStatus.duplicate
        assert results[order[1]].receipt is None


def test_revision_of_paid_1004_never_pays_second_version(both_orders):
    for label, later in (
        ("forward", "invoice_1004_revised.json"),
        ("reverse", "invoice_1004.json"),
    ):
        _, _, results = both_orders[label]
        assert results[later].status is RunStatus.needs_review
        assert results[later].receipt is None


def test_reprocessing_whole_corpus_only_adds_duplicates(both_orders, monkeypatch):
    db, _, first = both_orders["forward"]
    spy = PaymentSpy(monkeypatch)
    again = {n: process_invoice(CORPUS / n, OFF, db, EVAL) for n in NAMES}
    assert spy.keys == []
    assert payment_count(db) == len(PAID_IDENTITIES)
    assert {r.status for r in again.values()} == {RunStatus.duplicate}
