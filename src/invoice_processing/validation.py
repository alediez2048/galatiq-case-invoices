"""Pure validation checks over a NormalizedInvoice. No I/O except the *_against_db wrapper."""

import sqlite3
from collections.abc import Collection, Iterable
from datetime import date
from decimal import Decimal, InvalidOperation

from invoice_processing.codes import DEFAULT_SEVERITY, FindingCode
from invoice_processing.money import MINOR_UNITS, compare, quantize
from invoice_processing.schemas import (
    AggregatedItem,
    ComputedTotals,
    EvidenceRef,
    LineItem,
    NormalizedInvoice,
    ValidationFinding,
)
from invoice_processing.storage import get_stock

C = FindingCode


def _finding(
    code: FindingCode,
    *,
    field: str | None = None,
    item: str | None = None,
    expected: str | None = None,
    observed: str | None = None,
    evidence: Iterable[EvidenceRef] = (),
) -> ValidationFinding:
    return ValidationFinding(
        code=code,
        severity=DEFAULT_SEVERITY[code],
        field=field,
        item=item,
        expected=expected,
        observed=observed,
        evidence=list(evidence),
    )


def _blank(value: str | None) -> bool:
    return value is None or not value.strip()


def _line_label(line: LineItem, index: int) -> str:
    return line.item if not _blank(line.item) else f"line:{index}"


def check_required_fields(
    invoice: NormalizedInvoice, *, unresolved: Collection[str] = ()
) -> list[ValidationFinding]:
    """Fields in `unresolved` already carry a review finding, so no missing_<field> is added."""
    missing = [
        (C.missing_vendor, "vendor", _blank(invoice.vendor_name)),
        (C.missing_invoice_number, "invoice_number", _blank(invoice.invoice_number)),
        (C.missing_due_date, "due_date", invoice.due_date is None),
        (C.missing_currency, "currency", _blank(invoice.currency)),
        (C.missing_total, "total", invoice.stated.total is None),
        (C.missing_line_items, "lines", not invoice.lines),
    ]
    findings = [
        _finding(code, field=field)
        for code, field, absent in missing
        if absent and field not in unresolved
    ]
    for index, line in enumerate(invoice.lines):
        if _blank(line.item) or line.quantity is None or line.unit_price is None:
            findings.append(
                _finding(
                    C.incomplete_line_item,
                    field=f"lines[{index}]",
                    item=_line_label(line, index),
                    evidence=line.evidence,
                )
            )
    return findings


def check_value_signs(invoice: NormalizedInvoice) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    for index, line in enumerate(invoice.lines):
        label = _line_label(line, index)
        q = line.quantity
        if q is not None:
            if q <= 0:
                findings.append(
                    _finding(
                        C.non_positive_quantity,
                        field=f"lines[{index}].quantity",
                        item=label,
                        observed=str(q),
                        evidence=line.evidence,
                    )
                )
            if q != q.to_integral_value():
                findings.append(
                    _finding(
                        C.non_integer_quantity,
                        field=f"lines[{index}].quantity",
                        item=label,
                        observed=str(q),
                        evidence=line.evidence,
                    )
                )
        if line.unit_price is not None and line.unit_price < 0:
            findings.append(
                _finding(
                    C.negative_unit_price,
                    field=f"lines[{index}].unit_price",
                    item=label,
                    observed=str(line.unit_price),
                    evidence=line.evidence,
                )
            )
    stated = invoice.stated
    if stated.total is not None and stated.total <= 0:
        findings.append(_finding(C.non_positive_total, field="total", observed=str(stated.total)))
    if stated.tax is not None and stated.tax < 0:
        findings.append(_finding(C.negative_tax, field="tax", observed=str(stated.tax)))
    if stated.shipping is not None and stated.shipping < 0:
        findings.append(
            _finding(C.negative_shipping, field="shipping", observed=str(stated.shipping))
        )
    return findings


def check_due_date(invoice: NormalizedInvoice, evaluation_date: date) -> list[ValidationFinding]:
    if invoice.due_date is None or invoice.due_date >= evaluation_date:
        return []
    return [
        _finding(
            C.due_date_past,
            field="due_date",
            expected=evaluation_date.isoformat(),
            observed=invoice.due_date.isoformat(),
        )
    ]


def _compare_amount(
    findings: list[ValidationFinding],
    code: FindingCode,
    *,
    stated: Decimal,
    computed: Decimal,
    currency: str,
    field: str,
    item: str | None = None,
) -> None:
    """Append a mismatch blocker, or rounding_tolerated for a non-zero difference within 0.01."""
    diff = compare(stated, computed, currency)
    if diff.difference == 0:
        return
    finding_code = C.rounding_tolerated if diff.within_tolerance else code
    findings.append(
        _finding(
            finding_code,
            field=field,
            item=item,
            expected=str(quantize(computed, currency)),
            # The stated value as written, so a sub-cent difference stays visible.
            observed=str(stated),
        )
    )


