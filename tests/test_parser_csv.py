import pytest

from invoice_processing.intake import read_source
from invoice_processing.limits import DEFAULT_LIMITS
from invoice_processing.parsers import PARSER_VERSIONS, parse_document
from invoice_processing.parsers.base import ExtractionError
from invoice_processing.parsers.csv_parser import parse_csv

HEADER = "Invoice Number,Vendor,Date,Due Date,Item,Qty,Unit Price,Line Total\n"


def lines(x):
    return [(ln.raw_name, ln.quantity_raw, ln.unit_price_raw) for ln in x.lines]


def _parse(tmp_path, text, name="a.csv", raw=None):
    p = tmp_path / name
    if raw is not None:
        p.write_bytes(raw)
    else:
        p.write_text(text)
    return parse_csv(*read_source(p))


def test_1006_field_value():
    x = parse_csv(*read_source("data/invoices/invoice_1006.csv"))
    assert lines(x) == [("WidgetA", "5", "250.00"), ("WidgetB", "3", "500.00")]
    assert (x.subtotal_raw, x.tax_raw, x.total_raw, x.payment_terms_raw) == (
        "2750.00",
        "0.00",
        "2750.00",
        "Net 15",
    )
    assert x.vendor_raw == "Acme Industrial Supplies" and x.issues == []
    assert x.field_evidence["invoice_number"][0].location == "row:2"
    assert x.lines[0].evidence[0].location.startswith("row:")


def test_1007_row_table():
    x = parse_csv(*read_source("data/invoices/invoice_1007.csv"))
    assert len(x.lines) == 3 and (x.invoice_date_raw, x.due_date_raw) == (
        "01/28/2026",
        "02/28/2026",
    )
    assert (x.subtotal_raw, x.tax_rate_raw, x.tax_raw, x.total_raw) == (
        "14750.00",
        "6",
        "885.00",
        "15525.00",
    )
    assert x.lines[0].line_total_raw == "5000.00"
    assert x.issues == []
    assert x.field_evidence["vendor"][0].location == "row:2,col:Vendor"
    assert x.lines[0].evidence[0].location == "row:2"


def test_1015_row_table():
    x = parse_csv(*read_source("data/invoices/invoice_1015.csv"))
    assert len(x.lines) == 3 and (x.subtotal_raw, x.tax_raw, x.total_raw) == (
        "6500.00",
        "0.00",
        "6500.00",
    )
    assert x.tax_rate_raw == "0"


def test_rows_disagree_on_vendor(tmp_path):
    x = _parse(
        tmp_path,
        HEADER + "INV-1,A Co,2026-01-01,2026-02-01,WidgetA,1,1.00,1.00\n"
        "INV-1,B Co,2026-01-01,2026-02-01,WidgetB,1,1.00,1.00\n",
    )
    assert x.vendor_raw == "A Co" and "inconsistent_row_header" in [i.code for i in x.issues]
    bad = [i for i in x.issues if i.code == "inconsistent_row_header"][0]
    assert len(bad.evidence) == 2


def test_incomplete_group_not_merged(tmp_path):
    x = _parse(
        tmp_path,
        "field,value\nitem,WidgetA\nquantity,5\nitem,WidgetB\nquantity,3\nunit_price,500.00\n",
    )
    assert lines(x) == [("WidgetA", "5", None), ("WidgetB", "3", "500.00")]


def test_unknown_layout(tmp_path):
    with pytest.raises(ExtractionError) as e:
        _parse(tmp_path, "a,b,c\n1,2,3\n")
    assert e.value.code == "unsupported_csv_layout"
    assert str(e.value) == "This CSV layout is not supported."


def test_decode_error(tmp_path):
    with pytest.raises(ExtractionError) as e:
        _parse(tmp_path, "", raw=b"field,value\n\xff\xfe,1\n")
    assert e.value.code == "csv_decode_error"


def test_field_value_issues(tmp_path):
    x = _parse(
        tmp_path,
        "Field , Value\nquantity,5\nVendor, A \nvendor,B\nbogus,1\ntax_rate,0.06\n"
        "currency,\nitem,W\n",
    )
    codes = [i.code for i in x.issues]
    assert codes.count("malformed_row") == 1
    assert "duplicate_field" in codes and "unrecognized_field" in codes
    assert x.vendor_raw == "A"
    assert x.tax_rate_fraction_raw == "0.06" and x.currency_raw is None
    assert lines(x) == [("W", None, None)]


def test_row_table_footers_and_extra_currency(tmp_path):
    x = _parse(
        tmp_path,
        HEADER.strip() + ",Currency\n"
        "INV-1,A,2026-01-01,2026-02-01,W,1,1.00,1.00,USD\n"
        ",,,,,,Shipping:,5.00\n"
        ",,,,,,Tax:,0.50\n"
        ",,,,,,Weird:,1\n"
        ",,,,,,,9\n",
    )
    assert x.currency_raw == "USD" and x.shipping_raw == "5.00" and x.tax_raw == "0.50"
    assert [i.code for i in x.issues] == ["unparsed_line", "unparsed_line"]


def test_registered_and_dispatch():
    assert PARSER_VERSIONS[next(k for k in PARSER_VERSIONS if k.value == "csv")] == "csv-1"
    src, data = read_source("data/invoices/invoice_1006.csv")
    assert len(parse_document(src, data, DEFAULT_LIMITS).draft.lines) == 2
