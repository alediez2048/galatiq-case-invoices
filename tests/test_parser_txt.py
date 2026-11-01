from pathlib import Path

import pytest

from invoice_processing.intake import read_source
from invoice_processing.parsers.txt import ExtractionError, parse_txt

FIXTURE = Path("data/invoices/invoice_1001.txt")


def test_fixture_raw_fields():
    d = parse_txt(*read_source(FIXTURE))
    assert d.vendor_raw == "Widgets Inc."
    assert d.invoice_number_raw == "INV-1001"
    assert d.invoice_date_raw == "2026-01-15"
    assert d.due_date_raw == "2026-02-01"
    assert d.subtotal_raw == "$5,000.00"
    assert d.tax_rate_raw == "0"
    assert d.tax_raw == "$0.00"
    assert d.total_raw == "$5,000.00"
    assert d.currency_raw is None
    assert [(x.raw_name, x.quantity_raw, x.unit_price_raw) for x in d.lines] == [
        ("WidgetA", "10", "$250.00"),
        ("WidgetB", "5", "$500.00"),
    ]
    assert d.issues == []


def test_every_extracted_value_has_line_evidence():
    draft = parse_txt(*read_source(FIXTURE))
    assert all(x.evidence and x.evidence[0].location.startswith("line:") for x in draft.lines)
    assert [x.evidence[0].location for x in draft.lines] == ["line:9", "line:10"]
    locations = {e.location for e in draft.evidence}
    assert {"line:3", "line:4", "line:5", "line:6", "line:12", "line:13", "line:14"} <= locations
    vendor_ref = next(e for e in draft.evidence if e.location == "line:3")
    assert vendor_ref.snippet == "Vendor: Widgets Inc."


def test_crlf_bom_and_trailing_spaces_parse_identically(tmp_path):
    raw = FIXTURE.read_bytes().decode()
    variant = "﻿" + "\r\n".join(x + "  " for x in raw.splitlines())
    p = tmp_path / "v.txt"
    p.write_bytes(variant.encode())
    a = parse_txt(*read_source(FIXTURE))
    b = parse_txt(*read_source(p))
    raw_fields = {k: v for k, v in a.model_dump().items() if k.endswith("_raw")}
    assert raw_fields == {k: v for k, v in b.model_dump().items() if k.endswith("_raw")}
    assert [(x.raw_name, x.quantity_raw, x.unit_price_raw) for x in a.lines] == [
        (x.raw_name, x.quantity_raw, x.unit_price_raw) for x in b.lines
    ]
    assert [e.snippet for e in a.evidence] == [e.snippet for e in b.evidence]


def test_invalid_utf8_raises_extraction_error(tmp_path):
    p = tmp_path / "bad.txt"
    p.write_bytes(b"Vendor: \xff\xfe\n")
    with pytest.raises(ExtractionError) as e:
        parse_txt(*read_source(p))
    assert e.value.code == "txt_decode_error"


def test_unparsed_line_becomes_issue(tmp_path):
    p = tmp_path / "x.txt"
    p.write_text("INVOICE\n\nVendor: A\nHello world\n")
    d = parse_txt(*read_source(p))
    assert [i.code for i in d.issues] == ["unparsed_line"]
    assert d.issues[0].evidence[0].location == "line:4"
    assert d.issues[0].evidence[0].snippet == "Hello world"
    assert d.vendor_raw == "A"


def test_unparsed_item_line_becomes_issue(tmp_path):
    p = tmp_path / "x.txt"
    p.write_text("Items:\n  WidgetA qty: 1 unit price: 2\n  garbage here\n\nTotal: 2\n")
    d = parse_txt(*read_source(p))
    assert len(d.lines) == 1
    assert [i.code for i in d.issues] == ["unparsed_line"]
    assert d.issues[0].evidence[0].location == "line:3"
    assert d.total_raw == "2"


def test_explicit_currency_label(tmp_path):
    p = tmp_path / "x.txt"
    p.write_text("Currency: EUR\nTotal: 10\n")
    d = parse_txt(*read_source(p))
    assert d.currency_raw == "EUR"
    assert d.issues == []
