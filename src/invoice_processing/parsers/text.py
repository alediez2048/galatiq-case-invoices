"""Label-driven extractor shared by TXT and PDF text. Values stay raw strings."""

import re

from invoice_processing.codes import FindingCode
from invoice_processing.parsers.base import same_text
from invoice_processing.schemas import (
    DraftLine,
    EvidenceRef,
    ExtractionIssue,
    InvoiceDraft,
    NormalizationEvent,
)

LABELS: dict[str, tuple[str, ...]] = {
    "vendor": ("Vendor", "Vndr", "From", "Supplier"),
    "invoice_number": (
        "Invoice Number",
        "Invoice",
        "Inv #",
        "Inv No",
        "Invoice No",
        "Invoice #",
    ),
    "invoice_date": ("Date", "Dt", "Invoice Date"),
    "due_date": ("Due Date", "Due Dt", "Due"),
    "currency": ("Currency",),
    "subtotal": ("Subtotal",),
    "tax": ("Tax", "Sales Tax"),
    "shipping": ("Shipping",),
    "total": ("Total", "Total Amount", "Amt", "Grand Total"),
    "payment_terms": ("Payment Terms", "Pymnt Terms", "Terms"),
    "notes": ("Notes",),
}
ITEM_BLOCK_LABELS = ("Items", "Itms", "Items Ordered")
IGNORED_LABELS = ("Bill To", "To", "Attn", "Ship To")
CANONICAL_LABELS = {
    "Vendor",
    "Invoice Number",
    "Date",
    "Due Date",
    "Currency",
    "Subtotal",
    "Tax",
    "Shipping",
    "Total",
    "Total Amount",
    "Payment Terms",
    "Notes",
    "Items",
}
# Canonical label reported for an aliased spelling, per field.
_CANONICAL_FOR_FIELD = {
    "vendor": "Vendor",
    "invoice_number": "Invoice Number",
    "invoice_date": "Date",
    "due_date": "Due Date",
    "currency": "Currency",
    "subtotal": "Subtotal",
    "tax": "Tax",
    "shipping": "Shipping",
    "total": "Total",
    "payment_terms": "Payment Terms",
    "notes": "Notes",
}

_LABELED = re.compile(r"^(?P<label>[^:]+?)\s*:\s*(?P<value>.*)$")
_TAX_LABEL = re.compile(r"^tax\s*\((?P<rate>[^%()]*)%\)$", re.IGNORECASE)
_TITLE_NUMBER = re.compile(r"^invoice\s*#\s*(?P<value>[^:\s][^:]*)$", re.IGNORECASE)
_EMAIL_HEADERS = ("from", "to", "cc", "subject", "date")
_ITEM_PATTERNS = (
    re.compile(
        r"^(?P<name>.+?)\s+qty:\s*(?P<qty>\S+)\s+unit price:\s*(?P<price>\S+)$", re.IGNORECASE
    ),
    re.compile(
        r"^(?P<name>.+?)\s+qty\s+(?P<qty>\S+)\s+@\s*(?P<price>\S+?)(\s+ea(ch)?)?$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^-\s*(?P<name>.+?)\s+x(?P<qty>\S+)\s+(?P<price>\S+?)(\s+ea(ch)?)?$", re.IGNORECASE
    ),
)


_TABLE_HEADER = re.compile(
    r"^(item|description)\s+(qty|quantity)\s+(unit price|rate|price)"
    r"\s+(amount|total|line total)(\s+notes)?$"
)
_SEPARATOR = re.compile(r"^[\s\-=_]+$")
_NUMERIC = re.compile(r"^-?\$?[\dO][\dO,]*(\.[\dO]+)?$")

_Entry = tuple[str, str, EvidenceRef]


def _norm(label: str) -> str:
    return " ".join(label.casefold().split())


_FIELD_BY_LABEL = {_norm(s): field for field, spellings in LABELS.items() for s in spellings}
_ITEM_LABELS = {_norm(s) for s in ITEM_BLOCK_LABELS}
_IGNORED = {_norm(s) for s in IGNORED_LABELS}
_CANONICAL = {_norm(s) for s in CANONICAL_LABELS}
_SPELLINGS = sorted({s for spellings in LABELS.values() for s in spellings}, key=len, reverse=True)
_NEXT_FIELD = re.compile(
    r"\s+(?=(?:" + "|".join(re.escape(s) for s in _SPELLINGS) + r"|Tax\s*\([^%()]*%\))\s*:)",
    re.IGNORECASE,
)


