"""Normalization: raw draft strings to typed values, with an audit trail.

Every change to a raw value is a NormalizationEvent with a "rule:<name>" provenance and the
evidence it rests on. Values that cannot be converted stay None and raise a review finding.
"""

import re
from collections.abc import Callable, Collection
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from invoice_processing.codes import DEFAULT_SEVERITY, FindingCode
from invoice_processing.dates import AmbiguousDate, RelativeDate, parse_date
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
_NET_TERMS = re.compile(r"net\s*(\d+)", re.IGNORECASE)
_URGENCY = re.compile(
    r"\b(urgent|immediately|asap|wire transfer|penalt(y|ies)|final notice)\b", re.IGNORECASE
)
# Text addressed to an AI system rather than to accounts payable (P3-07). Info only.
EMBEDDED_INSTRUCTIONS = re.compile(
    "|".join(
        (
            r"ignore (all |any )?(previous |prior )?instructions",
            r"you are (now )?(an?|the) ",
            r"approve this invoice",
            r"mark (this|as) (approved|paid)",
            r"(manager|cfo|director) (has )?(already )?approved",
            r"inventory has been updated",
            r"\"recommendation\"\s*:",
            r"tool_call",
            r"function_call",
            r"system prompt",
        )
    ),
    re.IGNORECASE,
)
_SYMBOL_CODES = {"$": "USD", "€": "EUR", "£": "GBP"}
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
        # A number made only of separators has no identity; the ledger uses a provisional one.
        number_key = invoice_number_key(draft.invoice_number_raw) or None
        if number_key is not None and number_key != draft.invoice_number_raw.strip():
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
        # JSON/XML/CSV parsers file the fraction's evidence under "tax_rate_fraction".
        fraction_ev = field_ev("tax_rate_fraction") or field_ev("tax_rate")
        tax_rate = convert("tax_rate", draft.tax_rate_fraction_raw, parse_decimal, fraction_ev)

    def amount(name: str, raw: str | None) -> Decimal | None:
        return convert(name, raw, parse_amount, field_ev(name), ocr_ok=True)

    def day(name: str, raw: str | None) -> date | None:
        ev = field_ev(name)
        if raw is None:
            return None
        corrected = ocr(raw, parse_date)
        if corrected is not None:
            fixed, value = corrected
            event(name, raw, fixed, ev, "ocr_digit")
            return value
        try:
            return parse_date(raw)
        except RelativeDate:
            if name == "due_date":
                event(name, raw, None, ev, "unresolved_date")
                finding(FindingCode.due_date_unresolved, name, ev, observed=raw)
                return None
        except AmbiguousDate:
            event(name, raw, None, ev, "ambiguous_date")
            finding(FindingCode.ambiguous_date, name, ev, observed=raw)
            return None
        except ValueError:
            pass
        unparseable(name, raw, ev)
        return None

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
        # Where each header field was read; review corrections check citations against it.
        field_evidence={name: list(refs) for name, refs in draft.field_evidence.items()},
    )

    _check_dates(invoice, finding, field_ev)
    _resolve_currency(draft, invoice, event, finding, field_ev)
    _urgency(draft, finding, field_ev)
    embedded = detect_embedded_instructions(draft)
    if embedded is not None:
        findings.append(embedded)
    invoice.normalization_events = events
    return invoice, findings


def _present(value: str | None) -> bool:
    return value is not None and bool(value.strip())


def _text(value: str | None) -> str | None:
    return value.strip() if _present(value) else None


def _check_dates(invoice: NormalizedInvoice, finding, field_ev) -> None:
    issued, due = invoice.invoice_date, invoice.due_date
    if issued is None or due is None:
        return
    ev = field_ev("due_date")
    if due < issued:
        finding(
            FindingCode.due_before_invoice_date,
            "due_date",
            ev,
            expected=issued.isoformat(),
            observed=due.isoformat(),
        )
    terms = _NET_TERMS.fullmatch(invoice.payment_terms or "")
    if terms is not None:
        expected = issued + timedelta(days=int(terms[1]))
        if due != expected:
            finding(
                FindingCode.terms_inconsistent,
                "payment_terms",
                field_ev("payment_terms"),
                expected=expected.isoformat(),
                observed=due.isoformat(),
            )


