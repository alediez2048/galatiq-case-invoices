"""P4-02 evidence rule: locate a cited location, who owns it, and whether it shows the value."""

import pytest

from invoice_processing import evidence
from invoice_processing.schemas import EvidenceRef, LineItem, NormalizedInvoice, StatedTotals
from invoice_processing.tools import REGISTRY, SourceExcerptArgs, ToolContext
from tests.review_helpers import INVOICES


@pytest.mark.parametrize(
    "field,value,text,ok",
    [
        ("stated.total", "3500.00", "Total Amount: $3.500,00", True),
        ("stated.total", "22512.80", '"total": 22562.80', False),
        ("stated.total", "5000.00", "Total: $5,000", True),
        ("lines[0].line_total", "3500.00", "WidgetA  7  $450.00  $3,5O0.00", True),
        ("lines[0].line_total", "350.00", "WidgetA  7  $450.00  $3,5O0.00", False),
        ("lines[0].unit_price", "12.50", "qty 1250", False),
        ("lines[0].quantity", "7", "WidgetA qty: 7 unit price: $500.00", True),
        ("due_date", "2026-03-31", "Remittance note: due date extended to 2026-03-31", True),
        ("currency", "USD", "Total: €4,125.00", False),
        ("lines[0].item", "WidgetA", "  Widget A    qty: 10", True),
    ],
)
def test_supports(field, value, text, ok):
    assert evidence.supports(field, value, text) is ok


@pytest.mark.parametrize(
    "field,value,text,ok",
    [
        ("stated.subtotal", "5000.00", "Subtotal: $5 000.00", True),  # digits split by a space
        ("lines[0].quantity", "0", "qty: 0", False),  # quantities are positive integers
        ("lines[0].quantity", "7.5", "qty: 7.5", False),
        ("invoice_date", "2026-01-15", "Date: Jan 15, 2026", True),  # two or three tokens
        ("invoice_date", "2026-01-16", "Date: Jan 15, 2026", False),
        ("currency", "EUR", "Total: €4,125.00", True),
        ("currency", "usd", "Currency: USD", True),
        ("currency", "USD", "USDX 5", False),  # a word, not part of one
        ("vendor", "Widgets Inc.", "Vendor:  widgets  INC.", True),
        ("invoice_number", "INV-1002", "Invoice Number: INV-1001", False),
        ("stated.total", "not money", "Total: $5,000.00", False),
        ("notes", "x", "x", False),  # not a correctable field kind
    ],
)
def test_supports_edges(field, value, text, ok):
    assert evidence.supports(field, value, text) is ok


def _tool_excerpt(text: str, location: str) -> str:
    ctx = ToolContext(conn=None, run_id="r", source_text=text)  # type: ignore[arg-type]
    handler = REGISTRY["get_source_excerpt"].handler
    return handler(ctx, SourceExcerptArgs(location=location))["text"]


def test_locate_matches_phase3_tool_excerpts():
    txt = (INVOICES / "invoice_1001.txt").read_text()
    js = (INVOICES / "invoice_1013.json").read_text()
    assert evidence.locate(txt, "line:9") == _tool_excerpt(txt, "line:9")
    assert evidence.locate(txt, "line:9").strip().startswith("WidgetA")
    assert evidence.locate(js, "$.total") == _tool_excerpt(js, "$.total") == "22562.8"
    for bad in ("line:999", "nonsense", "$.nope", "/invoice", "row:99"):
        assert evidence.locate(txt, bad) is None


def _ref(location: str) -> EvidenceRef:
    return EvidenceRef(source_id="s", location=location)


def _invoice(field_evidence: dict[str, list[str]], lines: list[list[str]]) -> NormalizedInvoice:
    return NormalizedInvoice(
        source_id="s",
        lines=[LineItem(evidence=[_ref(loc) for loc in locs]) for locs in lines],
        stated=StatedTotals(),
        field_evidence={k: [_ref(loc) for loc in locs] for k, locs in field_evidence.items()},
    )


LINES = "\n".join(f"source line {i}" for i in range(1, 41))  # 40 plain text lines


def test_claimed_by_other_subtotal_line_for_total():
    inv = _invoice({"subtotal": ["line:12"], "total": ["line:14"]}, [["line:9"], ["line:10"]])
    assert evidence.claimed_by_other("stated.total", "line:12", inv, LINES) is True
    assert evidence.claimed_by_other("stated.total", "line:14", inv, LINES) is False
    assert evidence.claimed_by_other("stated.subtotal", "line:12", inv, LINES) is False
    assert (
        evidence.claimed_by_other("stated.total", "line:9", inv, LINES) is True
    )  # a line's evidence
    assert evidence.claimed_by_other("lines[0].quantity", "line:9", inv, LINES) is False
    assert evidence.claimed_by_other("lines[1].quantity", "line:9", inv, LINES) is True
    assert evidence.claimed_by_other("due_date", "line:30", inv, LINES) is False  # nobody's


