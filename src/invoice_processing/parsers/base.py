"""Types shared by every parser. Parsers must not import intake."""

from dataclasses import dataclass

from invoice_processing.schemas import InvoiceDraft


@dataclass
class ParsedDocument:
    draft: InvoiceDraft
    extracted_text: str | None = None


class ExtractionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
