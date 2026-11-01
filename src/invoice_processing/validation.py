"""Pure validation checks over a NormalizedInvoice. No I/O except the *_against_db wrapper."""

from collections.abc import Iterable
from datetime import date

from invoice_processing.codes import DEFAULT_SEVERITY, FindingCode
from invoice_processing.schemas import EvidenceRef, LineItem, NormalizedInvoice, ValidationFinding

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


def check_required_fields(invoice: NormalizedInvoice) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    if _blank(invoice.vendor_name):
        findings.append(_finding(C.missing_vendor, field="vendor"))
    if _blank(invoice.invoice_number):
        findings.append(_finding(C.missing_invoice_number, field="invoice_number"))
    if invoice.due_date is None:
        findings.append(_finding(C.missing_due_date, field="due_date"))
    if _blank(invoice.currency):
        findings.append(_finding(C.missing_currency, field="currency"))
    if invoice.stated.total is None:
        findings.append(_finding(C.missing_total, field="total"))
    if not invoice.lines:
        findings.append(_finding(C.missing_line_items, field="lines"))
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
