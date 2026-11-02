from invoice_processing.intake import read_source
from invoice_processing.parsers.text import parse_lines
from invoice_processing.parsers.txt import parse_txt


def draft(name):
    return parse_txt(*read_source(f"data/invoices/{name}"))


def aliases(d):
    return {
        (e.field, e.raw_value) for e in d.normalization_events if e.provenance == "rule:label_alias"
    }


def test_1002_misspelled_labels():
    d = draft("invoice_1002.txt")
    assert (d.vendor_raw, d.invoice_number_raw) == ("Gadgets Co.", "1002")
    assert (d.invoice_date_raw, d.due_date_raw, d.total_raw) == (
        "Jan 30 2026",
        "2026-01-30",
        "$15,000.00",
    )
    assert d.payment_terms_raw == "Net 30"
    assert [(x.raw_name, x.quantity_raw, x.unit_price_raw) for x in d.lines] == [
        ("GadgetX", "20", "$750")
    ]
    assert aliases(d) == {
        ("vendor", "Vndr"),
        ("invoice_number", "Inv #"),
        ("invoice_date", "Dt"),
        ("due_date", "Due Dt"),
        ("total", "Amt"),
        ("payment_terms", "Pymnt Terms"),
    }
    assert d.field_evidence["vendor"][0].location == "line:3"


def test_1001_has_no_aliases():
    assert aliases(draft("invoice_1001.txt")) == set()


def test_1003_notes_and_relative_due_date():
    d = draft("invoice_1003.txt")
    assert [(x.raw_name, x.quantity_raw, x.unit_price_raw) for x in d.lines] == [
        ("FakeItem", "100", "$1,000.00")
    ]
    assert d.total_raw == "$100,000.00" and d.due_date_raw == "yesterday"
    assert d.notes_raw == "URGENT - Pay immediately to avoid penalties!!! Wire transfer preferred."
    assert d.payment_terms_raw == "Immediate"


def test_1008_email_body():
    d = draft("invoice_1008.txt")
    assert (d.vendor_raw, d.invoice_number_raw, d.total_raw) == (
        "NoProd Industries",
        "INV-1008",
        "$9,900.00",
    )
    assert [(x.raw_name, x.quantity_raw, x.unit_price_raw) for x in d.lines] == [
        ("SuperGizmo", "12", "$400.00"),
        ("MegaSprocket", "6", "$850.00"),
    ]
    assert all("@" not in (e.snippet or "") for e in d.field_evidence["vendor"])
    assert any("@" in (e.snippet or "") for e in d.evidence)


def test_from_without_address_is_vendor():
    d = parse_lines(
        "s", [("line:1", "FROM:  QuickShip Distributers"), ("line:2", "  (formerly FastShip Ltd.)")]
    )
    assert d.vendor_raw == "QuickShip Distributers"
    assert [e.location for e in d.field_evidence["vendor"]] == ["line:1", "line:2"]
    assert d.issues == []


def test_repeated_label_is_duplicate_field_first_wins():
    d = parse_lines("s", [("line:1", "Vendor: A Co."), ("line:2", "Vendor: B Co.")])
    assert d.vendor_raw == "A Co."
    assert [i.code for i in d.issues] == ["duplicate_field"]
    assert len(d.issues[0].evidence) == 2


def test_title_invoice_number_and_tax_rate():
    d = parse_lines("s", [("line:1", "INVOICE #1005"), ("line:2", "Tax (5%): $5.00")])
    assert (d.invoice_number_raw, d.tax_raw, d.tax_rate_raw) == ("1005", "$5.00", "5")
    assert ("invoice_number", "INVOICE #") in aliases(d)
    assert "tax_rate" in d.field_evidence


def test_unknown_label_is_unparsed():
    d = parse_lines("s", [("line:1", "Mystery: x")])
    assert [i.code for i in d.issues] == ["unparsed_line"]


def test_every_value_has_line_evidence():
    for name in ("invoice_1002.txt", "invoice_1003.txt", "invoice_1008.txt"):
        d = draft(name)
        assert all(x.evidence[0].location.startswith("line:") for x in d.lines)
        assert all(
            refs and refs[0].location.startswith("line:") for refs in d.field_evidence.values()
        )
