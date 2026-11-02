from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from invoice_processing.codes import DEFAULT_SEVERITY, FindingCode, Severity
from invoice_processing.codes import FindingCode as C
from invoice_processing.intake import read_source
from invoice_processing.limits import DEFAULT_LIMITS
from invoice_processing.normalize import (
    fix_ocr_digits,
    invoice_number_key,
    normalize,
    parse_amount,
    vendor_key,
)
from invoice_processing.parsers import parse_document
from invoice_processing.parsers.text import parse_lines
from invoice_processing.parsers.txt import parse_txt
from invoice_processing.schemas import DraftLine, InvoiceDraft
from invoice_processing.validation import aggregate_quantities

FIXTURE = Path("data/invoices/invoice_1001.txt")


def _norm(tmp_path, text):
    p = tmp_path / "x.txt"
    p.write_text(text)
    return normalize(parse_txt(*read_source(p)))


def test_inv_1001_end_to_end_extraction():
    source, data = read_source(FIXTURE)
    inv, findings = normalize(parse_txt(source, data))
    assert inv.source_id == source.source_id
    assert inv.vendor_name == "Widgets Inc." and inv.vendor_key == "widgets inc."
    assert inv.invoice_number == "INV-1001" and inv.invoice_number_key == "1001"
    assert inv.due_date == date(2026, 2, 1) and inv.invoice_date == date(2026, 1, 15)
    assert [(x.item, x.quantity, x.unit_price) for x in inv.lines] == [
        ("WidgetA", Decimal("10"), Decimal("250.00")),
        ("WidgetB", Decimal("5"), Decimal("500.00")),
    ]
    assert all(x.evidence for x in inv.lines)
    assert inv.stated.subtotal == inv.stated.total == Decimal("5000.00")
    assert inv.stated.tax == Decimal("0.00") and inv.stated.tax_rate == Decimal("0")
    assert inv.currency == "USD"
    assert [f.code for f in findings] == [C.currency_assumed_usd]
    assert "rule:invoice_number_format" in [e.provenance for e in inv.normalization_events]
    assert findings[0].severity == DEFAULT_SEVERITY[C.currency_assumed_usd]
    assert any(e.provenance == "rule:dataset_usd_assumption" for e in inv.normalization_events)


def test_usd_assumption_cites_first_dollar_evidence():
    inv, findings = normalize(parse_txt(*read_source(FIXTURE)))
    event = next(e for e in inv.normalization_events if e.field == "currency")
    assert event.raw_value is None and event.normalized_value == "USD"
    assert event.evidence[0].location == "line:12"
    assert "$" in (event.evidence[0].snippet or "")
    assert findings[0].evidence == event.evidence


def test_crlf_bom_and_trailing_spaces_extract_identically(tmp_path):
    raw = FIXTURE.read_bytes().decode()
    variant = "﻿" + "\r\n".join(x + "  " for x in raw.splitlines())
    p = tmp_path / "v.txt"
    p.write_bytes(variant.encode())
    a, _ = normalize(parse_txt(*read_source(FIXTURE)))
    b, _ = normalize(parse_txt(*read_source(p)))
    skip = {"source_id", "lines", "normalization_events"}
    assert a.model_dump(exclude=skip) == b.model_dump(exclude=skip)
    assert [(x.item, x.quantity) for x in a.lines] == [(x.item, x.quantity) for x in b.lines]


def test_explicit_currency_no_assumption(tmp_path):
    inv, findings = _norm(tmp_path, "Currency: EUR\nSubtotal: $10\n")
    assert inv.currency == "EUR"
    assert findings == []
    assert not any(e.field == "currency" for e in inv.normalization_events)


def test_no_dollar_no_currency(tmp_path):
    inv, findings = _norm(tmp_path, "Subtotal: 10\n")
    assert inv.currency is None
    assert findings == []


def test_unparseable_values_stay_none_with_event(tmp_path):
    inv, _ = _norm(
        tmp_path,
        "Date: 15/01/2026\nTotal: five\nItems:\n  W qty: many unit price: $1\n",
    )
    assert inv.invoice_date is None
    assert inv.stated.total is None
    assert inv.lines[0].quantity is None
    assert inv.lines[0].unit_price == Decimal("1")
    events = {e.field: e for e in inv.normalization_events if e.provenance == "rule:unparseable"}
    assert events["invoice_date"].raw_value == "15/01/2026"
    assert events["invoice_date"].normalized_value is None
    assert "total" in {f.split(".")[-1] for f in events}
    assert any(f.endswith("quantity") for f in events)