def test_claimed_by_other_json_and_xml_paths_match_by_prefix():
    inv = _invoice(
        {"subtotal": ["$.subtotal"], "total": ["$.total"], "vendor": ["/invoice/header/vendor"]},
        [["$.line_items[0]"], ["$.line_items[1]"]],
    )
    assert evidence.claimed_by_other("stated.total", "$.subtotal", inv, LINES) is True
    assert evidence.claimed_by_other("stated.total", "$.total", inv, LINES) is False
    assert evidence.claimed_by_other("stated.total", "$.line_items[0].amount", inv, LINES) is True
    assert (
        evidence.claimed_by_other("lines[0].line_total", "$.line_items[0].amount", inv, LINES)
        is False
    )
    assert (
        evidence.claimed_by_other("lines[0].line_total", "$.line_items[1].amount", inv, LINES)
        is True
    )
    assert (
        evidence.claimed_by_other("stated.total", "$", inv, LINES) is True
    )  # contains every field
    assert evidence.claimed_by_other("stated.total", "$.subtotal_note", inv, LINES) is False
    assert evidence.claimed_by_other("invoice_number", "/invoice/header/vendor", inv, LINES) is True
    assert evidence.claimed_by_other("vendor", "/invoice/header/vendor", inv, LINES) is False


@pytest.mark.parametrize(
    "field,value,text,ok",
    [
        ("stated.total", "5050.00", "5050.0", True),  # json.dumps of a JSON number
        ("stated.total", "22562.80", "22562.8", True),
        ("stated.total", "22512.80", "22562.8", False),
        ("stated.total", "5050.00", '"5050.00"', True),  # a JSON string scalar
        ("stated.total", "4125.00", "4125.00", True),  # an XML element's text
        ("stated.total", "412.50", "4125.00", False),
        ("stated.total", "5050.00", '{"amount": 5050.0}', False),  # not a scalar
        ("lines[0].unit_price", "250.00", "250", True),
    ],
)
def test_supports_structured_money_compares_numbers(field, value, text, ok):
    assert evidence.supports(field, value, text, structured=True) is ok


def test_structured_rule_only_for_json_and_xml_paths():
    assert evidence.is_structured("$.total") and evidence.is_structured("/invoice/totals/total")
    assert not evidence.is_structured("line:13") and not evidence.is_structured("row:2")
    # the text-format token rule still reads a one-digit tail as whole units
    assert evidence.supports("stated.total", "5050.00", "Total: 5050.0") is False


def test_ocr_fix_only_for_numbers_and_dates():
    assert evidence.supports("vendor", "ACME CO.", "Vendor: ACME CO.") is True
    assert evidence.supports("lines[0].item", "WidgetO", "WidgetO, 2") is True
    assert evidence.supports("currency", "USD", "Currency: USD") is True
    assert evidence.supports("lines[0].quantity", "10", "qty: 1O") is True
    assert evidence.supports("due_date", "2026-03-10", "Due: 2026-03-1O") is True


TXT = "INVOICE\nVendor: A\nSubtotal: $5,000.00\nTotal: $5,050.00\n"
PAGED = "INVOICE\nVendor: A\n\f\nSubtotal: $5,000.00\nTotal: $5,050.00"  # two PDF pages


@pytest.mark.parametrize(
    "location,text,canonical",
    [
        ("line:3", TXT, "line:3"),
        ("line:003", TXT, "line:3"),
        ("page:1,line:3", TXT, "line:3"),  # non-paged text has no page
        ("page:01,line:03", TXT, "line:3"),
        ("page:2,line:1", TXT, None),
        ("line:99", TXT, None),
        ("line:0", TXT, None),
        ("page:2,line:1", PAGED, "page:2,line:1"),
        ("page:002,line:01", PAGED, "page:2,line:1"),
        ("page:1,line:2", PAGED, "page:1,line:2"),
        ("line:2", PAGED, "page:1,line:2"),  # a whole-text line maps to its page
        ("line:5", PAGED, "page:2,line:1"),
        ("line:3", PAGED, None),  # the page break itself is no source line
        ("row:3", "", "row:3"),
        ("row:03,col:total", "", "row:3"),
        ("$.total", "", "$.total"),
        ("$.line_items[00].amount", "", "$.line_items[0].amount"),
        ("$", "", "$"),
        ("$.a..b", "", None),
        ("/invoice/totals/subtotal", "", "/invoice/totals[1]/subtotal[1]"),
        ("//invoice//totals/subtotal/", "", None),  # an empty step is not a path
        ("//invoice/totals/subtotal", "", "/invoice/totals[1]/subtotal[1]"),
        ("/invoice/totals[01]/subtotal", "", "/invoice/totals[1]/subtotal[1]"),
        ("/invoice/line_items/item[2]/name", "", "/invoice/line_items[1]/item[2]/name[1]"),
        ("nonsense", "", None),
        ("line:3\n", TXT, None),
    ],
)
def test_canonical_location(location, text, canonical):
    assert evidence.canonical_location(location, text) == canonical


