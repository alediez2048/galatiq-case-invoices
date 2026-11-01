"""Minimal Phase 1 normalization: raw draft strings to typed values, with an audit trail."""

from datetime import date
from decimal import Decimal

from invoice_processing.codes import DEFAULT_SEVERITY, FindingCode
from invoice_processing.money import parse_decimal
from invoice_processing.schemas import (
    EvidenceRef,
    InvoiceDraft,
    LineItem,
    NormalizationEvent,
    NormalizedInvoice,
    StatedTotals,
    ValidationFinding,
)


def parse_amount(raw: str) -> Decimal:
    text = raw.strip()
    if text.startswith("$"):
        text = text[1:]
    return parse_decimal(text.replace(",", ""))


def vendor_key(name: str) -> str:
    return " ".join(name.split()).casefold()


def invoice_number_key(number: str) -> str:
    return number.strip().upper()


def normalize(draft: InvoiceDraft) -> tuple[NormalizedInvoice, list[ValidationFinding]]:
    events: list[NormalizationEvent] = []

    def convert(field: str, raw: str | None, parser, evidence: list[EvidenceRef]):
        if raw is None:
            return None
        try:
            return parser(raw)
        except ValueError:
            events.append(
                NormalizationEvent(
                    field=field,
                    raw_value=raw,
                    normalized_value=None,
                    evidence=evidence,
                    provenance="rule:unparseable",
                )
            )
            return None

    def tax_rate(raw: str) -> Decimal:
        return parse_decimal(raw) / 100

    ev = draft.evidence
    lines = [
        LineItem(
            item=line.raw_name,
            quantity=convert(
                f"lines[{i}].quantity", line.quantity_raw, parse_decimal, line.evidence
            ),
            unit_price=convert(
                f"lines[{i}].unit_price", line.unit_price_raw, parse_amount, line.evidence
            ),
            line_total=convert(
                f"lines[{i}].line_total", line.line_total_raw, parse_amount, line.evidence
            ),
            note=line.note,
            evidence=line.evidence,
        )
        for i, line in enumerate(draft.lines)
    ]
    invoice = NormalizedInvoice(
        source_id=draft.source_id,
        vendor_name=draft.vendor_raw,
        vendor_key=vendor_key(draft.vendor_raw) if _present(draft.vendor_raw) else None,
        invoice_number=draft.invoice_number_raw,
        invoice_number_key=(
            invoice_number_key(draft.invoice_number_raw)
            if _present(draft.invoice_number_raw)
            else None
        ),
        revision=draft.revision_raw,
        invoice_date=convert("invoice_date", draft.invoice_date_raw, date.fromisoformat, ev),
        due_date=convert("due_date", draft.due_date_raw, date.fromisoformat, ev),
        currency=draft.currency_raw,
        lines=lines,
        stated=StatedTotals(
            subtotal=convert("subtotal", draft.subtotal_raw, parse_amount, ev),
            tax_rate=convert("tax_rate", draft.tax_rate_raw, tax_rate, ev),
            tax=convert("tax", draft.tax_raw, parse_amount, ev),
            shipping=convert("shipping", draft.shipping_raw, parse_amount, ev),
            total=convert("total", draft.total_raw, parse_amount, ev),
        ),
    )

    findings: list[ValidationFinding] = []
    if draft.currency_raw is None:
        dollar = next((e for e in draft.evidence if "$" in (e.snippet or "")), None)
        if dollar is not None:
            invoice.currency = "USD"
            events.append(
                NormalizationEvent(
                    field="currency",
                    raw_value=None,
                    normalized_value="USD",
                    evidence=[dollar],
                    provenance="rule:dataset_usd_assumption",
                )
            )
            code = FindingCode.currency_assumed_usd
            findings.append(
                ValidationFinding(
                    code=code,
                    severity=DEFAULT_SEVERITY[code],
                    field="currency",
                    observed="USD",
                    evidence=[dollar],
                )
            )
    invoice.normalization_events = events
    return invoice, findings


def _present(value: str | None) -> bool:
    return value is not None and bool(value.strip())
