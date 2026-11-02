"""Fixture acceptance suite: every file in data/invoices/ has an asserted offline outcome."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from invoice_processing import payments, seed, storage, validation
from invoice_processing.codes import ExecutionMode, RunStatus, Severity
from invoice_processing.schemas import NormalizedInvoice
from invoice_processing.service import process_invoice
from invoice_processing.storage import connect

CORPUS = Path("data/invoices")
EVAL = date(2026, 1, 31)

# file: (status, paid amount, gating blocker+review codes, codes that must also be present)
CASES = {
    "invoice_1001.txt": ("paid_mock", "5000.00", set(), {"currency_assumed_usd"}),
    "invoice_1002.txt": ("rejected", None, {"quantity_exceeds_stock"}, {"terms_inconsistent"}),
    "invoice_1003.txt": (
        "rejected",
        None,
        {"zero_stock", "due_date_unresolved"},
        {"risk_signal_urgency"},
    ),
    "invoice_1004.json": ("paid_mock", "1890.00", set(), set()),
    "invoice_1004_revised.json": ("paid_mock", "5940.00", set(), set()),
    "invoice_1005.json": ("rejected", None, {"quantity_exceeds_stock"}, set()),
    "invoice_1006.csv": ("paid_mock", "2750.00", set(), {"currency_assumed_usd"}),
    "invoice_1007.csv": (
        "rejected",
        None,
        {"quantity_exceeds_stock", "total_mismatch"},
        set(),
    ),
    "invoice_1008.txt": ("rejected", None, {"unknown_item"}, set()),
    "invoice_1009.json": (
        "rejected",
        None,
        {
            "missing_vendor",
            "missing_due_date",
            "non_positive_quantity",
            "non_positive_total",
            "subtotal_mismatch",
        },
        set(),
    ),
    "invoice_1010.txt": ("paid_mock", "7185.00", set(), set()),
    "invoice_1011.txt": ("paid_mock", "3000.00", set(), set()),
    "invoice_1011.pdf": ("paid_mock", "3000.00", set(), {"currency_assumed_usd"}),
    "invoice_1012.txt": ("paid_mock", "9975.00", set(), set()),
    "invoice_1012.pdf": ("paid_mock", "9975.00", set(), set()),
    "invoice_1013.json": (
        "rejected",
        None,
        {"quantity_exceeds_stock", "total_mismatch"},
        set(),
    ),
    "invoice_1013.pdf": (
        "rejected",
        None,
        {"quantity_exceeds_stock", "total_mismatch"},
        {"currency_assumed_usd"},
    ),
    "invoice_1014.xml": (
        "needs_review",
        None,
        {"unsupported_currency", "non_usd_currency"},
        set(),
    ),
    "invoice_1015.csv": ("paid_mock", "6500.00", set(), {"currency_assumed_usd"}),
    "invoice_1016.json": ("rejected", None, {"unknown_item"}, set()),
}


class Outcome:
    def __init__(self, result, db, payment_calls):
        self.result = result
        self.db = db
        self.payment_calls = payment_calls

    @property
    def findings(self):
        return self.result.findings

    def by_code(self, code):
        return [f for f in self.findings if f.code == code]

    def invoice(self) -> NormalizedInvoice:
        c = connect(self.db)
        try:
            row = c.execute(
                "SELECT payload_json FROM invoice_versions WHERE invoice_id = ? "
                "ORDER BY version DESC LIMIT 1",
                (self.result.invoice_id,),
            ).fetchone()
        finally:
            c.close()
        return NormalizedInvoice.model_validate(json.loads(row[0], parse_float=Decimal))

    def events(self, provenance):
        return [e for e in self.invoice().normalization_events if e.provenance == provenance]

    def payment_rows(self):
        c = connect(self.db)
        try:
            return c.execute("SELECT COUNT(*) FROM payments").fetchone()[0]
        finally:
            c.close()


@pytest.fixture(scope="module")
def outcomes(tmp_path_factory):
    """Process each fixture once, each on its own freshly seeded database."""
    results: dict[str, Outcome] = {}
    real = payments.mock_payment
    mp = pytest.MonkeyPatch()
    calls: list[tuple] = []

    def counting(*args, **kwargs):
        calls.append((args, kwargs))
        return real(*args, **kwargs)

    mp.setattr(payments, "mock_payment", counting)
    try:
        for name in CASES:
            db = tmp_path_factory.mktemp(name.replace(".", "_")) / "case.db"
            c = connect(db)
            storage.init_schema(c)
            seed.seed_inventory(c)
            c.close()
            calls.clear()
            result = process_invoice(CORPUS / name, ExecutionMode.offline, db, EVAL)
            results[name] = Outcome(result, db, list(calls))
    finally:
        mp.undo()
    return results


def test_every_fixture_has_a_case():
    assert sorted(p.name for p in CORPUS.iterdir() if p.is_file()) == sorted(CASES)


@pytest.mark.parametrize("name", sorted(CASES))
def test_fixture_outcome(name, outcomes):
    status, amount, gating, also = CASES[name]
    o = outcomes[name]
    assert o.result.status is RunStatus(status)
    gated = {f.code.value for f in o.findings if f.severity in (Severity.blocker, Severity.review)}
    assert gated == gating
    assert also <= {f.code.value for f in o.findings}
    if status == "paid_mock":
        assert o.result.receipt.amount == Decimal(amount)
        assert len(o.payment_calls) == 1
        assert o.payment_rows() == 1
    else:
        assert o.result.receipt is None
        assert o.payment_calls == []
        assert o.payment_rows() == 0


def test_no_identity_paid_twice_across_corpus(outcomes):
    paid = [o for o in outcomes.values() if o.result.status is RunStatus.paid_mock]
    assert len(paid) == sum(1 for c in CASES.values() if c[0] == "paid_mock")
    assert all(len(o.payment_calls) == 1 for o in paid)


def only(findings, code):
    return [(f.item, f.expected, f.observed) for f in findings if f.code == code]


def test_invoice_1002(outcomes):
    o = outcomes["invoice_1002.txt"]
    aliased = {e.field for e in o.events("rule:label_alias")}
    assert {
        "vendor",
        "invoice_number",
        "invoice_date",
        "due_date",
        "total",
        "payment_terms",
    } <= aliased
    assert only(o.findings, "quantity_exceeds_stock") == [("GadgetX", "5", "20")]


def test_invoice_1003(outcomes):
    o = outcomes["invoice_1003.txt"]
    assert [f.item for f in o.by_code("zero_stock")] == ["FakeItem"]
    assert o.invoice().due_date is None


def test_invoice_1005(outcomes):
    assert only(outcomes["invoice_1005.json"].findings, "quantity_exceeds_stock") == [
        ("GadgetX", "5", "8")
    ]


def test_invoice_1007(outcomes):
    # The fixture's stated total (15525.00) is 110.00 below subtotal + 6% tax (15635.00).
    assert only(outcomes["invoice_1007.csv"].findings, "total_mismatch") == [
        (None, "15635.00", "15525.00")
    ]
    assert sorted(only(outcomes["invoice_1007.csv"].findings, "quantity_exceeds_stock")) == [
        ("WidgetA", "15", "20"),
        ("WidgetB", "10", "15"),
    ]


def test_invoice_1008(outcomes):
    items = {f.item for f in outcomes["invoice_1008.txt"].by_code("unknown_item")}
    assert items == {"SuperGizmo", "MegaSprocket"}


def test_invoice_1010(outcomes):
    o = outcomes["invoice_1010.txt"]
    assert o.events("rule:item_qualifier")
    assert validation.aggregate_quantities(o.invoice().lines)["WidgetA"].quantity == 12


@pytest.mark.parametrize("name", ["invoice_1012.txt", "invoice_1012.pdf"])
def test_invoice_1012(name, outcomes):
    o = outcomes[name]
    for provenance in ("rule:item_spacing", "rule:ocr_digit", "rule:invoice_number_format"):
        assert o.events(provenance), provenance


@pytest.mark.parametrize("name", ["invoice_1013.json", "invoice_1013.pdf"])
def test_invoice_1013(name, outcomes):
    o = outcomes[name]
    got = {(i, obs) for i, _, obs in only(o.findings, "quantity_exceeds_stock")}
    assert {("WidgetA", "22"), ("WidgetB", "18"), ("GadgetX", "9")} <= got
    assert only(o.findings, "total_mismatch") == [(None, "22512.80", "22562.80")]


def test_invoice_1014(outcomes):
    o = outcomes["invoice_1014.xml"]
    assert o.invoice().currency == "EUR"
    assert o.payment_rows() == 0


def test_invoice_1016(outcomes):
    assert {f.item for f in outcomes["invoice_1016.json"].by_code("unknown_item")} == {"WidgetC"}


def test_shared_ledger_never_pays_an_identity_twice(tmp_path, monkeypatch):
    """All files through one database: alternate formats and revisions add no second payment."""
    db = tmp_path / "shared.db"
    c = connect(db)
    storage.init_schema(c)
    seed.seed_inventory(c)
    c.close()
    calls: list[str] = []
    real = payments.mock_payment

    def counting(*args, **kwargs):
        calls.append(kwargs.get("idempotency_key"))
        return real(*args, **kwargs)

    monkeypatch.setattr(payments, "mock_payment", counting)
    for name in sorted(CASES):
        process_invoice(CORPUS / name, ExecutionMode.offline, db, EVAL)
    assert len(calls) == len(set(calls))
    c = connect(db)
    try:
        per_invoice = c.execute(
            "SELECT invoice_id, COUNT(*) FROM payments GROUP BY invoice_id"
        ).fetchall()
    finally:
        c.close()
    assert all(n == 1 for _, n in per_invoice)
    assert len(per_invoice) == len(calls)
