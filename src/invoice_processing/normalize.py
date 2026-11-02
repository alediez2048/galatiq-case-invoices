"""Normalization: raw draft strings to typed values, with an audit trail.

Every change to a raw value is a NormalizationEvent with a "rule:<name>" provenance and the
evidence it rests on. Values that cannot be converted stay None and raise a review finding.
"""

import re
from collections.abc import Callable, Collection
from datetime import date
from decimal import Decimal
from typing import Any

from invoice_processing.codes import DEFAULT_SEVERITY, FindingCode
from invoice_processing.money import parse_decimal
from invoice_processing.schemas import (
    DraftLine,
    EvidenceRef,
    InvoiceDraft,
    LineItem,
    NormalizationEvent,
    NormalizedInvoice,
    StatedTotals,
    ValidationFinding,
)

_AMOUNT = re.compile(r"(?P<pre>-)?(?P<sym>[$€£])?(?P<post>-)?(?P<body>.*)")
_PLAIN = re.compile(r"\d+(\.\d+)?")
_GROUPED = re.compile(r"\d{1,3}(,\d{3})+(\.\d+)?")
_OCR_O = re.compile(r"(?<=[\d.,])O|O(?=[\d.,])")
_KEY_STRIP = re.compile(r"[\s\-_/#.]")
_INV_PREFIX = re.compile(r"^INV(?=\d)")
_QUALIFIER = re.compile(r"^(?P<base>.+?)\s*\((?P<q>[^()]+)\)$")


def parse_amount(raw: str) -> Decimal:
    m = _AMOUNT.fullmatch(raw.strip())
    if m is None or (m["pre"] and m["post"]):
        raise ValueError(f"not an amount: {raw!r}")
    body = m["body"]
    if _PLAIN.fullmatch(body):
        value = parse_decimal(body)
    elif _GROUPED.fullmatch(body):
        value = parse_decimal(body.replace(",", ""))
    else:
        raise ValueError(f"not an amount: {raw!r}")
    return -value if m["pre"] or m["post"] else value


def fix_ocr_digits(raw: str) -> str | None:
    """Read a letter O touching a digit, '.' or ',' as a zero. None if nothing changed."""
    fixed = _OCR_O.sub("0", raw)
    return None if fixed == raw else fixed


def vendor_key(name: str) -> str:
    return " ".join(name.split()).casefold()


def invoice_number_key(number: str) -> str:
    return _INV_PREFIX.sub("", _KEY_STRIP.sub("", number.upper()))


def _tax_rate_percent(raw: str) -> Decimal:
    return parse_decimal(raw) / 100