def test_blank_vendor_has_no_key(tmp_path):
    inv, _ = _norm(tmp_path, "Vendor:   \nInvoice Number: \n")
    assert inv.vendor_key is None and inv.invoice_number_key is None


def test_tax_rate_is_fraction(tmp_path):
    inv, _ = _norm(tmp_path, "Tax (7%): $7.00\n")
    assert inv.stated.tax_rate == Decimal("0.07")
    assert inv.stated.tax == Decimal("7.00")


def test_parse_amount():
    assert parse_amount(" $5,000.00 ") == Decimal("5000.00")
    with pytest.raises(ValueError):
        parse_amount("five")


def test_keys():
    assert vendor_key("  Widgets   INC. ") == "widgets inc."
    assert invoice_number_key(" inv-1001 ") == "1001"


ITEMS = ("WidgetA", "WidgetB", "GadgetX", "FakeItem")


def norm(name):
    src = read_source(f"data/invoices/{name}")
    return normalize(parse_document(*src, DEFAULT_LIMITS).draft, ITEMS)


def rules(inv):
    return [e.provenance for e in inv.normalization_events]


def test_1010_qualifier():
    inv, _ = norm("invoice_1010.txt")
    assert [(x.item, x.quantity) for x in inv.lines] == [
        ("WidgetA", Decimal(8)),
        ("WidgetB", Decimal(4)),
        ("GadgetX", Decimal(2)),
        ("WidgetA", Decimal(4)),
    ]
    assert inv.lines[3].note == "rush order" and "rule:item_qualifier" in rules(inv)
    assert aggregate_quantities(inv.lines)["WidgetA"].quantity == 12


@pytest.mark.parametrize("name", ["invoice_1012.txt", "invoice_1012.pdf"])
def test_1012_spacing_ocr_identity(name):
    inv, findings = norm(name)
    assert [(x.item, x.quantity) for x in inv.lines] == [
        ("WidgetA", Decimal(12)),
        ("WidgetB", Decimal(7)),
        ("GadgetX", Decimal(4)),
    ]
    assert inv.lines[1].line_total == Decimal("3500.00")
    assert inv.invoice_number == "INV 1012" and inv.invoice_number_key == "1012"
    assert rules(inv).count("rule:item_spacing") == 2
    assert "rule:ocr_digit" in rules(inv) and "rule:invoice_number_format" in rules(inv)
    assert inv.vendor_key == "quickship distributers"
    assert not [f for f in findings if f.code is FindingCode.ambiguous_normalization]


def test_1012_events_carry_canonical_values_and_evidence():
    inv, _ = norm("invoice_1012.txt")
    spacing = [e for e in inv.normalization_events if e.provenance == "rule:item_spacing"]
    assert [(e.field, e.raw_value, e.normalized_value) for e in spacing] == [
        ("lines[0].item", "Widget A", "WidgetA"),
        ("lines[2].item", "Gadget X", "GadgetX"),
    ]
    ocr = next(e for e in inv.normalization_events if e.provenance == "rule:ocr_digit")
    assert ocr.field == "lines[1].line_total" and ocr.raw_value == "$3,500.O0"
    assert [e.location for e in ocr.evidence] == ["line:17"]


def test_1016_widgetc_not_mapped():
    inv, _ = norm("invoice_1016.json")
    assert inv.lines[2].item == "WidgetC"


def test_ocr_amount_disagreeing_with_qty_price_is_not_applied():
    d = parse_lines(
        "s",
        [("line:1", "Item  Qty  Unit Price  Amount"), ("line:2", "WidgetB  6  $500.00  $3,5O0.00")],
    )
    inv, findings = normalize(d, ITEMS)
    assert inv.lines[0].line_total is None
    assert [f.code for f in findings if f.severity is Severity.review] == [
        FindingCode.ambiguous_normalization
    ]
    assert "rule:ocr_digit" not in rules(inv)


