from datetime import date
from decimal import Decimal

from invoice_processing import validation
from invoice_processing.codes import FindingCode as C
from invoice_processing.codes import Severity
from tests.helpers import codes, inv_1001, inv_1009, invoice, line


def test_1001_has_no_blockers():
    inv = inv_1001()
    findings = validation.check_required_fields(inv) + validation.check_value_signs(inv)
    assert findings == []


def test_1009_required_and_sign_blockers():
    inv = inv_1009()
    got = set(codes(validation.check_required_fields(inv) + validation.check_value_signs(inv)))
    assert {
        C.missing_vendor,
        C.missing_due_date,
        C.non_positive_quantity,
        C.non_positive_total,
    } <= got
    assert all(f.severity == Severity.blocker for f in validation.check_required_fields(inv))


def test_whitespace_vendor_is_missing():
    inv = invoice(lines=[line("WidgetA", "1", "1")], vendor="   ")
    assert C.missing_vendor in codes(validation.check_required_fields(inv))


def test_missing_and_incomplete_lines():
    assert C.missing_line_items in codes(validation.check_required_fields(invoice(lines=[])))
    inv = invoice(lines=[line("WidgetA", None, "250.00")])
    f = [x for x in validation.check_required_fields(inv) if x.code == C.incomplete_line_item]
    assert len(f) == 1 and f[0].item == "WidgetA"


def test_incomplete_line_without_name_is_identified_by_index():
    inv = invoice(lines=[line("WidgetA", "1", "1"), line(None, "1", "1")])
    f = [x for x in validation.check_required_fields(inv) if x.code == C.incomplete_line_item]
    assert [x.item for x in f] == ["line:1"]


def test_quantity_with_fractional_zero_is_integer():
    inv = invoice(lines=[line("WidgetA", "10.0", "250.00")])
    assert C.non_integer_quantity not in codes(validation.check_value_signs(inv))
    inv = invoice(lines=[line("WidgetA", "2.5", "250.00")])
    assert C.non_integer_quantity in codes(validation.check_value_signs(inv))


def test_zero_and_negative_zero_total():
    for total in ("0", "-0.00"):
        inv = invoice(lines=[line("WidgetA", "1", "1")], total=total)
        assert C.non_positive_total in codes(validation.check_value_signs(inv))


def test_negative_price_tax_shipping():
    inv = invoice(lines=[line("WidgetA", "1", "-1")], tax="-1", shipping="-2", total="1")
    got = codes(validation.check_value_signs(inv))
    assert {C.negative_unit_price, C.negative_tax, C.negative_shipping} <= set(got)


def test_missing_total_and_currency_are_blockers():
    inv = invoice(lines=[line("WidgetA", "1", "1")], currency=None, total=None)
    got = codes(validation.check_required_fields(inv))
    assert C.missing_total in got and C.missing_currency in got


def test_due_date_past_is_warning_and_depends_only_on_evaluation_date():
    inv = inv_1001()  # due 2026-02-01
    assert validation.check_due_date(inv, date(2026, 1, 31)) == []
    f = validation.check_due_date(inv, date(2026, 2, 2))
    assert codes(f) == [C.due_date_past] and f[0].severity == Severity.warning
    assert f[0].observed == "2026-02-01" and f[0].expected == "2026-02-02"
    assert validation.check_due_date(invoice(lines=[], due=None), date(2026, 2, 2)) == []


def test_observed_values_are_strings():
    inv = invoice(lines=[line("WidgetA", "-5", "250.00")], total="1")
    f = [x for x in validation.check_value_signs(inv) if x.code == C.non_positive_quantity][0]
    assert f.observed == "-5" and f.item == "WidgetA" and isinstance(f.observed, str)
    assert Decimal(f.observed) == Decimal("-5")
