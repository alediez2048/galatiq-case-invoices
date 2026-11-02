"""CSV invoice parsers: a field/value layout and a row-table layout."""

import csv
import io

from invoice_processing.codes import FindingCode
from invoice_processing.parsers.base import ExtractionError
from invoice_processing.schemas import (
    DraftLine,
    EvidenceRef,
    ExtractionIssue,
    InvoiceDraft,
    SourceDocument,
)

PARSER_VERSION = "csv-1"

# field/value layout: field name -> draft field
_FIELDS = {
    "invoice_number": "invoice_number",
    "vendor": "vendor",
    "date": "invoice_date",
    "invoice_date": "invoice_date",
    "due_date": "due_date",
    "currency": "currency",
    "subtotal": "subtotal",
    "tax": "tax",
    "tax_rate": "tax_rate_fraction",
    "shipping": "shipping",
    "total": "total",
    "payment_terms": "payment_terms",
    "notes": "notes",
    "revision": "revision",
}
_LINE_FIELDS = {
    "item": "raw_name",
    "quantity": "quantity_raw",
    "unit_price": "unit_price_raw",
    "amount": "line_total_raw",
    "note": "note",
}

_TABLE_HEADER = [
    "invoice number",
    "vendor",
    "date",
    "due date",
    "item",
    "qty",
    "unit price",
    "line total",
]
# column index -> draft field, for the invoice-level columns repeated on every data row
_TABLE_HEADER_FIELDS = {0: "invoice_number", 1: "vendor", 2: "invoice_date", 3: "due_date"}
_FOOTERS = {"subtotal:": "subtotal", "tax:": "tax", "shipping:": "shipping", "total:": "total"}


def parse_csv(source: SourceDocument, data: bytes) -> InvoiceDraft:
    try:
        text = data.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as exc:
        raise ExtractionError(
            "csv_decode_error", f"The CSV file is not valid UTF-8: {exc.reason}."
        ) from exc
    reader = csv.reader(io.StringIO(text, newline=""))
    try:
        rows = [(reader.line_num, row) for row in reader]
    except csv.Error as exc:
        raise ExtractionError(
            "csv_decode_error", f"The CSV file could not be read: {exc}."
        ) from exc
    rows = [(n, row) for n, row in rows if any(c.strip() for c in row)]
    header = [c.strip().casefold() for c in rows[0][1]] if rows else []
    draft = InvoiceDraft(source_id=source.source_id)
    if header == ["field", "value"]:
        _field_value(draft, rows[1:])
    elif header[:8] == _TABLE_HEADER and header[8:] in ([], ["currency"]):
        _row_table(draft, rows[0][1], rows[1:])
    else:
        raise ExtractionError("unsupported_csv_layout", "This CSV layout is not supported.")
    return draft


def _clean(cell: str | None) -> str | None:
    text = (cell or "").strip()
    return text or None


def _ref(draft: InvoiceDraft, location: str, snippet: str | None) -> EvidenceRef:
    return EvidenceRef(source_id=draft.source_id, location=location, snippet=snippet)


def _issue(draft: InvoiceDraft, code: FindingCode, message: str, refs: list[EvidenceRef]) -> None:
    draft.issues.append(ExtractionIssue(code=code, message=message, evidence=refs))


def _set_field(draft: InvoiceDraft, field: str, value: str, ref: EvidenceRef) -> bool:
    """Set a header field, first value wins. Returns False when it was a duplicate."""
    if field in draft.field_evidence:
        _issue(
            draft,
            "duplicate_field",
            f"Field '{field}' appears more than once; the first value is used.",
            [ref],
        )
        return False
    setattr(draft, f"{field}_raw", value)
    draft.field_evidence[field] = [ref]
    return True


def _field_value(draft: InvoiceDraft, rows: list[tuple[int, list[str]]]) -> None:
    current: DraftLine | None = None
    for n, row in rows:
        loc = f"row:{n}"
        name = (row[0] if row else "").strip().casefold()
        value = _clean(row[1]) if len(row) > 1 else None
        ref = _ref(draft, loc, value)
        if name in _LINE_FIELDS:
            attr = _LINE_FIELDS[name]
            if name == "item":
                current = DraftLine(raw_name=value, evidence=[ref])
                draft.lines.append(current)
                continue
            if current is None:
                _issue(draft, "malformed_row", f"'{name}' appears before any item.", [ref])
                continue
            if getattr(current, attr) is None:
                setattr(current, attr, value)
            current.evidence.append(ref)
        elif name in _FIELDS:
            if value is not None:
                _set_field(draft, _FIELDS[name], value, ref)
        else:
            _issue(draft, "unrecognized_field", f"Unrecognized field '{name}'.", [ref])


def _row_table(draft: InvoiceDraft, header: list[str], rows: list[tuple[int, list[str]]]) -> None:
    names = [h.strip() for h in header]
    has_currency = len(names) > 8

    def cell(row: list[str], i: int) -> str | None:
        return _clean(row[i]) if i < len(row) else None

    def col_ref(n: int, i: int, row: list[str]) -> EvidenceRef:
        return _ref(draft, f"row:{n},col:{names[i]}", cell(row, i))

    first: dict[int, tuple[int, str]] = {}  # invoice-level column -> (row number, value)
    invoice_cols = dict(_TABLE_HEADER_FIELDS)
    if has_currency:
        invoice_cols[8] = "currency"
    for n, row in rows:
        if cell(row, 4) is None:
            _footer(draft, n, row, cell, col_ref)
            continue
        for i, field in invoice_cols.items():
            value = cell(row, i)
            if value is None:
                continue
            if i not in first:
                first[i] = (n, value)
                _set_field(draft, field, value, col_ref(n, i, row))
            elif value != first[i][1]:
                _issue(
                    draft,
                    "inconsistent_row_header",
                    f"Column '{names[i]}' differs between rows {first[i][0]} and {n}; "
                    "the first value is kept.",
                    [
                        _ref(draft, f"row:{first[i][0]},col:{names[i]}", first[i][1]),
                        col_ref(n, i, row),
                    ],
                )
        draft.lines.append(
            DraftLine(
                raw_name=cell(row, 4),
                quantity_raw=cell(row, 5),
                unit_price_raw=cell(row, 6),
                line_total_raw=cell(row, 7),
                evidence=[_ref(draft, f"row:{n}", None)],
            )
        )


def _footer(draft, n, row, cell, col_ref) -> None:
    label, value = cell(row, 6), cell(row, 7)
    leading_empty = all(cell(row, i) is None for i in range(6))
    key = (label or "").casefold()
    ref_label = col_ref(n, 6, row)
    if not leading_empty or label is None:
        _issue(draft, "unparsed_line", "Row is not an item or a recognised footer.", [ref_label])
        return
    ref = col_ref(n, 7, row)
    if key.startswith("tax (") and key.endswith("%):"):
        rate = key[5:-3].strip()
        if value is None or not rate:
            _issue(draft, "unparsed_line", "Tax footer has no usable value.", [ref_label])
            return
        _set_field(draft, "tax_rate", label.strip()[5:-3].strip(), ref_label)
        _set_field(draft, "tax", value, ref)
    elif key in _FOOTERS and value is not None:
        _set_field(draft, _FOOTERS[key], value, ref)
    else:
        _issue(draft, "unparsed_line", f"Unrecognised footer '{label}'.", [ref_label])
