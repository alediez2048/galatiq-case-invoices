"""Plain-text invoice parser: decode, then delegate to the shared text extractor."""

from invoice_processing.parsers.base import ExtractionError
from invoice_processing.parsers.text import parse_lines
from invoice_processing.schemas import InvoiceDraft, SourceDocument

PARSER_VERSION = "txt-2"

__all__ = ["PARSER_VERSION", "ExtractionError", "parse_txt"]


def parse_txt(source: SourceDocument, data: bytes) -> InvoiceDraft:
    try:
        text = data.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as exc:
        raise ExtractionError("txt_decode_error", f"not valid UTF-8: {exc}") from exc
    lines = [(f"line:{n}", line) for n, line in enumerate(text.splitlines(), start=1)]
    return parse_lines(source.source_id, lines)