def parse_lines(source_id: str, lines: list[tuple[str, str]]) -> InvoiceDraft:
    draft = InvoiceDraft(source_id=source_id)
    entries = [
        (loc, text.strip(), EvidenceRef(source_id=source_id, location=loc, snippet=text.strip()))
        for loc, text in lines
    ]
    start = _skip_email_header(draft, entries)
    in_items = False
    in_notes = False
    in_table = False
    table_notes = False
    after_vendor = False
    for _, line, ref in entries[start:]:
        was_after_vendor, after_vendor = after_vendor, False
        if not line:
            in_items = in_notes = in_table = False
            continue
        if _SEPARATOR.match(line):
            continue
        if _TABLE_HEADER.match(_norm(line)):
            in_items = in_notes = False
            in_table = True
            table_notes = _norm(line).endswith("notes")
            draft.evidence.append(ref)
            continue
        labeled = _LABELED.match(line)
        known = labeled and _classify(labeled["label"])
        if in_table and not known:
            _table_row(draft, line, ref, table_notes)
            continue
        if known:
            in_table = False
        if in_items:
            item = _match_item(line)
            if item:
                name, qty, price = item
                draft.lines.append(
                    DraftLine(raw_name=name, quantity_raw=qty, unit_price_raw=price, evidence=[ref])
                )
                continue
        if line.casefold() == "invoice":
            continue
        title = _TITLE_NUMBER.match(line)
        if title:
            in_notes = False
            if _set_field(draft, "invoice_number", title["value"].strip(), ref):
                _alias_event(draft, "invoice_number", "INVOICE #", ref)
            continue
        if not known:
            if in_notes and not in_items:
                _append_notes(draft, line, ref)
            elif was_after_vendor and line.startswith("(") and line.endswith(")"):
                draft.evidence.append(ref)
                draft.field_evidence.setdefault("vendor", []).append(ref)
                after_vendor = False
            else:
                _unparsed(draft, ref)
            continue
        in_notes = False
        kind, field = known
        segments = [(labeled["label"].strip(), labeled["value"].strip())]
        if kind == "field" and field != "notes":
            first, *rest = _NEXT_FIELD.split(segments[0][1])
            segments = [(segments[0][0], first.strip())]
            for part in rest:
                sub = _LABELED.match(part)
                segments.append((sub["label"].strip(), sub["value"].strip()))
        for label, value in segments:
            kind, field = _classify(label)
            if kind == "items":
                in_items = True
                continue
            in_items = False
            if kind == "ignored":
                draft.evidence.append(ref)
                continue
            if not value and field != "notes":
                _unparsed(draft, ref)
                continue
            if field == "tax" and (tax := _TAX_LABEL.match(label)):
                if _set_field(draft, "tax", value, ref):
                    draft.tax_rate_raw = tax["rate"].strip()
                    draft.field_evidence.setdefault("tax_rate", []).append(ref)
                continue
            if _set_field(draft, field, value, ref):
                if _norm(label) not in _CANONICAL:
                    _alias_event(draft, field, label, ref)
                in_notes = field == "notes"
                after_vendor = field == "vendor"
    return draft


def _table_row(draft: InvoiceDraft, line: str, ref: EvidenceRef, has_notes: bool) -> None:
    """Read a column row right to left: amount, price and qty end at the last numeric token."""
    tokens = line.split()
    numeric = [i for i, t in enumerate(tokens) if _NUMERIC.match(t) and any(c.isdigit() for c in t)]
    k = numeric[-1] if numeric else -1
    note = " ".join(tokens[k + 1 :]) or None
    if k < 3 or not {k, k - 1, k - 2} <= set(numeric) or (note and not has_notes):
        draft.issues.append(
            ExtractionIssue(
                code=FindingCode.malformed_row, message="table row not understood", evidence=[ref]
            )
        )
        return
    draft.lines.append(
        DraftLine(
            raw_name=" ".join(tokens[: k - 2]),
            quantity_raw=tokens[k - 2],
            unit_price_raw=tokens[k - 1],
            line_total_raw=tokens[k],
            note=note,
            evidence=[ref],
        )
    )


def _classify(label: str) -> tuple[str, str] | None:
    key = _norm(label)
    if _TAX_LABEL.match(key):
        return "field", "tax"
    if key in _ITEM_LABELS:
        return "items", "items"
    if key in _IGNORED:
        return "ignored", "ignored"
    if key in _FIELD_BY_LABEL:
        return "field", _FIELD_BY_LABEL[key]
    return None


def _skip_email_header(draft: InvoiceDraft, entries: list[_Entry]) -> int:
    """Return the index after a leading email header block (kept as evidence only)."""
    first = next((i for i, (_, line, _) in enumerate(entries) if line), None)
    if first is None:
        return 0
    end = first
    while end < len(entries) and entries[end][1]:
        end += 1
    block = entries[first:end]
    parsed = [_LABELED.match(line) for _, line, _ in block]
    if not all(m and _norm(m["label"]) in _EMAIL_HEADERS for m in parsed):
        return 0
    if not any(_norm(m["label"]) in ("from", "to") and "@" in m["value"] for m in parsed):
        return 0
    draft.evidence.extend(ref for _, _, ref in block)
    return end


def _match_item(line: str) -> tuple[str, str, str] | None:
    for pattern in _ITEM_PATTERNS:
        m = pattern.match(line)
        if m:
            return m["name"], m["qty"], m["price"]
    return None


def _set_field(draft: InvoiceDraft, field: str, value: str, ref: EvidenceRef) -> bool:
    attr = f"{field}_raw"
    if (existing := getattr(draft, attr)) is not None:
        if same_text(existing, value):
            return False
        first = draft.field_evidence.get(field, [])[:1]
        draft.issues.append(
            ExtractionIssue(
                code=FindingCode.duplicate_field,
                message=f"field {field} appears more than once",
                evidence=[*first, ref],
            )
        )
        return False
    setattr(draft, attr, value)
    draft.evidence.append(ref)
    draft.field_evidence.setdefault(field, []).append(ref)
    return True


def _append_notes(draft: InvoiceDraft, line: str, ref: EvidenceRef) -> None:
    draft.notes_raw = f"{draft.notes_raw} {line}".strip() if draft.notes_raw else line
    draft.evidence.append(ref)
    draft.field_evidence.setdefault("notes", []).append(ref)


def _alias_event(draft: InvoiceDraft, field: str, label: str, ref: EvidenceRef) -> None:
    draft.normalization_events.append(
        NormalizationEvent(
            field=field,
            raw_value=label,
            normalized_value=_CANONICAL_FOR_FIELD[field],
            evidence=[ref],
            provenance="rule:label_alias",
        )
    )


def _unparsed(draft: InvoiceDraft, ref: EvidenceRef) -> None:
    draft.issues.append(
        ExtractionIssue(
            code=FindingCode.unparsed_line, message="line not recognized", evidence=[ref]
        )
    )
