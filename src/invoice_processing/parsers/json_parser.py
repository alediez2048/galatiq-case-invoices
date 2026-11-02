"""JSON invoice parser. Numbers are parsed as Decimal so money never passes through float."""

import json
from decimal import Decimal
from typing import Any

from invoice_processing.codes import FindingCode
from invoice_processing.parsers.base import ExtractionError
from invoice_processing.schemas import (
    DraftLine,
    EvidenceRef,
    ExtractionIssue,
    InvoiceDraft,
    SourceDocument,
)

PARSER_VERSION = "json-1"

# draft field -> accepted top-level keys, in priority order.
_TOP_FIELDS: dict[str, tuple[str, ...]] = {
    "invoice_number": ("invoice_number",),
    "revision": ("revision",),
    "invoice_date": ("date", "invoice_date"),
    "due_date": ("due_date",),
    "currency": ("currency",),
    "subtotal": ("subtotal",),
    "tax_rate_fraction": ("tax_rate",),
    "tax": ("tax_amount", "tax"),
    "shipping": ("shipping",),
    "total": ("total",),
    "payment_terms": ("payment_terms",),
    "notes": ("notes",),
}
_LINE_FIELDS = {
    "raw_name": "item",
    "quantity_raw": "quantity",
    "unit_price_raw": "unit_price",
    "line_total_raw": "amount",
    "note": "note",
}
_KNOWN_TOP = {k for keys in _TOP_FIELDS.values() for k in keys} | {"vendor", "line_items"}
_ABSENT = object()


def _reject_constant(name: str) -> Any:
    raise ValueError(f"{name} is not valid JSON")


def parse_json(source: SourceDocument, data: bytes) -> InvoiceDraft:
    duplicates: list[str] = []

    def pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in pairs:
            if key in out:
                duplicates.append(key)
            else:
                out[key] = value
        return out

    try:
        text = data.decode("utf-8-sig", errors="strict")
        doc = json.loads(
            text,
            parse_float=Decimal,
            parse_int=Decimal,
            parse_constant=_reject_constant,
            object_pairs_hook=pairs_hook,
        )
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise ExtractionError("json_invalid", f"The JSON file could not be parsed: {exc}.") from exc
    if not isinstance(doc, dict):
        raise ExtractionError(
            "json_invalid", "The JSON file could not be parsed: top level is not an object."
        )

    draft = InvoiceDraft(source_id=source.source_id)

    def ref(path: str, value: Any) -> EvidenceRef:
        return EvidenceRef(source_id=source.source_id, location=path, snippet=_snippet(value))

    def issue(code: FindingCode, message: str, path: str, value: Any = None) -> None:
        draft.issues.append(
            ExtractionIssue(code=code, message=message, evidence=[ref(path, value)])
        )

    def scalar(value: Any, path: str) -> str | None:
        """Raw string for a scalar, None when absent/empty, malformed_row for non-scalars."""
        if value is None:
            return None
        if isinstance(value, bool) or isinstance(value, (list, dict)):
            issue("malformed_row", f"Expected a single value at {path}.", path, value)
            return None
        text = str(value)
        return text if text.strip() else None

    for key in dict.fromkeys(duplicates):
        issue(
            "duplicate_field", f"Key '{key}' appears more than once; the first value is used.", key
        )
        draft.issues[-1].evidence[0].location = f"$.{key}"

    for field, keys in _TOP_FIELDS.items():
        for key in keys:
            if key not in doc:
                continue
            path = f"$.{key}"
            value = scalar(doc[key], path)
            if value is None:
                continue
            setattr(draft, f"{field}_raw", value)
            draft.field_evidence.setdefault(field, []).append(ref(path, doc[key]))
            break

    _vendor(doc, draft, scalar, ref)
    _lines(doc, draft, scalar, issue)

    for key in doc:
        if key not in _KNOWN_TOP:
            issue("unrecognized_field", f"Unrecognized key '{key}'.", f"$.{key}", doc[key])
    return draft


def _vendor(doc: dict[str, Any], draft: InvoiceDraft, scalar, ref) -> None:
    if "vendor" not in doc:
        return
    vendor = doc["vendor"]
    if isinstance(vendor, dict):
        name = vendor.get("name", _ABSENT)
        if name is not _ABSENT:
            value = scalar(name, "$.vendor.name")
            if value is not None:
                draft.vendor_raw = value
                draft.field_evidence.setdefault("vendor", []).append(ref("$.vendor.name", name))
        if vendor.get("address") not in (None, ""):
            draft.evidence.append(ref("$.vendor.address", vendor["address"]))
        return
    value = scalar(vendor, "$.vendor")
    if value is not None:
        draft.vendor_raw = value
        draft.field_evidence.setdefault("vendor", []).append(ref("$.vendor", vendor))


def _lines(doc: dict[str, Any], draft: InvoiceDraft, scalar, issue) -> None:
    if "line_items" not in doc:
        return
    items = doc["line_items"]
    if not isinstance(items, list):
        issue("malformed_row", "line_items must be a list.", "$.line_items", items)
        return
    known = set(_LINE_FIELDS.values())
    for i, item in enumerate(items):
        base = f"$.line_items[{i}]"
        if not isinstance(item, dict):
            issue("malformed_row", f"Line item {i} is not an object.", base, item)
            continue
        values = {
            attr: scalar(item.get(key), f"{base}.{key}") for attr, key in _LINE_FIELDS.items()
        }
        draft.lines.append(
            DraftLine(
                **values,
                evidence=[EvidenceRef(source_id=draft.source_id, location=base)],
            )
        )
        for key in item:
            if key not in known:
                issue(
                    "unrecognized_field", f"Unrecognized key '{key}'.", f"{base}.{key}", item[key]
                )


def _snippet(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (list, dict)):
        return None
    return str(value)
