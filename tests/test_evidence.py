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


def test_claimed_by_other_subtotal_line_for_total():
    inv = _invoice({"subtotal": ["line:12"], "total": ["line:14"]}, [["line:9"], ["line:10"]])
    assert evidence.claimed_by_other("stated.total", "line:12", inv) is True
    assert evidence.claimed_by_other("stated.total", "line:14", inv) is False
    assert evidence.claimed_by_other("stated.subtotal", "line:12", inv) is False
    assert evidence.claimed_by_other("stated.total", "line:9", inv) is True  # a line's evidence
    assert evidence.claimed_by_other("lines[0].quantity", "line:9", inv) is False
    assert evidence.claimed_by_other("lines[1].quantity", "line:9", inv) is True
    assert evidence.claimed_by_other("due_date", "line:30", inv) is False  # nobody's


def test_claimed_by_other_json_and_xml_paths_match_by_prefix():
    inv = _invoice(
        {"subtotal": ["$.subtotal"], "total": ["$.total"], "vendor": ["/invoice/header/vendor"]},
        [["$.line_items[0]"], ["$.line_items[1]"]],
    )
    assert evidence.claimed_by_other("stated.total", "$.subtotal", inv) is True
    assert evidence.claimed_by_other("stated.total", "$.total", inv) is False
    assert evidence.claimed_by_other("stated.total", "$.line_items[0].amount", inv) is True
    assert evidence.claimed_by_other("lines[0].line_total", "$.line_items[0].amount", inv) is False
    assert evidence.claimed_by_other("lines[0].line_total", "$.line_items[1].amount", inv) is True
    assert evidence.claimed_by_other("stated.total", "$", inv) is True  # contains every field
    assert evidence.claimed_by_other("stated.total", "$.subtotal_note", inv) is False
    assert evidence.claimed_by_other("invoice_number", "/invoice/header/vendor", inv) is True
    assert evidence.claimed_by_other("vendor", "/invoice/header/vendor", inv) is False


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