def _amount_fields(draft: InvoiceDraft):
    """(field, raw, evidence) for every raw amount, in draft field order, then lines."""
    for name in ("subtotal", "tax", "shipping", "total"):
        raw = getattr(draft, f"{name}_raw")
        if raw is not None:
            yield name, raw, list(draft.field_evidence.get(name, []))
    for i, line in enumerate(draft.lines):
        for name, raw in (("unit_price", line.unit_price_raw), ("line_total", line.line_total_raw)):
            if raw is not None:
                yield f"lines[{i}].{name}", raw, line.evidence


def _resolve_currency(draft, invoice, event, finding, field_ev) -> None:
    seen = [
        (_SYMBOL_CODES[sym], ev)
        for _, raw, ev in _amount_fields(draft)
        for sym in _SYMBOL_CODES
        if sym in raw
    ]
    ev = field_ev("currency")
    code = draft.currency_raw.strip().upper() if _present(draft.currency_raw) else None
    if code is not None:
        invoice.currency = code
        if code != "USD":
            finding(FindingCode.unsupported_currency, "currency", ev, observed=code)
        clash = next(((c, e) for c, e in seen if c != code), None)
        if clash is not None:
            finding(
                FindingCode.currency_conflict,
                "currency",
                clash[1],
                expected=code,
                observed=clash[0],
            )
        return
    other = next(((c, e) for c, e in seen if c != "USD"), None)
    if other is not None:
        invoice.currency = other[0]
        finding(FindingCode.unsupported_currency, "currency", other[1], observed=other[0])
        return
    dollar = next((e for _, raw, e in _all_raw(draft) if "$" in raw), None)
    invoice.currency = "USD"
    cited = dollar or []
    event("currency", None, "USD", cited, "dataset_usd_assumption")
    finding(FindingCode.currency_assumed_usd, "currency", cited, observed="USD")


def _all_raw(draft: InvoiceDraft):
    """(field, raw, evidence) for every raw field value, in draft field order, then lines."""
    for name in type(draft).model_fields:
        raw = getattr(draft, name)
        if name.endswith("_raw") and isinstance(raw, str):
            key = name.removesuffix("_raw")
            yield key, raw, list(draft.field_evidence.get(key, []))
    for line in draft.lines:
        for raw in (line.unit_price_raw, line.line_total_raw):
            if raw is not None:
                yield "line", raw, line.evidence


def _urgency(draft: InvoiceDraft, finding, field_ev) -> None:
    sources = [
        (draft.notes_raw, field_ev("notes")),
        (draft.payment_terms_raw, field_ev("payment_terms")),
    ]
    sources += [
        (issue.evidence[0].snippet, list(issue.evidence[:1]))
        for issue in draft.issues
        if issue.code == FindingCode.unparsed_line and issue.evidence
    ]
    for text, ev in sources:
        m = _URGENCY.search(text or "")
        if m is not None:
            finding(FindingCode.risk_signal_urgency, "notes", ev, observed=m[0])
            return


def _evidence_lines(draft: InvoiceDraft):
    """Every evidence reference with a snippet, roughly in document order, each once."""
    refs = [*draft.evidence]
    refs += [ref for issue in draft.issues for ref in issue.evidence]
    refs += [ref for line in draft.lines for ref in line.evidence]
    refs += [ref for field_refs in draft.field_evidence.values() for ref in field_refs]
    seen: set[tuple[str, str]] = set()
    for ref in refs:
        if ref.snippet and (ref.location, ref.snippet) not in seen:
            seen.add((ref.location, ref.snippet))
            yield ref


def detect_embedded_instructions(draft: InvoiceDraft) -> ValidationFinding | None:
    """An info finding when the document holds text aimed at an AI system (all modes).

    The evidence is the first matching source line; raw field values are checked too, for
    formats whose snippets are truncated.
    """
    code = FindingCode.risk_signal_embedded_instructions
    for ref in _evidence_lines(draft):
        m = EMBEDDED_INSTRUCTIONS.search(ref.snippet or "")
        if m is not None:
            return ValidationFinding(
                code=code, severity=DEFAULT_SEVERITY[code], observed=m[0], evidence=[ref]
            )
    for name, raw, ev in _all_raw(draft):
        m = EMBEDDED_INSTRUCTIONS.search(raw)
        if m is not None:
            return ValidationFinding(
                code=code,
                severity=DEFAULT_SEVERITY[code],
                field=name,
                observed=m[0],
                evidence=ev[:1],
            )
    return None
