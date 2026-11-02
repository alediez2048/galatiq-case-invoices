"""Parser for the Phase 1 plain-text invoice layout. Values stay raw strings."""

import re

from invoice_processing.codes import FindingCode
from invoice_processing.parsers.base import ExtractionError
from invoice_processing.schemas import (
    DraftLine,
    EvidenceRef,
    ExtractionIssue,
    InvoiceDraft,
    SourceDocument,
)

PARSER_VERSION = "txt-2"

__all__ = ["PARSER_VERSION", "ExtractionError", "parse_txt"]

_FIELDS = {
    "Vendor": "vendor_raw",
    "Invoice Number": "invoice_number_raw",
    "Date": "invoice_date_raw",
    "Due Date": "due_date_raw",
    "Subtotal": "subtotal_raw",
    "Total Amount": "total_raw",
    "Total": "total_raw",
    "Currency": "currency_raw",
}
_IGNORED = {"Payment Terms"}
_LABELED = re.compile(r"^(?P<label>[^:]+?)\s*:\s*(?P<value>.*)$")
_TAX_LABEL = re.compile(r"^Tax \((?P<rate>[^%()]*)%\)$")
_ITEM = re.compile(r"^\s*(?P<name>\S+)\s+qty:\s*(?P<qty>\S+)\s+unit price:\s*(?P<price>\S+)\s*$")


def parse_txt(source: SourceDocument, data: bytes) -> InvoiceDraft:
    try:
        text = data.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as exc:
        raise ExtractionError("txt_decode_error", f"not valid UTF-8: {exc}") from exc

    draft = InvoiceDraft(source_id=source.source_id)
    in_items = False
    for number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        ref = EvidenceRef(source_id=source.source_id, location=f"line:{number}", snippet=line)
        if not line:
            in_items = False
            continue
        if in_items:
            match = _ITEM.match(line)
            if match:
                draft.lines.append(
                    DraftLine(
                        raw_name=match["name"],
                        quantity_raw=match["qty"],
                        unit_price_raw=match["price"],
                        evidence=[ref],
                    )
                )
            else:
                _unparsed(draft, ref)
            continue
        if line == "INVOICE":
            continue
        labeled = _LABELED.match(line)
        if not labeled:
            _unparsed(draft, ref)
            continue
        label, value = labeled["label"], labeled["value"].strip()
        tax = _TAX_LABEL.match(label)
        if label == "Items":
            in_items = True
        elif label in _IGNORED:
            pass
        elif label in _FIELDS:
            setattr(draft, _FIELDS[label], value)
            draft.evidence.append(ref)
        elif tax:
            draft.tax_rate_raw = tax["rate"].strip()
            draft.tax_raw = value
            draft.evidence.append(ref)
        else:
            _unparsed(draft, ref)
    return draft


def _unparsed(draft: InvoiceDraft, ref: EvidenceRef) -> None:
    draft.issues.append(
        ExtractionIssue(
            code=FindingCode.unparsed_line, message="line not recognized", evidence=[ref]
        )
    )
