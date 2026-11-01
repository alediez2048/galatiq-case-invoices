from decimal import Decimal

from invoice_processing import validation
from invoice_processing.codes import FindingCode as C
from invoice_processing.codes import Severity
from tests.helpers import codes, inv_1009, inv_1010, inv_1013, invoice, line


def test_1013_total_mismatch_of_50():
    computed, findings = validation.reconcile_totals(inv_1013())
    assert computed.subtotal == Decimal("21040.00")
    assert computed.tax == Decimal("1472.80")
    assert computed.total == Decimal("22512.80")
    [f] = [x for x in findings if x.code == C.total_mismatch]
    assert f.severity == Severity.blocker
    assert f.expected == "22512.80" and f.observed == "22562.80"
    assert C.subtotal_mismatch not in codes(findings)
    assert C.tax_mismatch not in codes(findings)


def test_1010_adds_up():
    computed, findings = validation.reconcile_totals(inv_1010())
    assert computed.total == Decimal("7185.00")
    assert findings == []


def test_1009_subtotal_mismatch():
    computed, findings = validation.reconcile_totals(inv_1009())
    assert computed.subtotal == Decimal("-250.00")
    assert C.subtotal_mismatch in codes(findings)


def test_one_cent_tolerated_two_cents_blocks():
    base = [line("WidgetA", "1", "100.00")]
    _, f = validation.reconcile_totals(invoice(lines=base, total="100.01"))
    assert codes(f) == [C.rounding_tolerated]
    _, f = validation.reconcile_totals(invoice(lines=base, total="100.02"))
    assert codes(f) == [C.total_mismatch]


def test_missing_tax_and_shipping_count_as_zero():
    _, f = validation.reconcile_totals(
        invoice(
            lines=[line("SuperGizmo", "12", "400.00"), line("MegaSprocket", "6", "850.00")],
            total="9900.00",
        )
    )
    assert f == []


def test_unverifiable_line_skips_totals():
    computed, f = validation.reconcile_totals(
        invoice(lines=[line("WidgetA", None, "250.00")], total="250.00")
    )
    assert computed.subtotal is None and computed.total is None
    assert codes(f) == [C.arithmetic_unverifiable] and f[0].severity == Severity.warning


def test_line_total_mismatch():
    _, f = validation.reconcile_totals(
        invoice(lines=[line("WidgetA", "2", "250.00", total="600.00")])
    )
    assert C.line_total_mismatch in codes(f)


def test_tax_rate_mismatch():
    _, f = validation.reconcile_totals(
        invoice(lines=[line("WidgetA", "1", "100.00")], tax_rate="0.10", tax="5.00", total="105.00")
    )
    assert C.tax_mismatch in codes(f)


def test_stated_values_untouched():
    inv = inv_1013()
    validation.reconcile_totals(inv)
    assert inv.stated.total == Decimal("22562.80")
