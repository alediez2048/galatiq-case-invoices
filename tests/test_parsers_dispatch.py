from invoice_processing.codes import SourceFormat
from invoice_processing.intake import read_source
from invoice_processing.limits import DEFAULT_LIMITS, Limits
from invoice_processing.parsers import PARSER_VERSIONS, ParsedDocument, parse_document


def test_limits_defaults():
    assert DEFAULT_LIMITS == Limits(max_bytes=10 * 1024 * 1024, max_pdf_pages=25, max_lines=200)


def test_dispatch_txt():
    source, data = read_source("data/invoices/invoice_1001.txt")
    parsed = parse_document(source, data, DEFAULT_LIMITS)
    assert isinstance(parsed, ParsedDocument)
    assert parsed.draft.vendor_raw == "Widgets Inc."
    assert PARSER_VERSIONS[SourceFormat.txt] == source.parser_version == "txt-2"


def test_every_format_has_a_registered_parser():
    assert set(PARSER_VERSIONS) == set(SourceFormat)
