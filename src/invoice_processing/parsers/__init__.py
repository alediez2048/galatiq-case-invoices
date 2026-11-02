"""Parser dispatch: one parser per source format, all returning raw-string drafts."""

from invoice_processing.codes import SourceFormat
from invoice_processing.limits import Limits
from invoice_processing.parsers.base import ExtractionError, ParsedDocument
from invoice_processing.parsers.csv_parser import PARSER_VERSION as CSV_VERSION
from invoice_processing.parsers.csv_parser import parse_csv
from invoice_processing.parsers.json_parser import PARSER_VERSION as JSON_VERSION
from invoice_processing.parsers.json_parser import parse_json
from invoice_processing.parsers.pdf import PARSER_VERSION as PDF_VERSION
from invoice_processing.parsers.pdf import parse_pdf
from invoice_processing.parsers.txt import PARSER_VERSION as TXT_VERSION
from invoice_processing.parsers.txt import parse_txt
from invoice_processing.parsers.xml_parser import PARSER_VERSION as XML_VERSION
from invoice_processing.parsers.xml_parser import parse_xml
from invoice_processing.schemas import SourceDocument

PARSER_VERSIONS: dict[SourceFormat, str] = {
    SourceFormat.txt: TXT_VERSION,
    SourceFormat.json: JSON_VERSION,
    SourceFormat.csv: CSV_VERSION,
    SourceFormat.xml: XML_VERSION,
    SourceFormat.pdf: PDF_VERSION,
}


def parse_document(source: SourceDocument, data: bytes, limits: Limits) -> ParsedDocument:
    if source.format is SourceFormat.txt:
        return ParsedDocument(draft=parse_txt(source, data))
    if source.format is SourceFormat.json:
        return ParsedDocument(draft=parse_json(source, data))
    if source.format is SourceFormat.csv:
        return ParsedDocument(draft=parse_csv(source, data))
    if source.format is SourceFormat.xml:
        return ParsedDocument(draft=parse_xml(source, data))
    if source.format is SourceFormat.pdf:
        return parse_pdf(source, data, limits)
    raise ExtractionError("unsupported_format", f"no parser for {source.format.value} yet")


__all__ = ["PARSER_VERSIONS", "ExtractionError", "ParsedDocument", "parse_document"]
