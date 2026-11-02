"""Parser dispatch: one parser per source format, all returning raw-string drafts."""

from dataclasses import dataclass

from invoice_processing.codes import SourceFormat
from invoice_processing.limits import Limits
from invoice_processing.parsers.base import ExtractionError
from invoice_processing.parsers.json_parser import PARSER_VERSION as JSON_VERSION
from invoice_processing.parsers.json_parser import parse_json
from invoice_processing.parsers.txt import PARSER_VERSION as TXT_VERSION
from invoice_processing.parsers.txt import parse_txt
from invoice_processing.schemas import InvoiceDraft, SourceDocument

PARSER_VERSIONS: dict[SourceFormat, str] = {
    SourceFormat.txt: TXT_VERSION,
    SourceFormat.json: JSON_VERSION,
}


@dataclass
class ParsedDocument:
    draft: InvoiceDraft
    extracted_text: str | None = None


def parse_document(source: SourceDocument, data: bytes, limits: Limits) -> ParsedDocument:
    if source.format is SourceFormat.txt:
        return ParsedDocument(draft=parse_txt(source, data))
    if source.format is SourceFormat.json:
        return ParsedDocument(draft=parse_json(source, data))
    raise ExtractionError("unsupported_format", f"no parser for {source.format.value} yet")


__all__ = ["PARSER_VERSIONS", "ExtractionError", "ParsedDocument", "parse_document"]