def normalize(
    draft: InvoiceDraft, known_items: Collection[str] = ()
) -> tuple[NormalizedInvoice, list[ValidationFinding]]:
    events: list[NormalizationEvent] = list(draft.normalization_events)
    findings: list[ValidationFinding] = []
    known = set(known_items)

    def field_ev(name: str) -> list[EvidenceRef]:
        return list(draft.field_evidence.get(name, []))

    def event(field: str, raw: str | None, value: str | None, ev: list[EvidenceRef], rule: str):
        events.append(
            NormalizationEvent(
                field=field,
                raw_value=raw,
                normalized_value=value,
                evidence=list(ev),
                provenance=f"rule:{rule}",
            )
        )

    def finding(code: FindingCode, field: str, ev: list[EvidenceRef], **extra: str | None):
        findings.append(
            ValidationFinding(
                code=code,
                severity=DEFAULT_SEVERITY[code],
                field=field,
                evidence=list(ev),
                **extra,
            )
        )

    def unparseable(field: str, raw: str, ev: list[EvidenceRef]) -> None:
        event(field, raw, None, ev, "unparseable")
        finding(FindingCode.unparseable_value, field, ev, observed=raw)

    def ocr(raw: str, parser: Callable[[str], Any]) -> tuple[str, Any] | None:
        """The OCR-corrected text and its parsed value, if a correction exists and parses."""
        fixed = fix_ocr_digits(raw)
        if fixed is None:
            return None
        try:
            return fixed, parser(fixed)
        except ValueError:
            return None

    def convert(
        field: str,
        raw: str | None,
        parser: Callable[[str], Any],
        ev: list[EvidenceRef],
        *,
        ocr_ok: bool = False,
    ) -> Any:
        if raw is None:
            return None
        corrected = ocr(raw, parser) if ocr_ok else None
        if corrected is not None:
            fixed, value = corrected
            event(field, raw, fixed, ev, "ocr_digit")
            return value
        try:
            return parser(raw)
        except ValueError:
            unparseable(field, raw, ev)
            return None

    def line_total(i: int, line: DraftLine, qty: Decimal | None, price: Decimal | None):
        field, raw, ev = f"lines[{i}].line_total", line.line_total_raw, line.evidence
        corrected = ocr(raw, parse_amount) if raw is not None else None
        if corrected is None:
            return convert(field, raw, parse_amount, ev)
        fixed, value = corrected
        if qty is not None and price is not None and value != qty * price:
            finding(
                FindingCode.ambiguous_normalization,
                field,
                ev,
                expected=str(qty * price),
                observed=raw,
            )
            return None
        event(field, raw, fixed, ev, "ocr_digit")
        return value

    def item_name(i: int, line: DraftLine) -> tuple[str | None, str | None]:
        """The canonical item name and the line note (with any qualifier appended)."""
        raw, note = line.raw_name, line.note
        if raw is None or raw in known:
            return raw, note
        field, ev = f"lines[{i}].item", line.evidence
        spaced = "".join(raw.split())
        if spaced in known:
            event(field, raw, spaced, ev, "item_spacing")
            return spaced, note
        m = _QUALIFIER.match(raw)
        if m is None:
            return raw, note
        base = m["base"]
        if base not in known and "".join(base.split()) in known:
            base = "".join(base.split())
            event(field, raw, base, ev, "item_spacing")
        if base not in known:
            return raw, note
        event(field, raw, base, ev, "item_qualifier")
        return base, "; ".join(x for x in (note, m["q"].strip()) if x)

    lines = []
    for i, line in enumerate(draft.lines):
        qty = convert(
            f"lines[{i}].quantity", line.quantity_raw, parse_decimal, line.evidence, ocr_ok=True
        )
        price = convert(
            f"lines[{i}].unit_price", line.unit_price_raw, parse_amount, line.evidence, ocr_ok=True
        )
        total = line_total(i, line, qty, price)
        item, note = item_name(i, line)
        lines.append(
            LineItem(
                item=item,
                quantity=qty,
                unit_price=price,
                line_total=total,
                note=note,
                evidence=line.evidence,
            )
        )

    number_key = None
    if _present(draft.invoice_number_raw):
        number_key = invoice_number_key(draft.invoice_number_raw)
        if number_key != draft.invoice_number_raw.strip():
            event(
                "invoice_number",
                draft.invoice_number_raw,
                number_key,
                field_ev("invoice_number"),
                "invoice_number_format",
            )

    if draft.tax_rate_raw is not None:
        tax_rate = convert("tax_rate", draft.tax_rate_raw, _tax_rate_percent, field_ev("tax_rate"))
    else:
        tax_rate = convert(
            "tax_rate", draft.tax_rate_fraction_raw, parse_decimal, field_ev("tax_rate")
        )

    def amount(name: str, raw: str | None) -> Decimal | None:
        return convert(name, raw, parse_amount, field_ev(name), ocr_ok=True)

    def day(name: str, raw: str | None) -> date | None:
        return convert(name, raw, date.fromisoformat, field_ev(name), ocr_ok=True)

    invoice = NormalizedInvoice(
        source_id=draft.source_id,
        vendor_name=draft.vendor_raw,
        vendor_key=vendor_key(draft.vendor_raw) if _present(draft.vendor_raw) else None,
        invoice_number=draft.invoice_number_raw,
        invoice_number_key=number_key,
        revision=draft.revision_raw,
        invoice_date=day("invoice_date", draft.invoice_date_raw),
        due_date=day("due_date", draft.due_date_raw),
        currency=draft.currency_raw,
        payment_terms=_text(draft.payment_terms_raw),
        notes=_text(draft.notes_raw),
        lines=lines,
        stated=StatedTotals(
            subtotal=amount("subtotal", draft.subtotal_raw),
            tax_rate=tax_rate,
            tax=amount("tax", draft.tax_raw),
            shipping=amount("shipping", draft.shipping_raw),
            total=amount("total", draft.total_raw),
        ),
    )

    if draft.currency_raw is None:
        dollar = next((e for e in draft.evidence if "$" in (e.snippet or "")), None)
        if dollar is not None:
            invoice.currency = "USD"
            event("currency", None, "USD", [dollar], "dataset_usd_assumption")
            finding(FindingCode.currency_assumed_usd, "currency", [dollar], observed="USD")
    invoice.normalization_events = events
    return invoice, findings


def _present(value: str | None) -> bool:
    return value is not None and bool(value.strip())


def _text(value: str | None) -> str | None:
    return value.strip() if _present(value) else None
