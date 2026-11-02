"""Types shared by every parser. Parsers must not import intake."""

from dataclasses import dataclass

from invoice_processing.schemas import InvoiceDraft


@dataclass
class ParsedDocument:
    draft: InvoiceDraft
    extracted_text: str | None = None


def same_text(a: str, b: str) -> bool:
    """True when two raw values match after whitespace collapse (a repeat, not a conflict)."""
    return " ".join(a.split()) == " ".join(b.split())


class ExtractionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
