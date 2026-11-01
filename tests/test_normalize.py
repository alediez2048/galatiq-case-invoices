from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from invoice_processing.codes import DEFAULT_SEVERITY
from invoice_processing.codes import FindingCode as C
from invoice_processing.intake import read_source
from invoice_processing.normalize import (
    invoice_number_key,
    normalize,
    parse_amount,
    vendor_key,
)
from invoice_processing.parsers.txt import parse_txt

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
    assert inv.invoice_number == "INV-1001" and inv.invoice_number_key == "INV-1001"
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
    assert invoice_number_key(" inv-1001 ") == "INV-1001"
