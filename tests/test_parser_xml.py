import pytest

from invoice_processing.codes import SourceFormat
from invoice_processing.intake import read_source
from invoice_processing.limits import DEFAULT_LIMITS
from invoice_processing.parsers import PARSER_VERSIONS, parse_document
from invoice_processing.parsers.base import ExtractionError
from invoice_processing.parsers.xml_parser import parse_xml

BILLION_LAUGHS = (
    b'<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;">]>'
    b"<invoice>&b;</invoice>"
)
XXE = (
    b'<?xml version="1.0"?><!DOCTYPE i [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
    b"<invoice>&x;</invoice>"
)


def _parse(tmp_path, text, name="a.xml"):
    p = tmp_path / name
    p.write_bytes(text if isinstance(text, bytes) else text.encode())
    return parse_xml(*read_source(p))


def test_1014():
    x = parse_xml(*read_source("data/invoices/invoice_1014.xml"))
    assert (x.vendor_raw, x.currency_raw) == ("TechParts International", "EUR")
    assert [(ln.raw_name, ln.quantity_raw, ln.unit_price_raw) for ln in x.lines] == [
        ("WidgetA", "4", "225.00"),
        ("WidgetB", "6", "475.00"),
    ]
    assert (x.subtotal_raw, x.tax_rate_fraction_raw, x.tax_raw, x.total_raw) == (
        "3750.00",
        "0.10",
        "375.00",
        "4125.00",
    )
    assert x.lines[1].evidence[0].location == "/invoice/line_items/item[2]"
    assert x.field_evidence["vendor"][0].location == "/invoice/header/vendor"
    assert x.payment_terms_raw == "Net 30"
    assert x.issues == []


def test_registered_and_dispatched():
    assert PARSER_VERSIONS[SourceFormat.xml] == "xml-1"
    source, data = read_source("data/invoices/invoice_1014.xml")
    assert parse_document(source, data, DEFAULT_LIMITS).draft.invoice_number_raw == "INV-1014"


@pytest.mark.parametrize("payload", [BILLION_LAUGHS, XXE])
def test_forbidden_constructs(tmp_path, payload):
    with pytest.raises(ExtractionError) as e:
        _parse(tmp_path, payload)
    assert e.value.code == "xml_forbidden_construct"


def test_malformed_xml(tmp_path):
    with pytest.raises(ExtractionError) as e:
        _parse(tmp_path, "<invoice><header></invoice>")
    assert e.value.code == "xml_invalid"


def test_wrong_root(tmp_path):
    with pytest.raises(ExtractionError) as e:
        _parse(tmp_path, "<bill/>")
    assert e.value.code == "xml_invalid"


def test_duplicate_vendor_first_wins(tmp_path):
    x = _parse(
        tmp_path,
        "<invoice><header><vendor>A</vendor><vendor>B</vendor></header></invoice>",
    )
    assert x.vendor_raw == "A"
    assert [i.code for i in x.issues] == ["duplicate_field"]
    assert x.issues[0].evidence[0].location == "/invoice/header/vendor[2]"


def test_unknown_element_and_empty_text(tmp_path):
    x = _parse(
        tmp_path,
        "<invoice><header><vendor>  </vendor><colour>red</colour></header>"
        "<notes> hi </notes></invoice>",
    )
    assert x.vendor_raw is None and x.notes_raw == "hi"
    assert [i.code for i in x.issues] == ["unrecognized_field"]
    assert x.issues[0].evidence[0].location == "/invoice/header/colour"


def test_fields_directly_under_root_and_line_note(tmp_path):
    x = _parse(
        tmp_path,
        "<invoice><vendor>V</vendor><payment_terms>Net 5</payment_terms>"
        "<line_items><item><name>W</name><quantity>1</quantity><unit_price>2</unit_price>"
        "<amount>2</amount><note>n</note></item></line_items></invoice>",
    )
    assert x.vendor_raw == "V" and x.payment_terms_raw == "Net 5"
    assert x.lines[0].line_total_raw == "2" and x.lines[0].note == "n"
    assert x.lines[0].evidence[0].location == "/invoice/line_items/item"


def test_unknown_declared_encoding(tmp_path):
    with pytest.raises(ExtractionError) as e:
        _parse(tmp_path, b'<?xml version="1.0" encoding="bogus"?><invoice/>')
    assert e.value.code == "xml_invalid"


def test_empty_first_element_does_not_hide_later_value(tmp_path):
    x = _parse(
        tmp_path,
        "<invoice><header><vendor></vendor><vendor>B</vendor></header></invoice>",
    )
    assert x.vendor_raw == "B" and x.issues == []


def test_line_level_duplicate_and_unrecognized(tmp_path):
    x = _parse(
        tmp_path,
        "<invoice><line_items><item><name>A</name><name>B</name><sku>1</sku>"
        "</item></line_items></invoice>",
    )
    assert x.lines[0].raw_name == "A"
    assert [(i.code, i.evidence[0].location) for i in x.issues] == [
        ("duplicate_field", "/invoice/line_items/item/name[2]"),
        ("unrecognized_field", "/invoice/line_items/item/sku"),
    ]


def test_non_leaf_field_is_malformed_row_only_once(tmp_path):
    x = _parse(
        tmp_path,
        "<invoice><header><vendor><b>x</b></vendor><vendor><b>y</b></vendor></header></invoice>",
    )
    assert x.vendor_raw is None
    assert [i.code for i in x.issues] == ["malformed_row", "malformed_row"]
