"""PDF parser: pdfplumber layout text per page, then the shared text-line parser."""

import io

import pdfplumber
from pdfminer.pdfdocument import PDFPasswordIncorrect
from pdfplumber.utils.exceptions import PdfminerException

from invoice_processing.limits import Limits
from invoice_processing.parsers.base import ExtractionError, ParsedDocument
from invoice_processing.parsers.text import parse_lines
from invoice_processing.schemas import SourceDocument

PARSER_VERSION = f"pdf-1/pdfplumber-{pdfplumber.__version__}"

_CORRUPT = ExtractionError("pdf_corrupt", "This PDF is damaged and cannot be read.")


def _page_lines(text: str) -> list[str]:
    stripped = (line.rstrip() for line in text.splitlines())
    return [line for line in stripped if line]


def extract_pdf_text(data: bytes, limits: Limits) -> list[str]:
    """One string per page: layout text, right-stripped, blank lines removed."""
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            n = len(pdf.pages)
            if n > limits.max_pdf_pages:
                raise ExtractionError(
                    "too_many_pages", f"The PDF has {n} pages; the limit is {limits.max_pdf_pages}."
                )
            pages = [
                "\n".join(_page_lines(page.extract_text(layout=True) or "")) for page in pdf.pages
            ]
    except ExtractionError:
        raise
    except PdfminerException as e:
        if e.args and isinstance(e.args[0], PDFPasswordIncorrect):
            raise ExtractionError(
                "pdf_encrypted", "This PDF is password-protected and cannot be read."
            ) from e
        raise _CORRUPT from e
    except Exception as e:
        raise _CORRUPT from e
    if not any(p.strip() for p in pages):
        raise ExtractionError(
            "pdf_needs_ocr", "This PDF needs OCR, which this prototype does not support."
        )
    return pages


def parse_pdf(source: SourceDocument, data: bytes, limits: Limits) -> ParsedDocument:
    pages = extract_pdf_text(data, limits)
    lines = [
        (f"page:{p},line:{n}", line)
        for p, page in enumerate(pages, start=1)
        for n, line in enumerate(page.splitlines(), start=1)
    ]
    draft = parse_lines(source.source_id, lines)
    return ParsedDocument(draft=draft, extracted_text="\n\f\n".join(pages))


__all__ = ["PARSER_VERSION", "extract_pdf_text", "parse_pdf"]
