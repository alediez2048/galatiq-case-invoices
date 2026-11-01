"""Status enums and stable finding codes. Codes are identifiers, never prose."""

from enum import StrEnum


class Severity(StrEnum):
    info = "info"
    warning = "warning"
    review = "review"  # routes to needs_review
    blocker = "blocker"  # routes to rejected


class RunStatus(StrEnum):
    """Lifecycle of one processing attempt."""

    received = "received"
    extracted = "extracted"
    validated = "validated"
    approval_pending = "approval_pending"
    approved = "approved"
    awaiting_human_approval = "awaiting_human_approval"
    paid_mock = "paid_mock"
    rejected = "rejected"
    needs_review = "needs_review"
    failed = "failed"
    duplicate = "duplicate"


class InvoiceStatus(StrEnum):
    """Current business state of one invoice identity. A duplicate run never changes it."""

    processing = "processing"
    paid_mock = "paid_mock"
    rejected = "rejected"
    needs_review = "needs_review"
    awaiting_human_approval = "awaiting_human_approval"
    failed = "failed"
    superseded = "superseded"


class ExecutionMode(StrEnum):
    offline = "offline"
    live = "live"


class SourceFormat(StrEnum):
    txt = "txt"
    json = "json"
    csv = "csv"
    xml = "xml"
    pdf = "pdf"


class FindingCode(StrEnum):
    missing_vendor = "missing_vendor"
    missing_invoice_number = "missing_invoice_number"
    missing_due_date = "missing_due_date"
    missing_currency = "missing_currency"
    missing_total = "missing_total"
    missing_line_items = "missing_line_items"
    incomplete_line_item = "incomplete_line_item"
    non_positive_quantity = "non_positive_quantity"
    non_integer_quantity = "non_integer_quantity"
    non_positive_total = "non_positive_total"
    negative_unit_price = "negative_unit_price"
    negative_tax = "negative_tax"
    negative_shipping = "negative_shipping"
    due_date_past = "due_date_past"
    line_total_mismatch = "line_total_mismatch"
    subtotal_mismatch = "subtotal_mismatch"
    tax_mismatch = "tax_mismatch"
    total_mismatch = "total_mismatch"
    rounding_tolerated = "rounding_tolerated"
    arithmetic_unverifiable = "arithmetic_unverifiable"
    unknown_item = "unknown_item"
    zero_stock = "zero_stock"
    quantity_exceeds_stock = "quantity_exceeds_stock"


C = FindingCode

FINDING_DESCRIPTIONS: dict[FindingCode, str] = {
    C.missing_vendor: "Vendor name is missing or blank.",
    C.missing_invoice_number: "Invoice number is missing or blank.",
    C.missing_due_date: "Due date is missing.",
    C.missing_currency: "Currency is missing.",
    C.missing_total: "Stated invoice total is missing.",
    C.missing_line_items: "Invoice has no line items.",
    C.incomplete_line_item: "A line item lacks an item name, quantity, or unit price.",
    C.non_positive_quantity: "A line quantity is zero or negative.",
    C.non_integer_quantity: "A line quantity is not a whole number.",
    C.non_positive_total: "Stated invoice total is zero or negative.",
    C.negative_unit_price: "A unit price is negative.",
    C.negative_tax: "Stated tax is negative.",
    C.negative_shipping: "Stated shipping is negative.",
    C.due_date_past: "Due date is before the evaluation date.",
    C.line_total_mismatch: "A stated line total differs from quantity times unit price.",
    C.subtotal_mismatch: "Stated subtotal differs from the sum of line totals.",
    C.tax_mismatch: "Stated tax differs from subtotal times the stated tax rate.",
    C.total_mismatch: "Stated total differs from subtotal plus tax plus shipping.",
    C.rounding_tolerated: "A difference of at most one cent was tolerated.",
    C.arithmetic_unverifiable: "Totals could not be recomputed because a line lacks inputs.",
    C.unknown_item: "Item is not in the inventory database.",
    C.zero_stock: "Item is in inventory with zero stock.",
    C.quantity_exceeds_stock: "Requested quantity exceeds available stock.",
}

_WARNINGS = {C.due_date_past, C.arithmetic_unverifiable}
_INFO = {C.rounding_tolerated}

DEFAULT_SEVERITY: dict[FindingCode, Severity] = {
    code: (
        Severity.warning
        if code in _WARNINGS
        else Severity.info
        if code in _INFO
        else Severity.blocker
    )
    for code in FindingCode
}