def test_locate_reads_every_spelling_like_its_canonical_form():
    xml = (INVOICES / "invoice_1014.xml").read_text()
    js = (INVOICES / "invoice_1013.json").read_text()
    for a, b, text in [
        ("line:3", "page:1,line:003", TXT),
        ("page:2,line:1", "line:5", PAGED),
        ("/invoice/totals/subtotal", "//invoice/totals[1]/subtotal", xml),
        ("$.line_items[0].amount", "$.line_items[00].amount", js),
    ]:
        assert evidence.locate(text, a) == evidence.locate(text, b) is not None
    assert evidence.locate(PAGED, "line:3") is None


@pytest.mark.parametrize(
    "location",
    ["line:3", "line:03", "page:1,line:3", "page:01,line:3"],
)
def test_claimed_by_other_sees_through_line_spellings(location):
    inv = _invoice({"subtotal": ["line:3"], "total": ["line:4"]}, [])
    assert evidence.claimed_by_other("stated.total", location, inv, TXT) is True


def test_claimed_by_other_sees_through_path_and_row_spellings():
    inv = _invoice(
        {"subtotal": ["/invoice/totals/subtotal", "$.subtotal"], "total": ["row:5"]},
        [["$.line_items[0]"]],
    )
    for loc in ("//invoice/totals/subtotal", "/invoice/totals[1]/subtotal[1]"):
        assert evidence.claimed_by_other("stated.total", loc, inv, "") is True
    assert evidence.claimed_by_other("stated.total", "$.line_items[00].amount", inv, "") is True
    assert evidence.claimed_by_other("stated.subtotal", "row:05,col:x", inv, "") is True
    assert evidence.claimed_by_other("stated.total", "row:5,col:total", inv, "") is False


def test_tax_and_tax_rate_share_the_tax_line():
    # The text parser records the "Tax (8%): $40.00" line under both tax and tax_rate.
    inv = _invoice({"tax": ["line:13"], "tax_rate": ["line:13"], "total": ["line:14"]}, [])
    assert evidence.claimed_by_other("stated.tax", "line:13", inv, LINES) is False
    assert evidence.claimed_by_other("stated.total", "line:13", inv, LINES) is True
    assert evidence.claimed_by_other("stated.tax", "line:99", inv, LINES) is True  # no such line


@pytest.mark.parametrize(
    "value,text,ok",
    [
        ("-50.00", "Discount: $50.00", False),  # a negative value needs a negative amount
        ("-50.00", "Discount: -$50.00", True),
        ("-50.00", "Discount: - 50.00", True),
        ("50.00", "Discount: -$50.00", False),
        ("50.00", "Discount: $50.00", True),
        ("-5000.00", "Subtotal: $5,000.00", False),
    ],
)
def test_money_sign_must_match(value, text, ok):
    assert evidence.supports("stated.shipping", value, text) is ok


def test_structured_money_sign_must_match():
    assert evidence.supports("stated.total", "-250.00", "250.0", structured=True) is False
    assert evidence.supports("stated.total", "-250.00", "-250.0", structured=True) is True


@pytest.mark.parametrize(
    "location,fmt,ok",
    [
        ("line:12", "txt", True),
        ("page:1,line:12", "txt", False),
        ("row:12", "txt", False),
        ("page:1,line:3", "pdf", True),
        ("line:3", "pdf", False),
        ("row:3", "csv", True),
        ("row:3,col:total", "csv", True),
        ("line:3", "csv", False),
        ("$.total", "json", True),
        ("line:3", "json", False),
        ("/invoice/totals/total", "xml", True),
        ("row:3", "xml", False),
        ("$.total", "xml", False),
    ],
)
def test_scheme_matches_the_source_format(location, fmt, ok):
    from invoice_processing.codes import SourceFormat

    assert evidence.scheme_matches(location, SourceFormat(fmt)) is ok


@pytest.mark.parametrize(
    "value,text",
    [("50.00", "Credit: (50.00)"), ("50.00", "Credit: ($50.00)"), ("-50.00", "Credit: (50.00)")],
)
def test_parenthesized_amounts_are_not_evidence(value, text):
    assert evidence.supports("stated.shipping", value, text) is False
