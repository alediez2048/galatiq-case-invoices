"""XML invoice parser. DTDs, entities and external references are refused outright."""

from collections.abc import Iterator
from xml.etree.ElementTree import Element, ParseError

from defusedxml import DTDForbidden, EntitiesForbidden, ExternalReferenceForbidden
from defusedxml.ElementTree import fromstring

from invoice_processing.codes import FindingCode
from invoice_processing.parsers.base import ExtractionError
from invoice_processing.schemas import (
    DraftLine,
    EvidenceRef,
    ExtractionIssue,
    InvoiceDraft,
    SourceDocument,
)

PARSER_VERSION = "xml-1"

_HEADER: dict[str, str] = {
    "invoice_number": "invoice_number",
    "revision": "revision",
    "vendor": "vendor",
    "date": "invoice_date",
    "due_date": "due_date",
    "currency": "currency",
}
_TOTALS: dict[str, str] = {
    "subtotal": "subtotal",
    "tax_rate": "tax_rate_fraction",
    "tax_amount": "tax",
    "shipping": "shipping",
    "total": "total",
}
_ROOT_ONLY: dict[str, str] = {"payment_terms": "payment_terms", "notes": "notes"}
_LINE_FIELDS = {
    "raw_name": "name",
    "quantity_raw": "quantity",
    "unit_price_raw": "unit_price",
    "line_total_raw": "amount",
    "note": "note",
}


def parse_xml(source: SourceDocument, data: bytes) -> InvoiceDraft:
    try:
        root = fromstring(data, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except (DTDForbidden, EntitiesForbidden, ExternalReferenceForbidden) as exc:
        raise ExtractionError(
            "xml_forbidden_construct", "This XML uses DTDs or entities, which are not allowed."
        ) from exc
    except (ParseError, ValueError) as exc:
        raise ExtractionError("xml_invalid", f"The XML file could not be parsed: {exc}.") from exc
    if root.tag != "invoice":
        raise ExtractionError("xml_invalid", "The XML root element must be <invoice>.")

    draft = InvoiceDraft(source_id=source.source_id)
    flat = {**_HEADER, **_TOTALS, **_ROOT_ONLY}

    def ref(path: str, text: str | None = None) -> EvidenceRef:
        return EvidenceRef(source_id=source.source_id, location=path, snippet=text)

    def issue(code: FindingCode, message: str, path: str, text: str | None = None) -> None:
        draft.issues.append(ExtractionIssue(code=code, message=message, evidence=[ref(path, text)]))

    def text_of(el: Element, path: str) -> str | None:
        if len(el):
            issue("malformed_row", f"Expected a single value at {path}.", path)
            return None
        text = (el.text or "").strip()
        return text or None

    def set_field(field: str, el: Element, path: str, seen: set[str]) -> None:
        text = text_of(el, path)
        if field in seen:
            issue(
                "duplicate_field",
                f"Element '{el.tag}' appears more than once; the first value is used.",
                path,
                text,
            )
            return
        seen.add(field)
        if text is None:
            return
        setattr(draft, f"{field}_raw", text)
        draft.field_evidence.setdefault(field, []).append(ref(path, text))

    seen: set[str] = set()

    for child, path in _children(root, "/invoice"):
        tag = child.tag
        if tag in flat:
            set_field(flat[tag], child, path, seen)
        elif tag == "header" or tag == "totals":
            table = _HEADER if tag == "header" else _TOTALS
            for el, el_path in _children(child, path):
                if el.tag in table:
                    set_field(table[el.tag], el, el_path, seen)
                else:
                    issue("unrecognized_field", f"Unrecognized element '{el.tag}'.", el_path)
        elif tag == "line_items":
            for item, item_path in _children(child, path):
                if item.tag != "item":
                    issue("unrecognized_field", f"Unrecognized element '{item.tag}'.", item_path)
                    continue
                _line(draft, item, item_path, text_of, issue)
        else:
            issue("unrecognized_field", f"Unrecognized element '{tag}'.", path)
    return draft


def _children(parent: Element, parent_path: str) -> Iterator[tuple[Element, str]]:
    """Yield (child, path); an index appears only among repeated same-tag siblings."""
    counts: dict[str, int] = {}
    for child in parent:
        counts[child.tag] = counts.get(child.tag, 0) + 1
    position: dict[str, int] = {}
    for child in parent:
        position[child.tag] = position.get(child.tag, 0) + 1
        suffix = f"[{position[child.tag]}]" if counts[child.tag] > 1 else ""
        yield child, f"{parent_path}/{child.tag}{suffix}"


def _line(draft, item, item_path, text_of, issue) -> None:
    values: dict[str, str | None] = {attr: None for attr in _LINE_FIELDS}
    taken: set[str] = set()
    for el, path in _children(item, item_path):
        attr = next((a for a, tag in _LINE_FIELDS.items() if tag == el.tag), None)
        if attr is None:
            issue("unrecognized_field", f"Unrecognized element '{el.tag}'.", path)
            continue
        text = text_of(el, path)
        if attr in taken:
            issue(
                "duplicate_field",
                f"Element '{el.tag}' appears more than once; the first value is used.",
                path,
                text,
            )
            continue
        taken.add(attr)
        values[attr] = text
    draft.lines.append(
        DraftLine(**values, evidence=[EvidenceRef(source_id=draft.source_id, location=item_path)])
    )
