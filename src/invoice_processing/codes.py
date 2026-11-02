"""Status enums and stable finding codes. Codes are identifiers, never prose."""

from enum import StrEnum


class Severity(StrEnum):
    info = "info"
    warning = "warning"
    review = "review"  # routes to needs_review
    blocker = "blocker"  # routes to rejected


class Recommendation(StrEnum):
    """What a reasoning step proposes. Never authorizes payment by itself."""

    approve = "approve"
    reject = "reject"
    review = "review"


class GateOutcome(StrEnum):
    """Result of the deterministic policy gate (P1-04)."""

    approved = "approved"
    rejected = "rejected"
    needs_review = "needs_review"
    awaiting_human_approval = "awaiting_human_approval"


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


TERMINAL_RUN_STATUSES: frozenset[RunStatus] = frozenset(
    {
        RunStatus.paid_mock,
        RunStatus.rejected,
        RunStatus.needs_review,
        RunStatus.awaiting_human_approval,
        RunStatus.failed,
        RunStatus.duplicate,
    }
)
BUSINESS_OUTCOMES: frozenset[RunStatus] = frozenset(
    {
        RunStatus.paid_mock,
        RunStatus.rejected,
        RunStatus.needs_review,
        RunStatus.awaiting_human_approval,
    }
)


class HumanReviewAction(StrEnum):
    approve = "approve"
    decline = "decline"


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
    currency_assumed_usd = "currency_assumed_usd"
    model_disagreement = "model_disagreement"
    non_usd_currency = "non_usd_currency"
    unparsed_line = "unparsed_line"
    ambiguous_normalization = "ambiguous_normalization"
    unparseable_value = "unparseable_value"
    risk_signal_urgency = "risk_signal_urgency"
    due_date_unresolved = "due_date_unresolved"
    ambiguous_date = "ambiguous_date"
    due_before_invoice_date = "due_before_invoice_date"
    terms_inconsistent = "terms_inconsistent"
    unsupported_currency = "unsupported_currency"
    currency_conflict = "currency_conflict"
    revision_after_payment = "revision_after_payment"
    version_conflict = "version_conflict"
    unrecognized_field = "unrecognized_field"
    duplicate_field = "duplicate_field"
    malformed_row = "malformed_row"
    inconsistent_row_header = "inconsistent_row_header"


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
    C.currency_assumed_usd: "Currency was missing and USD was assumed.",
    C.model_disagreement: "The final recommendation was not approve on an otherwise clean invoice.",
    C.non_usd_currency: "Invoice currency is not USD.",
    C.unparsed_line: "A source line matched no known field and was ignored.",
    C.ambiguous_normalization: "A value could be normalized in more than one way.",
    C.unparseable_value: "A value could not be converted to its expected type.",
    C.risk_signal_urgency: "The document contains urgency language that is a risk signal.",
    C.due_date_unresolved: "The due date could not be resolved to a calendar date.",
    C.ambiguous_date: "A date could be read as day-month or month-day.",
    C.due_before_invoice_date: "The due date is before the invoice date.",
    C.terms_inconsistent: "Payment terms disagree with the invoice and due dates.",
    C.unsupported_currency: "The currency is not one the system supports.",
    C.currency_conflict: "The document states conflicting currencies.",
    C.revision_after_payment: "A revision arrived for an invoice that was already paid.",
    C.version_conflict: "A revision conflicts with an existing version of the invoice.",
    C.unrecognized_field: "A field was not recognized and was ignored.",
    C.duplicate_field: "A field appears more than once with different content.",
    C.malformed_row: "A table row does not match the expected shape.",
    C.inconsistent_row_header: "Line item rows are inconsistent with their header.",
}

_WARNINGS = {
    C.due_date_past,
    C.arithmetic_unverifiable,
    C.model_disagreement,
    C.due_before_invoice_date,
    C.terms_inconsistent,
}
_INFO = {
    C.rounding_tolerated,
    C.currency_assumed_usd,
    C.unparsed_line,
    C.risk_signal_urgency,
    C.unrecognized_field,
}
_REVIEW = {
    C.non_usd_currency,
    C.ambiguous_normalization,
    C.unparseable_value,
    C.due_date_unresolved,
    C.ambiguous_date,
    C.unsupported_currency,
    C.currency_conflict,
    C.revision_after_payment,
    C.version_conflict,
    C.duplicate_field,
    C.malformed_row,
}

DEFAULT_SEVERITY: dict[FindingCode, Severity] = {
    code: (
        Severity.warning
        if code in _WARNINGS
        else Severity.info
        if code in _INFO
        else Severity.review
        if code in _REVIEW
        else Severity.blocker
    )
    for code in FindingCode
}
