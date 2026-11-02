import pytest

from invoice_processing.intake import read_source
from invoice_processing.limits import DEFAULT_LIMITS
from invoice_processing.parsers import PARSER_VERSIONS, parse_document
from invoice_processing.parsers.base import ExtractionError
from invoice_processing.parsers.json_parser import parse_json


def d(name):
    return parse_json(*read_source(f"data/invoices/{name}"))


def _parse(tmp_path, text, name="a.json"):
    p = tmp_path / name
    p.write_text(text)
    return parse_json(*read_source(p))


def test_all_json_fixtures_parse():
    for n in ("1004", "1004_revised", "1005", "1009", "1013", "1016"):
        d(f"invoice_{n}.json")


def test_1013_lines_notes_and_exact_total():
    x = d("invoice_1013.json")
    assert len(x.lines) == 8 and x.total_raw == "22562.80"
    assert [ln.note for ln in x.lines] == [
        None,
        None,
        None,
        "Volume discount",
        "Volume discount",
        "Expedited",
        "Replacement",
        "Sample",
    ]
    assert x.lines[3].evidence[0].location.startswith("$.line_items[3]")
    assert x.tax_rate_fraction_raw == "0.07" and x.tax_rate_raw is None
    assert x.vendor_raw == "Atlas Industrial Supply"
    assert x.field_evidence["total"][0].location == "$.total"
    assert x.field_evidence["vendor"][0].location == "$.vendor.name"
    assert x.issues == []


def test_revision():
    assert d("invoice_1004_revised.json").revision_raw == "R1"
    assert d("invoice_1004.json").revision_raw is None


def test_1009_missing_and_invalid_values_kept():
    x = d("invoice_1009.json")
    assert x.vendor_raw is None and x.due_date_raw is None and x.payment_terms_raw is None
    assert x.lines[0].quantity_raw == "-5" and x.total_raw == "-250.00"


def test_duplicate_and_unknown_keys(tmp_path):
    x = _parse(tmp_path, '{"invoice_number": "A", "invoice_number": "B", "po": "X"}')
    assert x.invoice_number_raw == "A"
    assert sorted(i.code for i in x.issues) == ["duplicate_field", "unrecognized_field"]
    dup = next(i for i in x.issues if i.code == "duplicate_field")
    assert dup.evidence[0].location == "$.invoice_number"


def test_nested_duplicate_key_uses_real_path(tmp_path):
    x = _parse(
        tmp_path,
        '{"line_items": [{"item": "A", "quantity": 1}, {"item": "B", "quantity": 2},'
        ' {"item": "C", "quantity": 3, "quantity": 9}], "vendor": {"name": "V", "name": "W"}}',
    )
    assert x.lines[2].quantity_raw == "3" and x.vendor_raw == "V"
    locs = sorted(i.evidence[0].location for i in x.issues if i.code == "duplicate_field")
    assert locs == ["$.line_items[2].quantity", "$.vendor.name"]


def test_invalid_json(tmp_path):
    with pytest.raises(ExtractionError) as e:
        _parse(tmp_path, "{nope")
    assert e.value.code == "json_invalid"


def test_top_level_not_object(tmp_path):
    with pytest.raises(ExtractionError) as e:
        _parse(tmp_path, "[1]")
    assert e.value.code == "json_invalid"


def test_invalid_utf8(tmp_path):
    p = tmp_path / "u.json"
    p.write_bytes(b'{"vendor": "\xff"}')
    with pytest.raises(ExtractionError) as e:
        parse_json(*read_source(p))
    assert e.value.code == "json_invalid"


def test_empty_null_and_wrong_types(tmp_path):
    x = _parse(
        tmp_path,
        '{"vendor": "", "currency": null, "total": true, "notes": ["a"], "subtotal": 1.50,'
        ' "line_items": [{"item": "W", "quantity": 3, "unit_price": {"a": 1}, "extra": 1}]}',
    )
    assert x.vendor_raw is None and x.currency_raw is None
    assert x.total_raw is None and x.notes_raw is None
    assert x.subtotal_raw == "1.50"
    assert x.lines[0].quantity_raw == "3" and x.lines[0].unit_price_raw is None
    issues = [(i.code, i.evidence[0].location) for i in x.issues]
    assert ("malformed_row", "$.total") in issues
    assert ("malformed_row", "$.notes") in issues
    assert ("malformed_row", "$.line_items[0].unit_price") in issues
    assert ("unrecognized_field", "$.line_items[0].extra") in issues


def test_line_items_not_list_and_vendor_string_and_aliases(tmp_path):
    x = _parse(
        tmp_path,
        '{"vendor": "Acme", "invoice_date": "2026-01-01", "tax": 5, "line_items": {"a": 1}}',
    )
    assert x.lines == [] and x.vendor_raw == "Acme"
    assert x.invoice_date_raw == "2026-01-01" and x.tax_raw == "5"
    assert [i.code for i in x.issues] == ["malformed_row"]


def test_dispatch_registered():
    source, data = read_source("data/invoices/invoice_1013.json")
    assert PARSER_VERSIONS[source.format] == source.parser_version == "json-1"
    assert parse_document(source, data, DEFAULT_LIMITS).draft.total_raw == "22562.80"


def test_identical_repeated_key_is_not_duplicate_field(tmp_path):
    x = _parse(tmp_path, '{"invoice_number": "A 1", "invoice_number": "A  1", "total": 5}')
    assert x.invoice_number_raw == "A 1" and x.issues == []


@pytest.mark.parametrize(
    ("first", "second", "field"),
    [("date", "invoice_date", "invoice_date"), ("tax_amount", "tax", "tax")],
)
def test_alternate_keys_conflict_is_duplicate_field(tmp_path, first, second, field):
    x = _parse(tmp_path, f'{{"{first}": "1", "{second}": "2"}}')
    assert getattr(x, f"{field}_raw") == "1"
    assert [(i.code, i.evidence[0].location) for i in x.issues] == [
        ("duplicate_field", f"$.{second}")
    ]
    same = _parse(tmp_path, f'{{"{first}": "1", "{second}": "1"}}')
    assert same.issues == []