def test_ocr_line_total_applied_when_price_missing():
    d = InvoiceDraft(
        source_id="s",
        lines=[DraftLine(raw_name="WidgetB", quantity_raw="6", line_total_raw="$3,5O0.00")],
    )
    inv, findings = normalize(d, ITEMS)
    assert inv.lines[0].line_total == Decimal("3500.00")
    assert not [f for f in findings if f.code is FindingCode.ambiguous_normalization]
    assert "rule:ocr_digit" in rules(inv)


@pytest.mark.parametrize("raw", ["PO-20260115", "26-Oct-2026", "ORDER 5", "$3,500.00"])
def test_ocr_leaves_non_numeric_o_alone(raw):
    assert fix_ocr_digits(raw) is None


@pytest.mark.parametrize("raw,expected", [("2O26", "2026"), ("$3,500.O0", "$3,500.00")])
def test_ocr_fixes_digit_tokens(raw, expected):
    assert fix_ocr_digits(raw) == expected


@pytest.mark.parametrize("raw", ["1,2,3", "12,34.00", "$1,00"])
def test_parse_amount_rejects_misplaced_commas(raw):
    with pytest.raises(ValueError):
        parse_amount(raw)


@pytest.mark.parametrize(
    "raw,value",
    [("-$5.00", "-5.00"), ("$-5.00", "-5.00"), ("€1,234.50", "1234.50"), ("£7", "7"), ("12", "12")],
)
def test_parse_amount_symbols_and_sign(raw, value):
    assert parse_amount(raw) == Decimal(value)


@pytest.mark.parametrize("raw", ["--5", "-$-5", "$$5", "1e3", "+5"])
def test_parse_amount_rejects_odd_forms(raw):
    with pytest.raises(ValueError):
        parse_amount(raw)


@pytest.mark.parametrize(
    "raw,key", [("INV 1012", "1012"), ("INV-1012", "1012"), ("1002", "1002"), ("inv-1001", "1001")]
)
def test_invoice_number_key(raw, key):
    assert invoice_number_key(raw) == key


def test_invoice_number_key_keeps_inv_not_followed_by_digit():
    assert invoice_number_key("INVX-9") == "INVX9"


def test_no_format_event_when_key_equals_display(tmp_path):
    inv, _ = _norm(tmp_path, "Invoice Number: 1002\n")
    assert "rule:invoice_number_format" not in rules(inv)


def test_unparseable_value_cites_its_own_line():
    d = parse_lines("s", [("line:1", "Vendor: A"), ("line:2", "Total: $abc")])
    _, findings = normalize(d, ITEMS)
    f = next(f for f in findings if f.code is FindingCode.unparseable_value)
    assert f.field == "total" and [e.location for e in f.evidence] == ["line:2"]
    assert f.severity is Severity.review


def test_terms_notes_and_fraction_tax_rate_are_copied():
    inv, _ = norm("invoice_1016.json")
    assert inv.payment_terms == "Net 30" and inv.notes is None
    assert inv.stated.tax_rate == Decimal("0.06")
    inv, _ = norm("invoice_1012.txt")
    assert inv.notes and inv.notes.startswith("Ref PO-20260115")
    assert inv.stated.tax_rate == Decimal("0.05")


def test_unparseable_json_tax_rate_cites_its_own_path(tmp_path):
    p = tmp_path / "t.json"
    p.write_text('{"invoice_number": "INV-9", "tax_rate": "abc"}')
    inv, findings = normalize(parse_document(*read_source(p), DEFAULT_LIMITS).draft, ITEMS)
    f = next(f for f in findings if f.code is FindingCode.unparseable_value)
    assert f.field == "tax_rate" and [e.location for e in f.evidence] == ["$.tax_rate"]
    event = next(e for e in inv.normalization_events if e.provenance == "rule:unparseable")
    assert [e.location for e in event.evidence] == ["$.tax_rate"]


@pytest.mark.parametrize("raw", ["#", " - ", "./_"])
def test_invoice_number_reducing_to_empty_key_has_no_key(raw):
    inv, _ = normalize(InvoiceDraft(source_id="s", invoice_number_raw=raw), ITEMS)
    assert inv.invoice_number_key is None