def reconcile_totals(invoice: NormalizedInvoice) -> tuple[ComputedTotals, list[ValidationFinding]]:
    """Recompute line totals, subtotal, tax, and total. Stated values are never modified.

    Absent tax and shipping count as zero. The computed subtotal (not the stated one) feeds the
    total check. A line without quantity or unit price makes subtotal and total unverifiable.
    """
    # A missing currency is already a blocker (missing_currency); USD here only lets the
    # arithmetic still be checked. The recorded USD assumption itself is normalization's job.
    currency = invoice.currency if invoice.currency is not None else "USD"
    if currency not in MINOR_UNITS:
        # Unsupported or unnormalized currency: the currency check routes it; arithmetic
        # cannot be rounded to an unknown minor unit, so it is reported, not raised.
        return ComputedTotals(), [_finding(C.arithmetic_unverifiable, field="currency")]
    try:
        return _reconcile(invoice, currency)
    except InvalidOperation:
        # Magnitudes beyond decimal precision (e.g. 1e20 x 1e10) cannot be verified exactly.
        return ComputedTotals(), [_finding(C.arithmetic_unverifiable, field="lines")]


def _reconcile(
    invoice: NormalizedInvoice, currency: str
) -> tuple[ComputedTotals, list[ValidationFinding]]:
    stated = invoice.stated
    findings: list[ValidationFinding] = []
    line_totals: list[Decimal | None] = []

    for index, line in enumerate(invoice.lines):
        label = _line_label(line, index)
        if line.quantity is None or line.unit_price is None:
            line_totals.append(None)
            findings.append(
                _finding(C.arithmetic_unverifiable, field=f"lines[{index}]", item=label)
            )
            continue
        line_total = quantize(line.quantity * line.unit_price, currency)
        line_totals.append(line_total)
        if line.line_total is not None:
            _compare_amount(
                findings,
                C.line_total_mismatch,
                stated=line.line_total,
                computed=line_total,
                currency=currency,
                field=f"lines[{index}].line_total",
                item=label,
            )

    tax = stated.tax if stated.tax is not None else Decimal(0)
    shipping = stated.shipping if stated.shipping is not None else Decimal(0)
    if any(t is None for t in line_totals):
        return ComputedTotals(line_totals=line_totals, tax=tax, shipping=shipping), findings

    subtotal = quantize(sum((t for t in line_totals if t is not None), Decimal(0)), currency)
    if stated.subtotal is not None:
        _compare_amount(
            findings,
            C.subtotal_mismatch,
            stated=stated.subtotal,
            computed=subtotal,
            currency=currency,
            field="subtotal",
        )
    if stated.tax_rate is not None and stated.tax is not None:
        _compare_amount(
            findings,
            C.tax_mismatch,
            stated=stated.tax,
            computed=quantize(subtotal * stated.tax_rate, currency),
            currency=currency,
            field="tax",
        )
    total = quantize(subtotal + tax + shipping, currency)
    if stated.total is not None:
        _compare_amount(
            findings,
            C.total_mismatch,
            stated=stated.total,
            computed=total,
            currency=currency,
            field="total",
        )
    computed = ComputedTotals(
        line_totals=line_totals, subtotal=subtotal, tax=tax, shipping=shipping, total=total
    )
    return computed, findings


def aggregate_quantities(lines: list[LineItem]) -> dict[str, AggregatedItem]:
    """Total quantity per exact item name. Alias and case rules belong to normalization."""
    aggregated: dict[str, AggregatedItem] = {}
    for index, line in enumerate(lines):
        if _blank(line.item) or line.quantity is None:
            continue
        entry = aggregated.get(line.item)
        if entry is None:
            aggregated[line.item] = AggregatedItem(
                item=line.item, quantity=line.quantity, line_indexes=[index]
            )
        else:
            entry.quantity += line.quantity
            entry.line_indexes.append(index)
    return aggregated


def check_inventory(
    aggregated: dict[str, AggregatedItem], stock: dict[str, int | None]
) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    for item, entry in aggregated.items():
        available = stock.get(item)
        requested = str(entry.quantity)
        if available is None:
            findings.append(_finding(C.unknown_item, item=item, observed=requested))
        elif available == 0:
            findings.append(_finding(C.zero_stock, item=item, expected="0", observed=requested))
        elif entry.quantity > available:
            findings.append(
                _finding(
                    C.quantity_exceeds_stock,
                    item=item,
                    expected=str(available),
                    observed=requested,
                )
            )
    return findings


def check_inventory_against_db(
    conn: sqlite3.Connection, aggregated: dict[str, AggregatedItem]
) -> list[ValidationFinding]:
    return check_inventory(aggregated, get_stock(conn, aggregated))
